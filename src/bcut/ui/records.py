"""기록 관리: 이 컴퓨터에 쌓인 기록을 보고, 표시를 해제하고, 휴지통으로 옮긴다 (spec FR-34~36).

- "지우기"는 파일을 지우지 않는다. 기록을 `<data-dir>/trash/`로 **옮기고** 복원할 수 있다
  (ADR-0012).
- 사진 파일, Capture One 안의 값, 클라우드 DB는 건드리지 않는다.
- 옮기고 복원하는 경로는 `<data-dir>` 안으로만 제한한다 (이름 검사 + 실제 경로 확인).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from bcut.bridge.capture_one import CaptureOneBridge
from bcut.bridge.osascript import AppleScriptError, explain_error
from bcut.ui.capture import undo
from bcut.ui.cloud_plan import make_plan, read_event
from bcut.ui.cloud_state import CloudState
from bcut.ui.marks import KINDS, MarkStore
from bcut.ui.reviews import ReviewStore

BACKUP_FILES = ("bcut-backup.json", "bcut-style-backup.json")  # Capture One 되돌리기용 기록
_NAME = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._ -]*")


class RecordError(ValueError):
    """요청한 기록을 찾을 수 없거나 안전하지 않은 이름이다."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _name(value) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or ".." in value:
        raise RecordError("올바르지 않은 이름")
    return value


def _inside(path: Path, root: Path) -> Path:
    real = path.resolve()
    if root.resolve() not in real.parents and real != root.resolve():
        raise RecordError("기록 폴더 밖은 다룰 수 없다")
    return real


