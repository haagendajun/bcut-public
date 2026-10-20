import json
from datetime import datetime

from bcut.config import Config
from bcut.report.run_log import build_log, write_log
from bcut.scan import PhotoResult


def r(name, status, **kw):
    return PhotoResult(name, status, 0.3, kw.pop("note", None), 1, 1, 0.01, None, **kw)


def test_log_contents_and_json_roundtrip(tmp_path):
    results = [
        r("a", "candidate", eyes_status="candidate"),
        r("b", "normal"),
        r("c", "unscorable", note="small_eye"),
        r("d", "review", note="read_error", error="OSError: x"),
    ]
    t = datetime(2026, 10, 19, 20, 0, 0)
    log = build_log(results, folder_name="행사", started=t, finished=t, seconds=2.0,
                    config=Config(), version="0.1")
    assert log["photos"] == 4 and log["seconds_per_photo"] == 0.5
    assert log["by_status"]["candidate"] == 1 and log["by_status"]["unscorable"] == 1
    assert log["unscorable_reasons"] == {"small_eye": 1}
    assert log["failed_files"] == [{"file": "d", "error": "OSError: x"}]
    assert log["reason_tiers"]["eyes_closed"] == "candidate"
    assert log["thresholds"]["sharpness"]["min_face_px"] == 420
    path = tmp_path / "bcut-log.json"
    write_log(log, path)
    assert json.loads(path.read_text(encoding="utf-8")) == log


def test_log_empty_run():
    t = datetime(2026, 10, 19)
    log = build_log([], folder_name="x", started=t, finished=t, seconds=0.0,
                    config=Config(), version="0.1")
    assert log["photos"] == 0 and log["seconds_per_photo"] is None
