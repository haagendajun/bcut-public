"""Capture One에도 표시하기 시험 (spec S6). 진짜 Capture One 대신 메모리 대역을 쓴다."""

from dataclasses import replace
from pathlib import Path

import pytest

from bcut.bridge.capture_one import VariantInfo
from bcut.bridge.osascript import AppleScriptError
from bcut.ui import capture
from bcut.ui.capture import KEYWORDS, build_plan, handle
from bcut.ui.marks import MarkStore, event_key, file_size

PICK, MAYBE, DISCARD = KEYWORDS["pick"], KEYWORDS["maybe"], KEYWORDS["discard"]


class Bridge:
    """Capture One 대역: 키워드만 붙고 떨어진다. 별점·태그는 바뀌지 않는다."""

    def __init__(self, folder: Path, names, catalog_keywords=None, catalog="bcut-test"):
        self.catalog_name = catalog
        self.variants = {n: VariantInfo(str(folder / n), n, 3, 2, ("사용자키워드",), "1", n)
                         for n in names}
        self.catalog_keywords = (
            [PICK, MAYBE, DISCARD] if catalog_keywords is None else catalog_keywords)
        self.writes = []

    def list_variants(self):
        return list(self.variants.values())

    def keywords(self):
        return list(self.catalog_keywords)

    def backup_catalog(self, location):
        self.writes.append(("backup", str(location)))

    def apply_keyword(self, keyword, refs):
        self.writes.append(("apply", keyword, [v for _, v in refs]))
        for _, vid in refs:
            v = self.variants[vid]
            if keyword not in v.keywords:
                self.variants[vid] = replace(v, keywords=(*v.keywords, keyword))
        return len(refs)

    def strip_keyword(self, keyword, refs):
        self.writes.append(("strip", keyword, [v for _, v in refs]))
        for _, vid in refs:
            v = self.variants[vid]
            self.variants[vid] = replace(v, keywords=tuple(k for k in v.keywords if k != keyword))
        return len(refs)


@pytest.fixture
def world(tmp_path):
    folder = tmp_path / "행사"
    folder.mkdir()
    names = ["A.CR3", "B.CR3", "C.CR3", "D.CR3", "E.CR3"]
    for n in names:
        (folder / n).write_bytes(n.encode() * 20)
    store = MarkStore(tmp_path / "events")
    key = event_key(folder)
    for n, kind in (("A.CR3", "pick"), ("B.CR3", "pick"), ("C.CR3", "maybe"), ("D.CR3", "discard")):
        store.set(key, n, file_size(folder / n), kind)
    return folder, set(names), store, tmp_path / "data", Bridge(folder, names)


def run(world, action, bridge=None, **extra):
    folder, names, store, data, default = world
    body = {"action": action, "catalog": "bcut-test", **extra}
    return handle(store, folder, names, data, body, make_bridge=lambda c: bridge or default,
                  now=lambda: "2026-10-20T10:00:00")


def test_plan_maps_kinds_to_the_three_keywords():
    marks = [{"file": "A", "kind": "pick"}, {"file": "B", "kind": "maybe"},
             {"file": "C", "kind": "discard"}]
    assert build_plan(marks) == {"A": [PICK], "B": [MAYBE], "C": [DISCARD]}
    assert set(KEYWORDS.values()) == {"bcut-셀렉", "bcut-보류", "bcut-버릴컷"}


def test_preview_writes_nothing_and_reports_counts(world):
    status, out = run(world, "preview")
    assert status == 200 and out["aborted"] is None and out["mode"] == "dry-run"
    assert out["planned"] == 4 and out["matched"] == 4
    assert out["keyword_counts"] == {DISCARD: 1, MAYBE: 1, PICK: 2}
    assert world[4].writes == []  # 카탈로그 백업도 키워드도 쓰지 않았다
    assert not list((world[3] / "capture-one").glob("**/bcut-backup.json"))  # 기록 파일도 없음


