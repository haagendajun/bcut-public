"""Capture One에도 표시하기 (spec FR-28, ADR-0010).

셀렉·보류·버릴 컷 표시를 **전용 키워드**로 바꿔 기존 `run_apply`(백업·검증·재실행 안전)와
`run_rollback`에 넘긴다. 이 파일은 "무엇을 붙일지"(계획)와 결과를 쉬운 JSON으로 바꾸는 일만 한다.
별점·컬러 태그는 만지지 않는다. 미리보기(`preview`)는 카탈로그에 아무것도 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from bcut import __version__
from bcut.apply import ApplyResult, run_apply
from bcut.bridge.backup import FILENAME
from bcut.bridge.capture_one import CaptureOneBridge
from bcut.bridge.osascript import AppleScriptError, explain_error
from bcut.rollback import RollbackResult, run_rollback
from bcut.ui.marks import MarkStore, event_key, list_marks

# 한글 이름이 Capture One에서 안 통하면 여기만 영문으로 바꾼다 (ADR-0010)
KEYWORDS = {"pick": "bcut-셀렉", "maybe": "bcut-보류", "discard": "bcut-버릴컷"}
ACTIONS = ("preview", "apply", "rollback")
SHOW = 20  # 화면에 이름을 보여 줄 최대 장수


def build_plan(marks: list[dict]) -> dict[str, list[str]]:
    """표시 목록 [{file, kind}] -> {파일 이름: [붙일 키워드]}."""
    return {m["file"]: [KEYWORDS[m["kind"]]] for m in marks if m["kind"] in KEYWORDS}


def _apply_payload(res: ApplyResult, action: str) -> dict:
    m = res.match
    return {
        "action": action, "mode": res.mode, "aborted": res.aborted, "planned": res.planned,
        "matched": len(m.matched) if m else 0,
        "missing": (m.missing[:SHOW] if m else []), "missing_total": len(m.missing) if m else 0,
        "ambiguous": list(m.ambiguous)[:SHOW] if m else [],
        "ambiguous_total": len(m.ambiguous) if m else 0,
        "missing_keywords": res.missing_keywords, "keyword_counts": res.keyword_counts,
        "already": res.already, "applied_files": res.applied_files,
        "violations": res.violations[:SHOW], "ok": res.ok,
        "backup": str(res.backup_path) if res.backup_path else None,
    }


def _rollback_payload(res: RollbackResult, action: str) -> dict:
    return {
        "action": action, "mode": res.mode, "aborted": res.aborted, "entries": res.entries,
        "strip_files": len(res.strip), "keyword_counts": res.keyword_counts,
        "already_clean": res.already_clean, "missing_total": len(res.missing),
        "user_changed": len(res.user_changed), "stripped_files": res.stripped_files,
        "violations": res.violations[:SHOW], "ok": res.ok,
    }


def handle(store: MarkStore, folder: Path, names: set[str], data_dir: Path, body: dict,
           make_bridge: Callable[[str], CaptureOneBridge] = CaptureOneBridge,
           now: Callable[[], str] | None = None) -> tuple[int, dict]:
    """(HTTP 상태 번호, 응답). 이 파일은 http를 쓰지 않아서(안전 규칙) 상태를 숫자로 준다."""
    action, catalog = body.get("action"), body.get("catalog")
    if action not in ACTIONS:
        return 400, {"error": "action은 preview, apply, rollback 중 하나여야 한다"}
    if not isinstance(catalog, str) or not catalog.strip():
        return 400, {"error": "카탈로그 이름을 입력해야 한다"}
    out_dir = data_dir / "capture-one" / event_key(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    bridge = make_bridge(catalog.strip())
    try:
        if action == "rollback":
            res = run_rollback(bridge, out_dir / FILENAME, commit=body.get("commit") is True)
            return 200, _rollback_payload(res, action)
        plan = build_plan(list_marks(store, folder, names)["marks"])
        res = run_apply(
            bridge, plan, folder, out_dir, commit=action == "apply",
            allow_partial=body.get("allow_partial") is True, tool_version=__version__,
            backups_dir=out_dir / "catalog-backups",
            now=now or (lambda: datetime.now().isoformat(timespec="seconds")))
        if not plan:
            res.aborted = "표시한 사진이 없어요. 먼저 훑기에서 셀렉·보류·버릴 컷을 표시해 주세요"
        return 200, _apply_payload(res, action)
    except AppleScriptError as exc:
        return 502, {"error": explain_error(exc)}
    except (ValueError, OSError) as exc:
        return 500, {"error": f"Capture One 표시 중 문제가 생겼다: {type(exc).__name__}"}
