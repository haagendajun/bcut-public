"""`apply`·`rollback` 실행 기록 (`bcut-actions.jsonl`, devplan T3.6).

문제가 생겼을 때 "언제, 무엇을, 어느 카탈로그에, 어떻게 돌렸고 무슨 일이 있었나"를 볼 수 있게,
실행할 때마다 **한 줄씩 덧붙인다**(JSON 한 줄). 미리보기(dry-run)도 남긴다. 사진 내용은 담지 않고
파일 이름도 넣지 않는다(장수와 사유만). 결과 폴더(`--out`)에만 쓰고 행사 폴더에는 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

FILENAME = "bcut-actions.jsonl"


def append_action(out_dir: Path, record: dict) -> Path | None:
    """기록 한 줄을 덧붙인다. 기록을 못 써도 본 작업을 멈추지 않는다 (실패하면 None)."""
    path = out_dir / FILENAME
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        return None
    return path


def read_actions(out_dir: Path) -> list[dict]:
    path = out_dir / FILENAME
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"unreadable": line[:80]})
    return out
