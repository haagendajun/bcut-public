"""파일 계약(docs/file-contracts.md)을 고정한다. 이 테스트를 바꾸면 문서도 바꾼다."""

import csv
from datetime import datetime

from bcut.config import REASONS, Config
from bcut.report.csv_report import COLUMNS, write_csv
from bcut.report.run_log import build_log
from bcut.scan import ALL_REASONS, ALL_STATUSES, PhotoResult

CSV_COLUMNS = [
    "file", "status", "reason", "confidence", "score", "note",
    "exposure", "exposure_p99", "exposure_face_hi", "exposure_global_hi",
    "sharpness", "sharp_best", "sharp_face",
    "face_count", "faces_considered", "eye_width_frac", "error",
    "tool_version", "config_version",
]
LOG_KEYS = {
    "version", "folder", "started_at", "finished_at", "photos", "seconds", "seconds_per_photo",
    "by_status", "by_reason", "unscorable_reasons", "failed_files", "config_version",
    "reason_tiers", "thresholds",
}


def test_csv_columns_are_frozen():
    assert COLUMNS == CSV_COLUMNS


def test_csv_row_has_versions_and_reason_vocabulary(tmp_path):
    r = PhotoResult("a.CR3", "review", 0.3, None, 1, 1, 0.01, None, eyes_status="normal",
                    sharpness_kind="blur", sharpness_best=0.7, confidence=0.35)
    path = tmp_path / "r.csv"
    write_csv([r], path, tool_version="9.9", config_version="cfg-1")
    row = next(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert list(row) == CSV_COLUMNS
    assert row["tool_version"] == "9.9" and row["config_version"] == "cfg-1"
    assert row["reason"] == "blur" and row["status"] in ALL_STATUSES


def test_reason_vocabulary_matches_config():
    assert set(ALL_REASONS) == set(REASONS)


def test_log_keys_are_frozen():
    t = datetime(2026, 10, 19)
    log = build_log([], folder_name="x", started=t, finished=t, seconds=0.0,
                    config=Config(), version="0")
    assert set(log) == LOG_KEYS
    assert set(log["thresholds"]) == {"eyes", "exposure", "sharpness"}
