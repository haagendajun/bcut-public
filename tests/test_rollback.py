from dataclasses import replace
from pathlib import Path

import pytest

from bcut.apply import read_plan, run_apply
from bcut.bridge.backup import FILENAME, load_backup, save_backup
from bcut.bridge.capture_one import VariantInfo
from bcut.cli import main
from bcut.rollback import plan_rollback, run_rollback, tool_keywords

ALL_KW = ["bcut-candidate", "bcut-review", "bcut-eyes_closed", "bcut-exposure"]


def vi(folder, name, rating=0, tag=0, kws=()):
    return VariantInfo(path=str(folder / name), name=name, rating=rating, color_tag=tag,
                       keywords=tuple(kws), collection_id="1", variant_id=name)


class FakeBridge:
    catalog_name = "bcut-test"

    def __init__(self, variants, catalog_keywords=ALL_KW):
        self.variants = {v.variant_id: v for v in variants}
        self.catalog_keywords = list(catalog_keywords)
        self.stripped = []

    def list_variants(self):
        return list(self.variants.values())

    def keywords(self):
        return list(self.catalog_keywords)

    def backup_catalog(self, location):
        pass

    def apply_keyword(self, keyword, refs):
        for _, vid in refs:
            v = self.variants[vid]
            if keyword not in v.keywords:
                self.variants[vid] = replace(v, keywords=(*v.keywords, keyword))
        return len(refs)

    def strip_keyword(self, keyword, refs):
        n = 0
        for _, vid in refs:
            v = self.variants[vid]
            if keyword in v.keywords:
                self.variants[vid] = replace(
                    v, keywords=tuple(k for k in v.keywords if k != keyword))
                n += 1
        self.stripped.append((keyword, [v for _, v in refs]))
        return n

    def user_edit(self, name, **changes):
        self.variants[name] = replace(self.variants[name], **changes)


