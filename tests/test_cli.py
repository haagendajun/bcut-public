import pytest

from bcut import __version__
from bcut.cli import USAGE_ERROR, build_parser, main, resolve_out_dir


def test_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("scan", "calibrate", "apply", "rollback"):
        assert command in out


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "scan" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_calibrate_with_too_few_labels_fails_and_writes_nothing(tmp_path, capsys):
    event = tmp_path / "event"
    event.mkdir()
    (event / "a.CR3").write_bytes(b"x")
    labels = tmp_path / "labels.csv"
    labels.write_text("file,label\na.CR3,OK\n", encoding="utf-8")
    out = tmp_path / "cfg.toml"
    code = main(["calibrate", "--folder", str(event), "--labels", str(labels), "--out", str(out),
                 "--workers", "1"])
    assert code == 2 and not out.exists()
    assert "보정할 수 없다" in capsys.readouterr().err


def test_calibrate_refuses_config_inside_event_folder(tmp_path, capsys):
    event = tmp_path / "event"
    event.mkdir()
    (event / "a.CR3").write_bytes(b"x")
    labels = tmp_path / "labels.csv"
    labels.write_text("file,label\n", encoding="utf-8")
    assert main(["calibrate", "--folder", str(event), "--labels", str(labels),
                 "--out", str(event / "cfg.toml")]) == 2
    assert list(event.iterdir()) == [event / "a.CR3"]


def test_scan_rejects_missing_folder(tmp_path):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["scan", "--folder", str(tmp_path / "nope")])
    assert exc.value.code == 2


def test_scan_without_photos_fails_and_writes_nothing(tmp_path, monkeypatch, capsys):
    event = tmp_path / "event"
    event.mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["scan", "--folder", str(event)]) == USAGE_ERROR
    assert "사진(CR3)이 없다" in capsys.readouterr().err
    assert not (tmp_path / "bcut-out").exists()
    assert list(event.iterdir()) == []


# ---- 결과 폴더: 행사 폴더 안에는 쓰지 않는다 (읽기 전용 약속) ----------------------


def test_default_out_dir_is_outside_the_event_folder(tmp_path, monkeypatch):
    event = tmp_path / "260223 EVENT_A"
    event.mkdir()
    monkeypatch.chdir(tmp_path / ".." / tmp_path.name)
    out = resolve_out_dir(event, None)
    assert out.parts[-2:] == ("bcut-out", "260223 EVENT_A")
    assert event.resolve() not in out.resolve().parents


def test_out_dir_inside_event_folder_is_rejected(tmp_path):
    event = tmp_path / "event"
    event.mkdir()
    with pytest.raises(ValueError, match="행사 폴더 안"):
        resolve_out_dir(event, event / "report")


def test_out_dir_equal_to_event_folder_is_rejected(tmp_path):
    event = tmp_path / "event"
    event.mkdir()
    with pytest.raises(ValueError):
        resolve_out_dir(event, event)


def test_out_dir_via_dotdot_inside_event_is_rejected(tmp_path):
    event = tmp_path / "event"
    (event / "sub").mkdir(parents=True)
    with pytest.raises(ValueError):
        resolve_out_dir(event, event / "sub" / ".." / "x")


def test_sibling_out_dir_is_accepted(tmp_path):
    event = tmp_path / "event"
    event.mkdir()
    assert resolve_out_dir(event, tmp_path / "out") == tmp_path / "out"


def test_scan_refuses_out_dir_inside_event_folder(tmp_path, capsys):
    event = tmp_path / "event"
    event.mkdir()
    (event / "a.CR3").write_bytes(b"x")
    code = main(["scan", "--folder", str(event), "--out", str(event / "out")])
    assert code == USAGE_ERROR
    assert "행사 폴더에 아무것도 쓰지 않는다" in capsys.readouterr().err
    assert sorted(p.name for p in event.iterdir()) == ["a.CR3"]


def test_scan_rejects_bad_config(tmp_path, capsys):
    folder = tmp_path / "ev"
    folder.mkdir()
    (folder / "a.CR3").write_bytes(b"x")
    cfg = tmp_path / "bad.toml"
    cfg.write_text("[eyes]\nnope = 1\n", encoding="utf-8")
    assert main(["scan", "--folder", str(folder), "--out", str(tmp_path / "o"),
                 "--config", str(cfg)]) == 2
    assert "설정 파일" in capsys.readouterr().err
