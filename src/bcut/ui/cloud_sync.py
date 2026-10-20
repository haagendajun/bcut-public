"""행사 한 곳의 기록을 DB에 올리는 순서 (spec FR-30, 33). 통신은 받은 `client`가 한다.

순서: 행사 → 사진(표시한 것만) → 이미 올라간 표시의 취소 → 새 표시(시간순) → 훑기 기록.
모두 "추가"와 "취소 시각 채우기"뿐이고, 삭제 요청은 없다 (ADR-0005).
"""

from __future__ import annotations

from bcut.ui.cloud_plan import EventData, Plan, db_uuid, make_plan, review_row
from bcut.ui.cloud_state import CloudState

BATCH = 200
IGNORE = "resolution=ignore-duplicates,return=minimal"


def _chunks(items: list, n: int = BATCH):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _event_id(client, access: str, name: str) -> str:
    client.rest("POST", "events", access=access, params={"on_conflict": "owner_id,name"},
                body=[{"name": name}], prefer=IGNORE)
    rows = client.rest("GET", "events", access=access, params={"name": f"eq.{name}",
                                                                "select": "id"})
    if not rows:
        raise RuntimeError("행사 번호를 받지 못했다")
    return rows[0]["id"]


def _photo_ids(client, access: str, event_id: str, plan: Plan) -> dict[tuple[str, int], str]:
    files = sorted({(m.file, m.size) for m in plan.inserts})
    for part in _chunks(files):
        client.rest("POST", "photos", access=access,
                    params={"on_conflict": "event_id,file_name,file_size"}, prefer=IGNORE,
                    body=[{"event_id": event_id, "file_name": f, "file_size": s} for f, s in part])
    found: dict[tuple[str, int], str] = {}
    offset = 0
    while files:
        rows = client.rest("GET", "photos", access=access, params={
            "event_id": f"eq.{event_id}", "select": "id,file_name,file_size",
            "order": "id", "limit": 1000, "offset": offset})
        found.update({(r["file_name"], int(r["file_size"])): r["id"] for r in rows})
        if len(rows) < 1000:
            break
        offset += 1000
    return found


def _mark_body(m, photo_id: str) -> dict:
    return {"id": db_uuid(m.id), "photo_id": photo_id, "kind": m.kind, "marked_at": m.at,
            "cancelled_at": m.cancelled_at}


def upload_event(client, access: str, ev: EventData, state: CloudState) -> int:
    """올린 건수를 돌려준다. 올릴 것이 없으면 요청을 보내지 않는다."""
    plan = make_plan(ev, state.data["marks"], set(state.data["reviews"]))
    if plan.pending == 0:
        return 0
    event_id = _event_id(client, access, ev.name)
    photos = _photo_ids(client, access, event_id, plan)
    for m in plan.cancels:  # 앞서 올린 표시의 취소를 먼저 (활성 표시는 사진당 하나)
        client.rest("PATCH", "photo_marks", access=access, params={"id": f"eq.{db_uuid(m.id)}"},
                    body={"cancelled_at": m.cancelled_at})
        state.data["marks"][m.id] = "c"
    state.save()
    for part in _chunks(plan.inserts):
        body = []
        for m in part:
            if (m.file, m.size) not in photos:
                raise RuntimeError("사진 번호를 받지 못했다")
            body.append(_mark_body(m, photos[(m.file, m.size)]))
        client.rest("POST", "photo_marks", access=access, params={"on_conflict": "id"},
                    prefer=IGNORE, body=body)
        for m in part:
            state.data["marks"][m.id] = "c" if m.cancelled_at else "a"
        state.save()
    for part in _chunks(plan.reviews):
        client.rest("POST", "review_sessions", access=access, params={"on_conflict": "id"},
                    prefer=IGNORE, body=[review_row(r, event_id) for r in part])
        state.data["reviews"].extend(r["id"] for r in part)
        state.save()
    return plan.pending
