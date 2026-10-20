import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from bcut import organize
from bcut.cli import main
from bcut.organize import (
    SortError,
    plan_sort,
    read_rescue,
    read_rows,
    result_dir_name,
    run_sort,
    unique_dir,
)

NOW = datetime(2026, 10, 20, 15, 30)


def snapshot(folder: Path):
    return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns,
                   p.read_bytes() if p.is_file() else b"") for p in folder.rglob("*"))


@pytest.fixture
def world(tmp_path):
    ev = tmp_path / "행사"
    ev.mkdir()
    rows = [
        ("A.CR3", "candidate", "eyes_closed"),
        ("B.CR3", "review", "exposure;eyes_closed"),
        ("C.CR3", "normal", ""),
        ("D.CR3", "no_face", ""),
        ("E.CR3", "unscorable", ""),
        ("F.CR3", "review", "blur"),
        ("GONE.CR3", "normal", ""),  # 리포트에만 있음
    ]
    for name, *_ in rows:
        if name != "GONE.CR3":
            (ev / name).write_bytes(name.encode() * 100)
    (ev / "NEW.CR3").write_bytes(b"new")  # 폴더에만 있음 (분석 뒤에 추가됨)
    (ev / ".hidden.CR3").write_bytes(b"h")
    out = tmp_path / "out"
    out.mkdir()
    report = out / "bcut-report.csv"
    report.write_text("file,status,reason\n" + "\n".join(",".join(r) for r in rows) + "\n",
                      encoding="utf-8")
    return ev, out, report


def test_read_rows_and_bad_report(world, tmp_path):
    _, _, report = world
    rows = read_rows(report)
    assert rows[1].reasons == ("exposure", "eyes_closed") and rows[0].status == "candidate"
    bad = tmp_path / "bad.csv"
    bad.write_text("name,tag\na,b\n", encoding="utf-8")
    with pytest.raises(SortError):
        read_rows(bad)
    with pytest.raises(SortError, match="scan"):
        read_rows(tmp_path / "nope.csv")
    weird = tmp_path / "w.csv"
    weird.write_text("file,status,reason\nx.CR3,whatever,\n", encoding="utf-8")
    with pytest.raises(SortError, match="알 수 없는 등급"):
        read_rows(weird)


def test_plan_folders_and_reasons(world):
    ev, _, report = world
    p = plan_sort(read_rows(report), ev)
    assert p.folders["버릴 것 같은 컷"] == ["A.CR3"]
    assert p.folders["직접 확인"] == ["B.CR3", "F.CR3"]
    assert p.folders["이상 없음"] == ["C.CR3", "D.CR3"]  # no_face도 정상
    assert p.folders["판단 못 함"] == ["E.CR3"]
    assert p.folders["문제 종류별/눈 감김"] == ["A.CR3", "B.CR3"]  # 한 컷이 사유마다 들어간다
    assert p.folders["문제 종류별/너무 밝거나 어두움"] == ["B.CR3"] and p.folders["문제 종류별/흔들려 찍힘"] == ["F.CR3"]
    assert p.files == 6 and p.placements == 10
    assert p.missing == ["GONE.CR3"] and p.unlisted == ["NEW.CR3"]  # 숨김 파일은 안 센다
    assert p.bytes_total > 0


def test_no_by_reason(world):
    ev, _, report = world
    p = plan_sort(read_rows(report), ev, by_reason=False)
    assert not any(k.startswith("문제 종류별") for k in p.folders) and p.placements == 6


def test_rescued_cuts_go_to_normal_only(world, tmp_path):
    ev, _, report = world
    r = tmp_path / "saved.txt"
    r.write_text("A.CR3\nB.CR3\nC.CR3\nZZZ.CR3\n\n", encoding="utf-8")
    p = plan_sort(read_rows(report), ev, rescue=read_rescue(r))
    assert p.rescued == ["A.CR3", "B.CR3"]
    assert sorted(p.folders["이상 없음"]) == ["A.CR3", "B.CR3", "C.CR3", "D.CR3"]
    assert "버릴 것 같은 컷" not in p.folders and p.folders["직접 확인"] == ["F.CR3"]
    assert "문제 종류별/눈 감김" not in p.folders  # 살린 컷은 사유별에서도 빠진다 (눈 감김은 둘 다 살림)
    assert "문제 종류별/너무 밝거나 어두움" not in p.folders and p.folders["문제 종류별/흔들려 찍힘"] == ["F.CR3"]
    assert p.unknown_rescue == ["C.CR3", "ZZZ.CR3"]  # 후보·확인이 아닌 것은 무시
    assert read_rescue(None) == set()


def test_dry_run_writes_nothing(world):
    ev, out, report = world
    before = (snapshot(ev), snapshot(out))
    res = run_sort(ev, report, out, now=lambda: NOW)
    assert res.mode == "dry-run" and res.ok and res.result_dir is None
    assert (snapshot(ev), snapshot(out)) == before


def test_commit_creates_new_folder_with_identical_copies_and_original_untouched(world):
    ev, out, report = world
    ev_before = snapshot(ev)
    res = run_sort(ev, report, out, commit=True, now=lambda: NOW)
    assert res.ok and res.result_dir == out / "행사_정리_2026-10-20_1530"
    d = res.result_dir
    assert (d / "버릴 것 같은 컷" / "A.CR3").read_bytes() == (ev / "A.CR3").read_bytes()
    assert (d / "문제 종류별" / "눈 감김" / "B.CR3").exists() and (d / "판단 못 함" / "E.CR3").exists()
    assert res.cloned + res.copied == res.plan.placements
    assert snapshot(ev) == ev_before  # 원본 폴더는 그대로 (이름, 크기, 시각, 내용)
    rec = json.loads((d / organize.RECORD_NAME).read_text(encoding="utf-8"))
    assert rec["photos"] == 6 and rec["counts"]["버릴 것 같은 컷"] == 1
    assert sorted(rec["files"]["B.CR3"]) == sorted(["직접 확인", "문제 종류별/너무 밝거나 어두움", "문제 종류별/눈 감김"])
    assert rec["missing"] == ["GONE.CR3"] and rec["unlisted"] == ["NEW.CR3"]


