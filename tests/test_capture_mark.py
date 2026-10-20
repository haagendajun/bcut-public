"""Capture One에도 표시하기 시험 (spec S6). 진짜 Capture One 대신 메모리 대역을 쓴다."""

from dataclasses import replace
from pathlib import Path

import pytest

from bcut.bridge.capture_one import VariantInfo
from bcut.bridge.osascript import AppleScriptError
from bcut.ui.capture import KEYWORDS, build_plan, handle
from bcut.ui.marks import MarkStore, event_key, file_size

PICK, MAYBE, DISCARD = KEYWORDS["pick"], KEYWORDS["maybe"], KEYWORDS["discard"]


class Bridge:
    """Capture One 대역: 키워드만 붙고 떨어진다. 별점·태그는 바뀌지 않는다."""

    def __init__(self, folder: Path, names, catalog_keywords=None, catalog="bcut-test",
                 rating=3, color=2):
        self.catalog_name = catalog
        self.variants = {
            n: VariantInfo(str(folder / n), n, rating, color, ("사용자키워드",), "1", n)
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

    def set_rating(self, value, refs):
        self.writes.append(("rating", value, [v for _, v in refs]))
        for _, vid in refs:
            self.variants[vid] = replace(self.variants[vid], rating=value)
        return len(refs)

    def set_color_tag(self, value, refs):
        self.writes.append(("color", value, [v for _, v in refs]))
        for _, vid in refs:
            self.variants[vid] = replace(self.variants[vid], color_tag=value)
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


def test_session_skips_catalog_backup_and_marks_the_response(world):
    folder, names, *_ = world

    class SessionBridge(Bridge):
        session = False

        def document_kind(self):
            return "session"

    bridge = SessionBridge(folder, names)
    status, out = run(world, "apply", bridge=bridge)
    assert status == 200 and out["session"] is True and out["ok"] and bridge.session is True
    assert all(w[0] != "backup" for w in bridge.writes)  # 세션에는 백업 명령이 없다
    assert out["backup"]  # 되돌리기용 기록(직전 키워드)은 만든다
    status, out = run(world, "rollback", bridge=bridge, commit=True)
    assert out["ok"] and bridge.variants["A.CR3"].keywords == ("사용자키워드",)


def test_catalog_document_still_gets_a_catalog_backup(world):
    class CatalogBridge(Bridge):
        session = False

        def document_kind(self):
            return "catalog"

    folder, names, *_ = world
    bridge = CatalogBridge(folder, names)
    status, out = run(world, "apply", bridge=bridge)
    assert out["session"] is False and bridge.writes[0][0] == "backup"


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


def test_each_document_keeps_its_own_undo_record(world):
    """같은 행사를 카탈로그에 반영한 뒤 세션에 반영해도 서로의 기록을 거절하지 않는다."""
    folder, names, *_ = world
    first = Bridge(folder, names, catalog="test")
    second = Bridge(folder, names, catalog="sejun.cosessiondb")
    assert run(world, "apply", bridge=first, catalog="test")[1]["ok"]
    status, out = run(world, "apply", bridge=second, catalog="sejun.cosessiondb")
    assert out["aborted"] is None and out["ok"] and out["applied_files"] == 4
    # 각자 되돌린다
    assert run(world, "rollback", bridge=second, catalog="sejun.cosessiondb", commit=True)[1]["ok"]
    assert run(world, "rollback", bridge=first, catalog="test", commit=True)[1]["ok"]
    assert second.variants["A.CR3"].keywords == ("사용자키워드",)
    assert first.variants["A.CR3"].keywords == ("사용자키워드",)


def test_legacy_record_of_the_same_document_is_still_used(world):
    folder, names, store, data, _ = world
    legacy_dir = data / "capture-one" / event_key(folder)
    legacy_dir.mkdir(parents=True)
    bridge = Bridge(folder, names, catalog="test")
    run(world, "apply", bridge=bridge, catalog="test")  # 새 방식: 문서별 폴더에 저장
    moved = next((data / "capture-one").rglob("bcut-backup.json"))
    moved.replace(legacy_dir / "bcut-backup.json")  # 예전 위치로 옮겨 예전 방식을 흉내
    status, out = run(world, "rollback", bridge=bridge, catalog="test", commit=True)
    assert out["aborted"] is None and out["stripped_files"] == 4


def test_default_never_touches_ratings_or_color_tags(world):
    run(world, "apply")
    bridge = world[4]
    assert all(w[0] not in ("rating", "color") for w in bridge.writes)
    assert all((v.rating, v.color_tag) == (3, 2) for v in bridge.variants.values())


STYLE = {"pick": {"rating": 5, "color": 4}, "maybe": {"rating": 3}, "discard": {"color": 1}}


def fresh(world, **kw):
    folder, names, *_ = world
    return Bridge(folder, names, rating=0, color=0, **kw)


def test_style_preview_counts_and_writes_nothing(world):
    bridge = fresh(world)
    status, out = run(world, "preview", bridge=bridge, style=STYLE)
    st = out["style"]
    assert st["rating_counts"] == {"3": 1, "5": 2} and st["color_counts"] == {"1": 1, "4": 2}
    assert st["applied"] is False and bridge.writes == []


def test_style_apply_sets_only_chosen_values_and_saves_before_values_first(world):
    bridge = fresh(world)
    seen = []
    orig = bridge.set_rating

    def spy(value, refs):
        seen.append((world[3] / "capture-one").glob("**/bcut-style-backup.json"))
        seen[-1] = list(seen[-1])
        return orig(value, refs)

    bridge.set_rating = spy
    status, out = run(world, "apply", bridge=bridge, style=STYLE)
    v = bridge.variants
    assert out["style"]["applied"] and not out["style"]["violations"]
    assert (v["A.CR3"].rating, v["A.CR3"].color_tag) == (5, 4)
    assert (v["C.CR3"].rating, v["C.CR3"].color_tag) == (3, 0)   # 보류: 별점만
    assert (v["D.CR3"].rating, v["D.CR3"].color_tag) == (0, 1)   # 버릴 컷: 컬러 태그만
    assert (v["E.CR3"].rating, v["E.CR3"].color_tag) == (0, 0)   # 표시 안 한 사진
    assert seen and all(seen)  # 별점을 쓰기 전에 이전 값 기록 파일이 이미 있었다


def test_existing_values_are_kept_unless_overwrite_is_on(world):
    folder, names, *_ = world
    bridge = Bridge(folder, names, rating=2, color=3)  # 모두 이미 값이 있다
    status, out = run(world, "apply", bridge=bridge, style=STYLE)
    assert out["style"]["skipped_rating"] == 3 and out["style"]["skipped_color"] == 3
    assert all((v.rating, v.color_tag) == (2, 3) for v in bridge.variants.values())
    status, out = run(world, "apply", bridge=bridge, style=STYLE, overwrite=True)
    assert bridge.variants["A.CR3"].rating == 5 and bridge.variants["A.CR3"].color_tag == 4


def test_style_is_not_applied_when_keywords_were_not(world):
    folder, names, *_ = world
    bridge = Bridge(folder, names, catalog_keywords=[PICK], rating=0, color=0)  # 키워드 없음
    status, out = run(world, "apply", bridge=bridge, style=STYLE)
    assert out["aborted"] and bridge.writes == []
    assert out["style"]["applied"] is False


def test_rollback_restores_each_value_separately_and_keeps_what_the_user_changed(world):
    bridge = fresh(world)
    run(world, "apply", bridge=bridge, style=STYLE)
    # 반영 뒤 사용자가 별점을 바꿈
    bridge.variants["B.CR3"] = replace(bridge.variants["B.CR3"], rating=2)
    status, out = run(world, "rollback", bridge=bridge, commit=True)
    v = bridge.variants
    assert out["style"]["restored"] and out["style"]["restore"] == 4
    assert (v["A.CR3"].rating, v["A.CR3"].color_tag) == (0, 0)
    assert v["B.CR3"].rating == 2  # 사용자가 바꾼 별점은 그대로
    assert v["B.CR3"].color_tag == 0  # 컬러 태그는 우리가 준 값 그대로라 되돌아간다
    assert v["A.CR3"].keywords == ("사용자키워드",)  # 키워드도 함께 되돌아간다


def test_rollback_works_when_only_one_of_rating_and_color_is_left(world):
    """실제 화면에서 본 문제: 별점은 이미 0인데 컬러 태그만 남은 사진이 되돌려지지 않았다."""
    bridge = fresh(world)
    run(world, "apply", bridge=bridge, style=STYLE)
    # 별점은 이미 0이고 컬러 태그(초록·빨강)만 남은 상태
    for n in ("A.CR3", "B.CR3"):
        bridge.variants[n] = replace(bridge.variants[n], rating=0)
    status, out = run(world, "rollback", bridge=bridge, commit=True)
    st = out["style"]
    assert st["restored"] and st["restore"] >= 3 and st["kept_user_changed"] == 0
    rest = [x for n, x in bridge.variants.items() if n != "C.CR3"]
    assert all(x.color_tag == 0 and x.rating == 0 for x in rest)
    again = run(world, "rollback", bridge=bridge)[1]["style"]
    assert again["restore"] == 0  # 다시 하면 할 일이 없다


def test_second_apply_keeps_the_first_before_values(world):
    bridge = fresh(world)
    run(world, "apply", bridge=bridge, style=STYLE)
    run(world, "apply", bridge=bridge, style={"pick": {"rating": 4}}, overwrite=True)
    run(world, "rollback", bridge=bridge, commit=True)
    assert bridge.variants["A.CR3"].rating == 0 and bridge.variants["A.CR3"].color_tag == 0


@pytest.mark.parametrize("style", [
    {"pick": {"rating": 0}}, {"pick": {"rating": 6}}, {"pick": {"color": 8}},
    {"pick": {"rating": True}}, {"nope": {"rating": 3}}, "text", {"pick": 3}])
def test_bad_style_is_rejected(world, style):
    status, out = run(world, "preview", style=style)
    assert status == 400 and "error" in out
