"""반영 전 백업 (`bcut-backup.json`, devplan T2.3, PRD FR-06·FR-08, Q5 확정).

컷마다 **반영 직전** 값(별점, 컬러 태그, 키워드 전체)과 도구가 붙일 키워드, 그리고 반영 후에 채우는
**반영 직후** 값을 저장한다. `rollback`은 현재 값이 직후 값과 같은 사진만 되돌리고, 다르면
(사용자가 그 사이에 바꾼 것) 건드리지 않고 알린다.

저장은 임시 파일에 쓰고 읽어서 확인한 다음 자리를 바꾸는 방식이다. 저장에 실패하면
`BackupError`를 올리고, 호출한 쪽(`apply`)은 **아무것도 반영하지 않고 중단**해야 한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bcut.bridge.capture_one import VariantInfo

SCHEMA = 1
FILENAME = "bcut-backup.json"


class BackupError(RuntimeError):
    """백업을 저장하거나 읽을 수 없다."""


@dataclass
class State:
    rating: int
    color_tag: int
    keywords: list[str]

    @classmethod
    def of(cls, v: VariantInfo) -> State:
        return cls(rating=v.rating, color_tag=v.color_tag, keywords=list(v.keywords))


@dataclass
class Entry:
    file: str
    path: str
    before: State
    add_keywords: list[str]  # 도구가 붙일 전용 키워드
    after: State | None = None  # 반영 직후 값. 반영하기 전에는 None


@dataclass
class Backup:
    catalog: str
    created_at: str
    tool_version: str
    config_version: str
    entries: list[Entry] = field(default_factory=list)
    schema: int = SCHEMA

    def entry(self, file: str) -> Entry | None:
        return next((e for e in self.entries if e.file == file), None)


def new_backup(
    catalog: str, plan: dict[str, list[str]], variants: dict[str, VariantInfo], *,
    created_at: str, tool_version: str, config_version: str,
) -> Backup:
    """`plan`(파일명 -> 붙일 키워드)과 짝지은 변형의 **현재 값**으로 백업을 만든다."""
    entries = [
        Entry(file=f, path=variants[f].path, before=State.of(variants[f]), add_keywords=list(kws))
        for f, kws in plan.items()
    ]
    return Backup(catalog=catalog, created_at=created_at, tool_version=tool_version,
                  config_version=config_version, entries=entries)


def merge_backup(old: Backup, new: Backup) -> Backup:
    """같은 행사에 `apply`를 다시 실행할 때: **처음의 직전 값은 지키고** 새 컷만 더한다.

    이미 백업에 있는 컷은 `before`를 그대로 두고(두 번째 실행의 "직전"에는 도구 키워드가 이미
    붙어 있어서, 그걸로 덮어쓰면 롤백이 도구 키워드를 되돌리지 못한다) 붙일 키워드만 합친다.
    """
    if old.catalog != new.catalog:
        raise BackupError(f"기존 백업은 다른 카탈로그({old.catalog})의 것이다")
    for e in new.entries:
        prev = old.entry(e.file)
        if prev is None:
            old.entries.append(e)
        else:
            prev.add_keywords = sorted({*prev.add_keywords, *e.add_keywords})
    return old


def record_after(backup: Backup, current: dict[str, VariantInfo]) -> list[str]:
    """반영 직후 값을 채운다. 카탈로그에서 읽지 못한 컷의 파일명 목록을 돌려준다."""
    unread = []
    for e in backup.entries:
        v = current.get(e.file)
        if v is None:
            unread.append(e.file)
        else:
            e.after = State.of(v)
    return unread


def to_dict(backup: Backup) -> dict:
    return asdict(backup)


def from_dict(data: dict) -> Backup:
    try:
        if data["schema"] != SCHEMA:
            raise BackupError(f"백업 형식 버전이 다르다: {data['schema']} (이 도구는 {SCHEMA})")

        def state(d: dict | None) -> State | None:
            return None if d is None else State(d["rating"], d["color_tag"], list(d["keywords"]))

        entries = [
            Entry(file=e["file"], path=e["path"], before=state(e["before"]),  # type: ignore[arg-type]
                  add_keywords=list(e["add_keywords"]), after=state(e.get("after")))
            for e in data["entries"]
        ]
        return Backup(catalog=data["catalog"], created_at=data["created_at"],
                      tool_version=data["tool_version"], config_version=data["config_version"],
                      entries=entries, schema=data["schema"])
    except (KeyError, TypeError) as exc:
        raise BackupError(f"백업 파일의 형식이 올바르지 않다: {exc!r}") from exc


def save_backup(backup: Backup, path: Path) -> None:
    """임시 파일에 쓰고, 다시 읽어 같은지 확인한 뒤 자리를 바꾼다. 실패하면 BackupError."""
    text = json.dumps(to_dict(backup), ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        if json.loads(tmp.read_text(encoding="utf-8")) != to_dict(backup):
            raise BackupError("저장한 백업을 다시 읽었더니 내용이 다르다")
        os.replace(tmp, path)
    except OSError as exc:
        raise BackupError(f"백업을 저장할 수 없다: {exc}") from exc


def load_backup(path: Path) -> Backup:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupError(f"백업 파일이 없다: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"백업 파일을 읽을 수 없다: {exc}") from exc
    return from_dict(data)
