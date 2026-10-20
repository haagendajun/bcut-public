"""사진 표시(셀렉·보류·버릴 컷)를 이 컴퓨터에 저장한다 (spec FR-22, plan 2-2).

- 행사(폴더 이름) 단위로 `<root>/<행사 키>/marks.jsonl` 한 파일에 **덧붙이기만** 한다.
  수정·삭제는 없다. 검사(작업 번호)를 다시 해도 표시가 남는다
  (ADR-0004: 사진은 파일 이름 + 크기로 구분).
- 사진 한 장에는 취소되지 않은 표시가 하나만 있다. 새 표시를 달면 앞의 표시는
  "취소 줄"로 닫힌다 (ADR-0008).
- 한 줄이 깨져 있어도 나머지는 읽는다 (깨진 줄 수를 알려 준다).

줄 모양:
  표시  {"id": ..., "file": "PHA_7780.CR3", "size": 24633012, "kind": "pick", "at": "..."}
  취소  {"id": ..., "cancel": "<취소할 표시의 id>", "at": "..."}
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

KINDS = ("pick", "maybe", "discard")  # 셀렉 / 보류 / 버릴 컷


def event_key(folder: Path) -> str:
    """행사 이름(폴더 이름)을 폴더 이름으로 안전하게 바꾼 글자."""
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", folder.name).strip("._")
    return (safe or "event")[:80]


def note_event(root: Path, folder: Path) -> None:
    """행사의 원래 이름(폴더 이름)을 한 번 적어 둔다. 올릴 때 행사 이름으로 쓴다."""
    path = root / event_key(folder) / "event.json"
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": folder.name}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 이름을 못 적어도 표시 저장은 계속한다 (폴더 키로 대신 올린다)


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MarkStore:
    def __init__(self, root: Path, now: Callable[[], str] = _now) -> None:
        self.root = root
        self._now = now
        self._lock = threading.Lock()

    def _path(self, event: str) -> Path:
        return self.root / event / "marks.jsonl"

    def _read(self, event: str) -> tuple[dict[tuple[str, int], dict], int]:
        """지금 유효한 표시 {(파일, 크기): 표시 줄}과 읽지 못한 줄 수."""
        active: dict[tuple[str, int], dict] = {}
        by_id: dict[str, tuple[str, int]] = {}
        broken = 0
        path = self._path(event)
        if not path.exists():
            return active, broken
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if "cancel" in item:
                    key = by_id.get(item["cancel"])
                    if key is not None and active.get(key, {}).get("id") == item["cancel"]:
                        del active[key]
                    continue
                if item["kind"] not in KINDS:
                    raise ValueError("kind")
                key = (item["file"], int(item["size"]))
                by_id[item["id"]] = key
                active[key] = item
            except (ValueError, KeyError, TypeError):
                broken += 1
        return active, broken

    def active(self, event: str) -> tuple[list[dict], int]:
        with self._lock:
            active, broken = self._read(event)
        marks = [{"file": f, "size": s, "kind": m["kind"]} for (f, s), m in sorted(active.items())]
        return marks, broken

    def clear_all(self, event: str) -> int:
        """지금 있는 표시를 모두 해제한다 (취소 줄만 덧붙여 이력은 남는다). 해제한 장수를 준다."""
        with self._lock:
            active, _ = self._read(event)
            if not active:
                return 0
            at = self._now()
            lines = [{"id": uuid.uuid4().hex, "cancel": m["id"], "at": at} for m in active.values()]
            path = self._path(event)
            with path.open("a", encoding="utf-8") as f:
                f.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
                f.flush()
                os.fsync(f.fileno())
        return len(lines)

    def set(self, event: str, file: str, size: int, kind: str | None) -> str | None:
        """표시를 달거나(kind) 해제한다(None). 앞 표시는 취소 줄로 닫고, 지금 표시를 돌려준다."""
        if kind is not None and kind not in KINDS:
            raise ValueError(f"kind는 {', '.join(KINDS)} 중 하나여야 한다")
        with self._lock:
            active, _ = self._read(event)
            current = active.get((file, size))
            if (current["kind"] if current else None) == kind:
                return kind
            lines = []
            if current:
                lines.append({"id": uuid.uuid4().hex, "cancel": current["id"], "at": self._now()})
            if kind is not None:
                lines.append({"id": uuid.uuid4().hex, "file": file, "size": size, "kind": kind,
                              "at": self._now()})
            path = self._path(event)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:  # 두 줄을 한 번에 쓴다
                f.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
                f.flush()
                os.fsync(f.fileno())
        return kind


# ---- 서버가 부르는 짧은 함수 (server.py가 커지지 않게 여기에 둔다) ------------------------------

def list_marks(store: MarkStore, folder: Path, names: set[str]) -> dict:
    """이 행사에서 지금 유효한 표시 중, 이 검사에 있는 사진의 것만."""
    marks, broken = store.active(event_key(folder))
    mine = [m for m in marks if m["file"] in names and file_size(folder / m["file"]) == m["size"]]
    return {"marks": mine, "broken": broken}


def post_mark(store: MarkStore, folder: Path, names: set[str], body: dict) -> tuple[int, dict]:
    """(HTTP 상태 번호, 응답). 이 파일은 http 모듈을 쓰지 않아서(안전 규칙) 상태를 숫자로 준다."""
    file, kind = body.get("file"), body.get("kind")
    if not isinstance(file, str) or file not in names:  # 검사 결과의 파일 이름만 (경로 조작 방지)
        return 404, {"error": "없는 사진"}
    if kind is not None and kind not in KINDS:
        return 400, {"error": "kind는 pick, maybe, discard 또는 null이어야 한다"}
    size = file_size(folder / file)
    if size is None:
        return 404, {"error": "사진 파일을 찾을 수 없다"}
    try:
        note_event(store.root, folder)
        now_kind = store.set(event_key(folder), file, size, kind)
    except OSError as exc:
        return 500, {"error": f"표시를 저장하지 못했다: {type(exc).__name__}"}
    return 200, {"file": file, "size": size, "kind": now_kind}
