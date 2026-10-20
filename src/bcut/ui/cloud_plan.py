"""로컬 기록에서 "무엇을 올릴지" 정하는 순수 규칙 (네트워크 없음, spec FR-30·33).

- 로컬 줄 번호(id)를 그대로 DB 번호로 쓰므로 같은 줄은 두 번 올라가지 않는다.
- 올릴 때는 표시를 **취소된 최종 상태로** 넣고, 이미 올라간 표시의 취소는 먼저 반영한다.
  (사진 한 장에 활성 표시는 하나라는 DB 규칙과 충돌하지 않게)
- 사진 파일·경로는 다루지 않는다. 이름·크기·표시·시각만 나간다.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REVIEW_NAMESPACE = uuid.UUID("6f1c2f0e-8f55-4d7e-9d36-7b1f0f4c9a11")


@dataclass
class MarkRow:
    id: str
    file: str
    size: int
    kind: str
    at: str
    cancelled_at: str | None = None


@dataclass
class EventData:
    key: str
    name: str
    marks: list[MarkRow] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)


@dataclass
class Plan:
    cancels: list[MarkRow]
    inserts: list[MarkRow]
    reviews: list[dict]

    @property
    def pending(self) -> int:
        """아직 올라가지 않은 표시·기록 수 (취소만 남은 것도 한 건)."""
        ids = {m.id for m in self.inserts}
        return len(self.inserts) + sum(1 for m in self.cancels if m.id not in ids) + len(
            self.reviews)


def db_uuid(raw: str) -> str:
    """DB 번호(uuid). 이미 uuid 모양이면 그대로, 아니면 같은 글자에서 항상 같은 번호."""
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return str(uuid.uuid5(REVIEW_NAMESPACE, raw))


def _lines(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            yield item


def read_event(folder: Path) -> EventData:
    """`events/<키>/` 한 행사의 표시·훑기 기록을 읽는다. 깨진 줄은 건너뛴다."""
    try:
        name = json.loads((folder / "event.json").read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        name = None
    ev = EventData(key=folder.name, name=name if isinstance(name, str) and name else folder.name)
    by_id: dict[str, MarkRow] = {}
    for item in _lines(folder / "marks.jsonl"):
        try:
            if "cancel" in item:
                target = by_id.get(item["cancel"])
                if target is not None and target.cancelled_at is None:
                    target.cancelled_at = str(item["at"])
            else:
                row = MarkRow(str(item["id"]), str(item["file"]), int(item["size"]),
                              str(item["kind"]), str(item["at"]))
                by_id[row.id] = row
                ev.marks.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    ev.reviews = [r for r in _lines(folder / "reviews.jsonl") if "id" in r]
    return ev


def make_plan(ev: EventData, uploaded_marks: dict, uploaded_reviews: set) -> Plan:
    inserts = [m for m in ev.marks if m.id not in uploaded_marks]
    cancels = [m for m in ev.marks if m.cancelled_at and uploaded_marks.get(m.id) != "c"]
    reviews = [r for r in ev.reviews if r["id"] not in uploaded_reviews]
    return Plan(cancels=cancels, inserts=inserts, reviews=reviews)


def review_row(r: dict, event_id: str) -> dict:
    return {"id": db_uuid(r["id"]), "event_id": event_id, "started_at": r["started_at"],
            "ended_at": r["ended_at"], "photos_seen": r["photos_seen"],
            "pick_count": r["pick_count"], "maybe_count": r["maybe_count"],
            "discard_count": r["discard_count"], "tool_version": r.get("tool_version", "")}