def test_every_run_makes_a_new_folder_and_never_overwrites(world):
    ev, out, report = world
    a = run_sort(ev, report, out, commit=True, now=lambda: NOW).result_dir
    mark = a / "버릴 것 같은 컷" / "A.CR3"
    mark_stat = mark.stat().st_mtime_ns
    b = run_sort(ev, report, out, commit=True, now=lambda: NOW).result_dir  # 같은 분에 다시
    assert a != b and b.name.endswith("-2") and mark.stat().st_mtime_ns == mark_stat
    assert unique_dir(out, "x") == out / "x"
    assert result_dir_name(Path("/e/행사"), NOW) == "행사_정리_2026-10-20_1530"


def test_copy_fallback_when_clone_fails(world, monkeypatch):
    ev, out, report = world
    monkeypatch.setattr(organize, "_clonefile", lambda s, d: False)
    res = run_sort(ev, report, out, commit=True, now=lambda: NOW)
    assert res.ok and res.cloned == 0 and res.copied == res.plan.placements
    assert res.method == "copy"
    assert (res.result_dir / "버릴 것 같은 컷" / "A.CR3").read_bytes() == (ev / "A.CR3").read_bytes()


def test_other_volume_checks_free_space_first(world, monkeypatch):
    ev, out, report = world
    monkeypatch.setattr(organize, "same_volume", lambda a, b: False)
    res = run_sort(ev, report, out, commit=True, free_space=lambda p: 10, now=lambda: NOW)
    assert res.aborted and "여유 공간이 부족" in res.aborted and res.result_dir is None
    assert res.needs_space > 0 and not list(out.glob("*_정리_*"))
    ok = run_sort(ev, report, out, free_space=lambda p: 10**12, now=lambda: NOW)
    assert ok.aborted is None and ok.method == "copy" and ok.needs_space > 0


def test_mismatched_copy_is_reported(world, monkeypatch):
    ev, out, report = world

    def bad_copy(src, dst):
        Path(dst).write_bytes(b"x")  # 크기가 다른 복제본
        return "copy"

    monkeypatch.setattr(organize, "clone_or_copy", bad_copy)
    res = run_sort(ev, report, out, commit=True, now=lambda: NOW)
    assert not res.ok and res.mismatches


def test_interrupted_run_keeps_what_exists_and_explains(world, monkeypatch):
    ev, out, report = world
    calls = {"n": 0}
    real = organize.clone_or_copy

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(organize, "clone_or_copy", flaky)
    res = run_sort(ev, report, out, commit=True, now=lambda: NOW)
    assert res.aborted and "disk full" in res.aborted and "Finder" in res.aborted
    assert res.result_dir.exists() and (res.result_dir / organize.RECORD_NAME).exists()


def test_clonefile_really_clones_on_same_volume(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(os.urandom(4096))
    b = tmp_path / "b.bin"
    assert organize.clone_or_copy(a, b) in ("clone", "copy") and b.read_bytes() == a.read_bytes()


# ---- CLI ---------------------------------------------------------------------------------

def test_cli_sort_preview_then_commit(world, capsys):
    ev, out, report = world
    base = ["sort", "--folder", str(ev), "--report", str(report), "--out", str(out)]
    assert main(base) == 0
    text = capsys.readouterr()
    assert "미리보기" in text.out and "버릴 것 같은 컷: 1장" in text.out and "--commit" in text.out
    assert "행사 폴더에 없는 사진 1장" in text.err and "리포트에 없는 사진 1장" in text.err
    assert not list(out.glob("*_정리_*"))
    assert main([*base, "--commit"]) == 0
    text = capsys.readouterr().out
    assert "결과 폴더:" in text and len(list(out.glob("행사_정리_*"))) == 1


def test_cli_sort_with_rescue_file(world, tmp_path, capsys):
    ev, out, report = world
    saved = tmp_path / "bcut-saved.txt"
    saved.write_text("A.CR3\n", encoding="utf-8")
    assert main(["sort", "--folder", str(ev), "--report", str(report), "--out", str(out),
                 "--rescue", str(saved), "--no-by-reason"]) == 0
    text = capsys.readouterr().out
    assert "남기기로 한 컷 1장" in text and "문제 종류별" not in text and "버릴 것 같은 컷:" not in text


def test_cli_sort_rejects_out_inside_event_and_missing_report(world, capsys):
    ev, out, report = world
    assert main(["sort", "--folder", str(ev), "--out", str(ev / "o"), "--report", str(report)]) == 2
    assert "행사 폴더 안" in capsys.readouterr().err
    assert main(["sort", "--folder", str(ev), "--out", str(out),
                 "--report", str(out / "nope.csv")]) == 2
    assert "scan" in capsys.readouterr().err


def test_cli_sort_logs_each_run(world):
    from bcut.report.action_log import read_actions
    ev, out, report = world
    main(["sort", "--folder", str(ev), "--report", str(report), "--out", str(out)])
    main(["sort", "--folder", str(ev), "--report", str(report), "--out", str(out), "--commit"])
    rows = [r for r in read_actions(out) if r["command"] == "sort"]
    assert [r["mode"] for r in rows] == ["dry-run", "commit"] and rows[1]["photos"] == 6
    assert "A.CR3" not in json.dumps(rows, ensure_ascii=False)  # 파일 이름은 기록하지 않는다