def _event_name(folder: Path) -> str:
    try:
        name = json.loads((folder / "event.json").read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else folder.name


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _capture_records(data_dir: Path, key: str) -> list[dict]:
    base = data_dir / "capture-one" / key
    out = []
    for path in sorted(base.rglob("bcut-backup.json")) if base.is_dir() else []:
        d, style = _load(path), _load(path.parent / BACKUP_FILES[1])
        sub = "" if path.parent == base else str(path.parent.relative_to(base))
        out.append({"document": d.get("catalog", "?"), "created_at": d.get("created_at"),
                    "photos": len(d.get("entries", [])),
                    "style_photos": len(style.get("entries", {})), "path": sub})
    return out


def _review_summary(items: list[dict]) -> dict:
    seconds = 0.0
    for r in items:
        try:
            seconds += (datetime.fromisoformat(r["ended_at"])
                        - datetime.fromisoformat(r["started_at"])).total_seconds()
        except (KeyError, ValueError):
            continue
    last = max((r.get("ended_at", "") for r in items), default=None)
    return {"count": len(items), "seen": sum(r.get("photos_seen", 0) for r in items),
            "seconds": round(seconds), "last": last}


def list_records(data_dir: Path) -> dict:
    events_dir = data_dir / "events"
    state = CloudState(data_dir / "cloud.json")
    marks, reviews = MarkStore(events_dir), ReviewStore(events_dir)
    cards = []
    folders = sorted(p for p in events_dir.iterdir() if p.is_dir()) if events_dir.is_dir() else []
    for folder in folders:
        active, _ = marks.active(folder.name)
        counts = {k: sum(1 for m in active if m["kind"] == k) for k in KINDS}
        plan = make_plan(read_event(folder), state.data["marks"], set(state.data["reviews"]))
        cards.append({"key": folder.name, "name": _event_name(folder), "marks": counts,
                      "reviews": _review_summary(reviews.list(folder.name)),
                      "cloud_pending": plan.pending,
                      "capture": _capture_records(data_dir, folder.name)})
    return {"events": cards, "trash": list_trash(data_dir),
            "cloud": {"consented": bool(state.data["consented_at"]),
                      "last_sync_at": state.data["last_sync_at"]}}


def clear_marks(store: MarkStore, key: str) -> int:
    """행사의 지금 표시를 모두 해제한다 (이력은 남는다)."""
    return store.clear_all(_name(key))


# ---- 휴지통 ----------------------------------------------------------------------------------

def _trash_dir(data_dir: Path) -> Path:
    return data_dir / "trash"


def _move(items: list[tuple[Path, str]], data_dir: Path, label: str, now: Callable[[], str],
          info: dict | None = None) -> str:
    """(원래 경로, 휴지통 안 이름) 목록을 한 휴지통 항목으로 옮긴다."""
    if not items:
        raise RecordError("옮길 기록이 없다")
    stamp = now()
    entry = _trash_dir(data_dir) / f"{re.sub(r'[^0-9]', '', stamp)}__{label}"
    n = 1
    while entry.exists():
        entry = entry.with_name(f"{entry.name}_{n}")
        n += 1
    entry.mkdir(parents=True)
    meta = {"label": label, "trashed_at": stamp, "items": [], **(info or {})}
    for src, name in items:
        os.replace(src, entry / name)
        meta["items"].append({"name": name, "original": str(src.relative_to(data_dir.resolve()))})
    (entry / "trash.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return entry.name


def trash_event(data_dir: Path, key: str, now: Callable[[], str] = _now) -> str:
    folder = _inside(data_dir / "events" / _name(key), data_dir)
    if not folder.is_dir():
        raise RecordError("없는 행사 기록")
    info = {"kind": "event", "event": key, "event_name": _event_name(folder)}
    return _move([(folder, "event")], data_dir, f"행사_{key}", now, info)


def trash_capture(data_dir: Path, key: str, sub: str, now: Callable[[], str] = _now) -> str:
    """Capture One 반영 기록(되돌리기용)을 옮긴다. sub는 문서별 폴더 이름(예전 방식이면 빈 값)."""
    base = data_dir / "capture-one" / _name(key)
    folder = _inside(base / _name(sub) if sub else base, data_dir)
    files = [(folder / f, f) for f in BACKUP_FILES if (folder / f).is_file()]
    if not files:
        raise RecordError("없는 Capture One 반영 기록")
    ev = data_dir / "events" / key
    info = {"kind": "capture", "event": key, "doc": sub,
            "event_name": _event_name(ev) if ev.is_dir() else key,
            "document": _load(folder / BACKUP_FILES[0]).get("catalog")}
    return _move(files, data_dir, f"CaptureOne_{key}_{sub or '기본'}", now, info)


def _trash_view(entry_name: str, meta: dict) -> dict:
    """휴지통 항목을 화면용으로: 어느 행사의 무슨 기록인지 읽기 쉬운 이름."""
    label = str(meta.get("label") or "")
    kind = meta.get("kind") or ("capture" if label.startswith("CaptureOne_") else "event")
    key = meta.get("event") or label.split("_", 1)[-1]
    group = meta.get("event_name") or key
    if kind == "capture":
        title = "Capture One 반영 기록 · " + (meta.get("document") or "문서 이름 모름")
    else:
        title = "행사 기록 (표시·훑기)"
    return {"id": entry_name, "kind": kind, "event": key, "group": group, "title": title,
            "trashed_at": meta.get("trashed_at"), "items": len(meta.get("items", []))}


def list_trash(data_dir: Path) -> list[dict]:
    root = _trash_dir(data_dir)
    out = []
    for entry in sorted(root.iterdir(), reverse=True) if root.is_dir() else []:
        meta = _load(entry / "trash.json")
        if meta:
            out.append(_trash_view(entry.name, meta))
    names = {t["event"]: t["group"] for t in out
             if t["kind"] == "event" and t["group"] != t["event"]}
    for t in out:  # 같은 행사의 다른 항목에서 읽기 쉬운 행사 이름을 가져온다
        if t["group"] == t["event"] and t["event"] in names:
            t["group"] = names[t["event"]]
    return out


def restore(data_dir: Path, trash_id: str) -> int:
    """휴지통 항목을 원래 자리로 되돌려 놓는다. 원래 자리에 이미 있으면 아무것도 하지 않는다."""
    entry = _inside(_trash_dir(data_dir) / _name(trash_id), _trash_dir(data_dir))
    try:
        meta = json.loads((entry / "trash.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecordError("없는 휴지통 항목") from exc
    root = data_dir.resolve()
    plan = []
    for it in meta.get("items", []):
        dst = _inside(root / it["original"], root)
        if dst.exists():
            raise RecordError("원래 자리에 이미 기록이 있어서 되돌려 놓을 수 없다")
        plan.append((entry / _name(it["name"]), dst))
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    os.replace(entry / "trash.json", entry / "restored.json")  # 복원한 항목은 목록에서 빠진다
    return len(plan)


def capture_undo(data_dir: Path, body: dict, make_bridge) -> dict:
    """기록 관리 화면에서 Capture One 반영을 되돌린다 (미리보기가 기본, commit이면 실제)."""
    base = data_dir / "capture-one" / _name(body.get("event"))
    sub = body.get("doc") or ""
    folder = _inside(base / _name(sub) if sub else base, data_dir)
    catalog = _load(folder / BACKUP_FILES[0]).get("catalog")
    if not isinstance(catalog, str) or not catalog:
        raise RecordError("이 반영 기록에서 카탈로그·세션 이름을 읽을 수 없다")
    return undo(make_bridge(catalog), folder, commit=body.get("commit") is True)


def handle(store: MarkStore, data_dir: Path, method: str, path: str, body: dict | None,
           make_bridge=CaptureOneBridge) -> tuple[int, dict]:
    """서버가 부르는 짧은 함수. (HTTP 상태 번호, 응답). http를 쓰지 않아서 숫자로 준다."""
    body = body or {}
    try:
        if method == "GET" and path == "/api/records":
            return 200, list_records(data_dir)
        if method != "POST":
            return 405, {"error": "허용되지 않은 메서드"}
        if path == "/api/records/clear-marks":
            return 200, {"cleared": clear_marks(store, body.get("event"))}
        if path == "/api/records/trash":
            if body.get("kind") == "event":
                return 200, {"id": trash_event(data_dir, body.get("event"))}
            if body.get("kind") == "capture":
                doc = body.get("doc") or ""
                return 200, {"id": trash_capture(data_dir, body.get("event"), doc)}
            return 400, {"error": "kind는 event 또는 capture여야 한다"}
        if path == "/api/records/capture-rollback":
            return 200, capture_undo(data_dir, body, make_bridge)
        if path == "/api/records/restore":
            return 200, {"restored": restore(data_dir, body.get("id"))}
    except RecordError as exc:
        return 400, {"error": str(exc)}
    except AppleScriptError as exc:
        return 502, {"error": explain_error(exc)}
    except OSError as exc:
        return 500, {"error": f"기록을 옮기지 못했다: {type(exc).__name__}"}
    return 404, {"error": "없는 주소"}