@pytest.fixture
def applied(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    rows = [("A.CR3", "candidate", "eyes_closed"), ("B.CR3", "review", "exposure"),
            ("C.CR3", "normal", "")]
    (out / "bcut-report.csv").write_text(
        "file,status,reason\n" + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
    b = FakeBridge([
        vi(ev, "A.CR3", 3, 1, ["mine", "bcut-review"]),  # 원래부터 도구 키워드 이름을 가진 컷
        vi(ev, "B.CR3"), vi(ev, "C.CR3", 5)])
    plan = read_plan(out / "bcut-report.csv")
    res = run_apply(b, plan, ev, out, commit=True)
    assert res.ok
    return ev, out, b


def test_tool_keywords_exclude_those_present_before(applied):
    _, out, _ = applied
    e = load_backup(out / FILENAME).entry("A.CR3")
    assert e.add_keywords == ["bcut-candidate", "bcut-eyes_closed"]
    assert tool_keywords(e) == ["bcut-candidate", "bcut-eyes_closed"]


def test_rollback_restores_state_before_apply(applied):
    ev, out, b = applied
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and res.stripped_files == 2
    a = b.variants["A.CR3"]
    assert a.keywords == ("mine", "bcut-review") and (a.rating, a.color_tag) == (3, 1)
    assert b.variants["B.CR3"].keywords == () and b.variants["C.CR3"].rating == 5
    assert (out / FILENAME).exists()  # 백업은 남는다


def test_dry_run_changes_nothing(applied):
    _, out, b = applied
    before = dict(b.variants)
    res = run_rollback(b, out / FILENAME)
    assert res.mode == "dry-run" and res.strip and b.variants == before and b.stripped == []
    assert res.keyword_counts == {"bcut-candidate": 1, "bcut-eyes_closed": 1, "bcut-exposure": 1,
                                  "bcut-review": 1}


def test_user_changed_values_after_apply_are_preserved_and_reported(applied):
    ev, out, b = applied
    b.user_edit("A.CR3", rating=5)                      # 반영 후 사용자가 별점을 바꿈
    b.user_edit("B.CR3", color_tag=2)                   # 컬러 태그를 바꿈
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and sorted(res.user_changed) == ["A.CR3", "B.CR3"]
    assert b.variants["A.CR3"].rating == 5 and b.variants["B.CR3"].color_tag == 2  # 보존
    assert "bcut-candidate" not in b.variants["A.CR3"].keywords  # 도구 키워드는 떼어짐


def test_user_added_keywords_are_kept(applied):
    _, out, b = applied
    v = b.variants["B.CR3"]
    b.user_edit("B.CR3", keywords=(*v.keywords, "내가붙인"))
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and res.user_keywords == {"B.CR3": ["내가붙인"]}
    assert b.variants["B.CR3"].keywords == ("내가붙인",)


def test_keyword_user_already_removed_is_not_an_error(applied):
    _, out, b = applied
    b.user_edit("A.CR3", keywords=("mine", "bcut-review"))  # 사용자가 도구 키워드를 이미 뗌
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and res.already_clean == 1 and "A.CR3" not in res.strip


def test_rollback_twice_is_harmless(applied):
    _, out, b = applied
    run_rollback(b, out / FILENAME, commit=True)
    state = dict(b.variants)
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and res.stripped_files == 0 and b.variants == state


def test_cut_missing_from_catalog_is_skipped_and_reported(applied):
    _, out, b = applied
    del b.variants["B.CR3"]
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and res.missing == ["B.CR3"]


def test_missing_or_corrupt_backup_aborts(applied, tmp_path):
    _, out, b = applied
    res = run_rollback(b, tmp_path / "nope.json", commit=True)
    assert res.aborted and "백업" in res.aborted and b.stripped == []
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert run_rollback(b, bad, commit=True).aborted


def test_backup_from_other_catalog_is_refused(applied):
    _, out, b = applied
    bk = load_backup(out / FILENAME)
    bk.catalog = "다른카탈로그"
    save_backup(bk, out / FILENAME)
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.aborted and "다른카탈로그" in res.aborted and b.stripped == []


def test_plan_matches_by_unique_name_when_path_changed(applied, tmp_path):
    _, out, b = applied
    moved = {k: replace(v, path=str(tmp_path / "moved" / v.name)) for k, v in b.variants.items()}
    res = plan_rollback(load_backup(out / FILENAME), list(moved.values()))
    assert res.missing == [] and set(res.strip) == {"A.CR3", "B.CR3"}


# ---- CLI -------------------------------------------------------------------------------

def test_cli_rollback_dry_run_and_commit(applied, monkeypatch, capsys):
    ev, out, b = applied
    import bcut.bridge.capture_one as co
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: b)
    base = ["rollback", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out)]
    assert main(base) == 0
    text = capsys.readouterr().out
    assert "dry-run" in text and "--commit" in text and b.stripped == []
    assert main([*base, "--commit"]) == 0
    assert "키워드를 뗀 컷 2장" in capsys.readouterr().out
    assert b.variants["B.CR3"].keywords == ()


def test_cli_rollback_without_backup_fails_without_touching_catalog(
        tmp_path, monkeypatch, capsys):
    ev = tmp_path / "ev"
    ev.mkdir()
    import bcut.bridge.capture_one as co
    fake = FakeBridge([vi(ev, "A.CR3", kws=["bcut-review"])])
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    code = main(["rollback", "--folder", str(ev), "--catalog", "bcut-test", "--out",
                 str(tmp_path / "o"), "--commit"])
    assert code == 1 and "중단" in capsys.readouterr().err
    assert fake.stripped == [] and fake.variants["A.CR3"].keywords == ("bcut-review",)


def test_cli_rollback_rejects_out_inside_event_folder(tmp_path, capsys):
    ev = tmp_path / "ev"
    ev.mkdir()
    assert main(["rollback", "--folder", str(ev), "--catalog", "x", "--out", str(ev / "o")]) == 2
    assert Path(ev).exists()
