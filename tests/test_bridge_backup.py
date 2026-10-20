import json
from pathlib import Path

import pytest

from bcut.bridge import backup as bk
from bcut.bridge.backup import BackupError, load_backup, new_backup, record_after, save_backup
from bcut.bridge.capture_one import CaptureOneBridge, VariantInfo
from bcut.bridge.matching import match_cuts


def v(path, rating=0, tag=0, kws=()):
    return VariantInfo(path=path, name=Path(path).name, rating=rating, color_tag=tag,
                       keywords=tuple(kws))


# ---- T2.2 매칭 -----------------------------------------------------------------------

def test_match_by_exact_path_prefers_event_folder_when_names_repeat(tmp_path):
    ev = tmp_path / "ev"
    other = tmp_path / "other"
    ev.mkdir()
    other.mkdir()
    a, b = v(str(ev / "A.CR3")), v(str(other / "A.CR3"))
    r = match_cuts(["A.CR3"], [b, a], ev)
    assert r.matched["A.CR3"] is a and r.clean and r.by_name == []


def test_same_name_in_two_places_without_folder_is_ambiguous_and_not_applied():
    vs = [v("/x/A.CR3"), v("/y/A.CR3"), v("/x/B.CR3")]
    r = match_cuts(["A.CR3", "B.CR3"], vs)
    assert "A.CR3" not in r.matched and r.ambiguous == {"A.CR3": ["/x/A.CR3", "/y/A.CR3"]}
    assert r.matched["B.CR3"].path == "/x/B.CR3" and r.by_name == ["B.CR3"]
    assert not r.clean


def test_missing_extra_and_folder_mismatch(tmp_path):
    vs = [v("/cat/A.CR3"), v("/cat/Z.CR3")]
    r = match_cuts(["A.CR3", "Q.CR3"], vs, tmp_path / "somewhere-else")
    # 경로가 달라서 이름으로 짝지었다
    assert r.matched["A.CR3"].path == "/cat/A.CR3" and r.by_name == ["A.CR3"]
    assert r.missing == ["Q.CR3"] and r.extra == ["Z.CR3"] and not r.clean


def test_symlink_and_relative_paths_are_normalized(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    r = match_cuts(["A.CR3"], [v(str(real / "A.CR3"))], link)
    assert r.matched and r.by_name == []  # 링크 경로로 물어도 같은 파일로 인식


# ---- T2.3 백업 -----------------------------------------------------------------------

def make(tmp_path):
    vs = {"A.CR3": v("/e/A.CR3", 2, 1, ["old"]), "B.CR3": v("/e/B.CR3")}
    plan = {"A.CR3": ["bcut-eyes_closed"], "B.CR3": ["bcut-exposure", "bcut-review"]}
    b = new_backup("bcut-test", plan, vs, created_at="2026-10-19T21:00:00",
                   tool_version="0.1.0", config_version="default-0")
    return b, vs


def test_backup_records_before_values_and_plan(tmp_path):
    b, _ = make(tmp_path)
    a = b.entry("A.CR3")
    assert (a.before.rating, a.before.color_tag, a.before.keywords) == (2, 1, ["old"])
    assert a.add_keywords == ["bcut-eyes_closed"] and a.after is None
    assert b.entry("nope") is None


def test_record_after_fills_after_and_reports_unread(tmp_path):
    b, _ = make(tmp_path)
    cur = {"A.CR3": v("/e/A.CR3", 2, 1, ["old", "bcut-eyes_closed"])}
    assert record_after(b, cur) == ["B.CR3"]
    assert b.entry("A.CR3").after.keywords == ["old", "bcut-eyes_closed"]
    assert b.entry("B.CR3").after is None


def test_save_load_roundtrip_and_no_tmp_left(tmp_path):
    b, _ = make(tmp_path)
    record_after(b, {"A.CR3": v("/e/A.CR3", 4, 1, ["old", "bcut-eyes_closed"])})  # 사용자가 4점으로
    path = tmp_path / "out" / bk.FILENAME
    save_backup(b, path)
    assert load_backup(path) == b
    assert [p.name for p in path.parent.iterdir()] == [bk.FILENAME]  # 임시 파일이 남지 않는다
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 1


def test_save_failure_raises_backup_error_and_keeps_old_file(tmp_path, monkeypatch):
    b, _ = make(tmp_path)
    path = tmp_path / bk.FILENAME
    save_backup(b, path)
    old = path.read_text(encoding="utf-8")
    b.entries[0].before.rating = 5

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(bk.os, "replace", boom)
    with pytest.raises(BackupError, match="disk full"):
        save_backup(b, path)
    assert path.read_text(encoding="utf-8") == old  # 기존 백업은 그대로


def test_save_into_unwritable_location_fails(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    b, _ = make(tmp_path)
    with pytest.raises(BackupError):
        save_backup(b, blocker / "sub" / bk.FILENAME)


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"schema": 99}'])
def test_load_rejects_bad_files(tmp_path, text):
    p = tmp_path / bk.FILENAME
    p.write_text(text, encoding="utf-8")
    with pytest.raises(BackupError):
        load_backup(p)


def test_load_missing_file(tmp_path):
    with pytest.raises(BackupError, match="없다"):
        load_backup(tmp_path / "nope.json")


# ---- 카탈로그 백업 명령 --------------------------------------------------------------

def test_catalog_backup_sends_catalog_and_location(tmp_path):
    calls = []
    b = CaptureOneBridge("bcut-test", run=lambda s, a, **k: calls.append((s, list(a))) or "ok")
    b.backup_catalog(tmp_path / "bk")
    assert (tmp_path / "bk").is_dir()
    script, args = calls[0]
    assert args == ["bcut-test", str(tmp_path / "bk")] and "backup now" in script
    assert "wrong catalog" in script
