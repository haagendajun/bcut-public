"""실행 로그(`bcut-log.json`, PRD FR-11): 소요 시간, 장수, 등급·사유별 개수, 처리 못 한 파일.

단축률을 계산하는 데 쓴다. 사진 파일 이름과 설정 값만 담고 사진 내용은 담지 않는다.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from bcut.config import Config
from bcut.scan import PhotoResult, count_by_reason, count_by_status


def build_log(
    results: Sequence[PhotoResult], *, folder_name: str, started: datetime, finished: datetime,
    seconds: float, config: Config, version: str,
) -> dict:
    n = len(results)
    errors = [r for r in results if r.error]
    unscorable = Counter(r.note or "unknown" for r in results if r.status == "unscorable")
    return {
        "version": version,
        "folder": folder_name,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "photos": n,
        "seconds": round(seconds, 2),
        "seconds_per_photo": round(seconds / n, 4) if n else None,
        "by_status": count_by_status(results),
        "by_reason": count_by_reason(results),
        "unscorable_reasons": dict(unscorable),
        "failed_files": [{"file": r.file, "error": r.error} for r in errors],
        "config_version": config.config_version,
        "reason_tiers": dict(config.reason_tiers),
        "thresholds": {
            "eyes": asdict(config.eyes),
            "exposure": asdict(config.exposure),
            "sharpness": asdict(config.sharpness),
        },
    }


def write_log(log: dict, path: Path) -> None:
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
