"""분석 리포트(CSV, PRD FR-04)를 쓴다. 엑셀에서 한글이 깨지지 않도록 BOM이 있는 UTF-8로 저장한다.

`reason` 열에는 이 사진을 사람 눈앞에 올린 사유가 들어간다
(eyes_closed, exposure, blur, out_of_focus).
두 사유가 함께 걸리면 `eyes_closed;exposure`처럼 세미콜론으로 잇는다.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from bcut.scan import PhotoResult

COLUMNS = [
    "file", "status", "reason", "confidence", "score", "note",
    "exposure", "exposure_p99", "exposure_face_hi", "exposure_global_hi",
    "sharpness", "sharp_best", "sharp_face",
    "face_count", "faces_considered", "eye_width_frac", "error",
    "tool_version", "config_version",
]


def reason_for(r: PhotoResult) -> str:
    """사유 목록을 세미콜론으로 이은 글자. 사유가 없으면 빈 글자."""
    return ";".join(r.reasons)


def _num(value: float | None, digits: int) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def write_csv(
    results: Sequence[PhotoResult], path: Path, *, tool_version: str = "", config_version: str = ""
) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for r in results:
            writer.writerow([
                r.file, r.status, reason_for(r), _num(r.confidence, 3), _num(r.score, 4),
                r.note or "",
                r.exposure_kind or "", _num(r.exposure_p99, 1), _num(r.exposure_face_hi, 4),
                _num(r.exposure_global_hi, 4),
                r.sharpness_kind or "", _num(r.sharpness_best, 3), _num(r.sharpness_face, 3),
                r.face_count, r.faces_considered, _num(r.eye_width_frac, 5), r.error or "",
                tool_version, config_version,
            ])
