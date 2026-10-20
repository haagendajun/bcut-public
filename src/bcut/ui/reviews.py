"""훑기 기록: 훑기 한 번의 시간·본 사진 수·표시 수를 이 컴퓨터에 남긴다 (spec FR-26, plan 2-2).

- `<root>/<행사 키>/reviews.jsonl`에 훑기가 끝날 때 한 줄씩 **덧붙이기만** 한다
  (수정·삭제 없음, ADR-0005).
- 줄의 이름은 ERD의 `review_sessions` 열과 같다. 나중에 슈파베이스로 올릴 때 그대로 쓴다.
- 번호(id)는 화면이 훑기를 시작할 때 만든다. 같은 번호를 다시 보내도 한 줄만 남는다.
- 표시 수는 훑기를 마칠 때의 표시 합계다 (이전에 달아 둔 표시 포함).
- 장당 훑는 시간 = (끝 − 시작) ÷ 본 사진 수. 기준값(손으로 하던 시간)은 없어서
  행사끼리 비교하는 용도다.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from bcut.ui.marks import event_key, note_event

_ID = re.compile(r"[0-9A-Za-z_-]{8,64}")
_COUNTS = (("seen", "photos_seen"), ("pick", "pick_count"), ("maybe", "maybe_count"),
           ("discard", "discard_count"))
MAX_COUNT = 1_000_000


class ReviewStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _path(self, event: str) -> Path:
        return self.root / event / "reviews.jsonl"

    def list(self, event: str) -> list[dict]:
        path = self._path(event)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue  # 깨진 줄은 건너뛴다
            if isinstance(item, dict) and "id" in item:
                out.append(item)
        return out

    def add(self, event: str, entry: dict) -> bool:
        """한 줄을 덧붙인다. 같은 번호가 이미 있으면 아무것도 하지 않고 False."""
        with self._lock:
            if any(x["id"] == entry["id"] for x in self.list(event)):
                return False
            path = self._path(event)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return True


def _count(value) -> int | None:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT
    return value if ok else None


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()  # 시간대가 없으면 이 컴퓨터 시간대로 본다


def post_review(store: ReviewStore, folder: Path, scan_ref: str, body: dict,
                tool_version: str) -> tuple[int, dict]:
    """(HTTP 상태 번호, 응답). 이 파일은 http를 쓰지 않아서(안전 규칙) 상태를 숫자로 준다."""
    rid = body.get("id")
    if not isinstance(rid, str) or not _ID.fullmatch(rid):
        return 400, {"error": "id가 올바르지 않다"}
    started, ended = _time(body.get("started_at")), _time(body.get("ended_at"))
    if started is None or ended is None or ended < started:
        return 400, {"error": "시작·끝 시각이 올바르지 않다"}
    counts = {col: _count(body.get(key)) for key, col in _COUNTS}
    if any(v is None for v in counts.values()):
        return 400, {"error": "장수는 0 이상의 정수여야 한다"}
    entry = {"id": rid, "scan_ref": scan_ref, "started_at": started.isoformat(timespec="seconds"),
             "ended_at": ended.isoformat(timespec="seconds"), **counts,
             "tool_version": tool_version}
    try:
        note_event(store.root, folder)
        added = store.add(event_key(folder), entry)
    except OSError as exc:
        return 500, {"error": f"훑기 기록을 저장하지 못했다: {type(exc).__name__}"}
    seconds = (ended - started).total_seconds()
    seen = counts["photos_seen"]
    return 200, {"id": rid, "saved": added, "seconds": round(seconds, 1),
                 "seconds_per_photo": round(seconds / seen, 2) if seen else None}