def test_apply_adds_only_keywords_and_keeps_rating_color_and_user_keywords(world):
    status, out = run(world, "apply")
    assert status == 200 and out["ok"] and out["applied_files"] == 4 and out["backup"]
    bridge = world[4]
    a, e = bridge.variants["A.CR3"], bridge.variants["E.CR3"]
    assert a.keywords == ("사용자키워드", PICK) and (a.rating, a.color_tag) == (3, 2)
    assert e.keywords == ("사용자키워드",)  # 표시 안 한 사진은 그대로
    assert [w[0] for w in bridge.writes][0] == "backup"  # 백업이 먼저
    assert {w[0] for w in bridge.writes} <= {"backup", "apply"}  # 떼기·다른 쓰기 없음
    assert (world[3] / "capture-one").exists()


def test_apply_twice_adds_nothing_new(world):
    run(world, "apply")
    n = len(world[4].writes)
    status, out = run(world, "apply")
    assert out["already"] == 4 and out["keyword_counts"] == {} and out["applied_files"] == 0
    assert all(w[0] != "apply" for w in world[4].writes[n:])


def test_rollback_strips_only_tool_keywords(world):
    run(world, "apply")
    bridge = world[4]
    status, out = run(world, "rollback", commit=True)
    assert status == 200 and out["ok"] and out["stripped_files"] == 4
    assert bridge.variants["A.CR3"].keywords == ("사용자키워드",)
    assert bridge.variants["A.CR3"].rating == 3


def test_rollback_preview_does_not_strip(world):
    run(world, "apply")
    status, out = run(world, "rollback")
    assert out["mode"] == "dry-run" and out["strip_files"] == 4
    assert all(w[0] != "strip" for w in world[4].writes)


def test_missing_catalog_keywords_abort_without_changes(world):
    folder, names, *_ = world
    bridge = Bridge(folder, names, catalog_keywords=[PICK])
    status, out = run(world, "apply", bridge=bridge)
    assert out["aborted"] and set(out["missing_keywords"]) == {MAYBE, DISCARD}
    assert bridge.writes == []
    assert all(v.keywords == ("사용자키워드",) for v in bridge.variants.values())


def test_photos_not_in_catalog_abort_unless_allow_partial(world):
    folder, names, *_ = world
    bridge = Bridge(folder, ["A.CR3", "B.CR3", "C.CR3"])  # D가 카탈로그에 없다
    status, out = run(world, "apply", bridge=bridge)
    assert out["aborted"] and out["missing"] == ["D.CR3"] and bridge.writes == []
    status, out = run(world, "apply", bridge=bridge, allow_partial=True)
    assert out["aborted"] is None and out["applied_files"] == 3


def test_no_marks_stops_with_easy_message(tmp_path):
    folder = tmp_path / "빈행사"
    folder.mkdir()
    (folder / "A.CR3").write_bytes(b"x")
    bridge = Bridge(folder, ["A.CR3"])
    body = {"action": "preview", "catalog": "bcut-test"}
    status, out = handle(MarkStore(tmp_path / "ev"), folder, {"A.CR3"}, tmp_path / "d", body,
                         make_bridge=lambda c: bridge)
    assert status == 200 and "표시한 사진이 없어요" in out["aborted"] and bridge.writes == []


def test_wrong_catalog_is_reported_not_raised(world):
    class Wrong(Bridge):
        def list_variants(self):
            raise AppleScriptError("wrong catalog: 다른 카탈로그 (expected bcut-test)")

    folder, names, *_ = world
    status, out = run(world, "preview", bridge=Wrong(folder, names))
    assert status == 502 and "error" in out


def test_bad_requests():
    store, folder = MarkStore(Path("/nonexistent-bcut")), Path("/x")
    assert handle(store, folder, set(), Path("/d"), {"action": "x", "catalog": "c"})[0] == 400
    assert handle(store, folder, set(), Path("/d"), {"action": "preview", "catalog": " "})[0] == 400


def test_module_never_touches_ratings_or_color_tags():
    text = Path(capture.__file__).read_text(encoding="utf-8")
    for word in ("rating", "color_tag", "color tag", "strip_keyword"):
        assert word not in text, word
