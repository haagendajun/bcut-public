"""`bcut rollback`: `apply`가 붙인 전용 키워드를 떼서 반영 이전 상태로 되돌린다 (devplan T2.7, Q5).

**기본은 dry-run이다.** `commit=True`일 때만 카탈로그를 바꾸고, 바꾸는 것은 **도구가 붙인 키워드를
떼는 것뿐**이다.

- 도구가 붙인 키워드 = 백업의 `add_keywords` 중 **반영 직전에 없던 것**. 반영 직전에 이미 있던
  키워드(사용자가 원래 붙여 둔 것)는 `apply`가 붙인 것이 아니므로 떼지 않는다.
- **사용자가 반영 후에 바꾼 값은 건드리지 않는다.** 별점·컬러 태그는 `apply`도 `rollback`도 바꾸지
  않으므로, 반영 직후 값과 지금 값이 다르면 "사용자가 바꾼 값"으로 알리기만 한다. 사용자가 반영 후에
  붙인 다른 키워드도 그대로 둔다.
- 사진이 카탈로그에 없으면 건너뛰고 알린다. 이미 키워드가 없는 컷은 그대로 둔다
  (다시 실행해도 같다).
- 백업 파일은 지우지 않는다.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bcut.bridge.backup import Backup, BackupError, Entry, load_backup
from bcut.bridge.capture_one import CaptureOneBridge, VariantInfo


@dataclass
class RollbackResult:
    mode: str
    entries: int = 0
    strip: dict[str, list[str]] = field(default_factory=dict)  # 파일명 -> 뗄 키워드
    already_clean: int = 0  # 뗄 키워드가 이미 없는 컷
    missing: list[str] = field(default_factory=list)  # 카탈로그에서 못 찾은 컷
    user_changed: list[str] = field(default_factory=list)  # 반영 후 사용자가 별점·태그를 바꾼 컷
    user_keywords: dict[str, list[str]] = field(default_factory=dict)  # 사용자가 붙인 키워드(보존)
    keyword_counts: dict[str, int] = field(default_factory=dict)
    aborted: str | None = None
    violations: list[str] = field(default_factory=list)
    stripped_files: int = 0

    @property
    def ok(self) -> bool:
        return self.aborted is None and not self.violations


def find_variant(entry: Entry, by_path: dict[str, VariantInfo],
                 by_name: dict[str, list[VariantInfo]]) -> VariantInfo | None:
    """백업의 경로로 찾고, 없으면 파일명이 카탈로그에서 하나뿐일 때만 그것."""
    hit = by_path.get(os.path.realpath(entry.path))
    if hit is not None:
        return hit
    cands = by_name.get(os.path.basename(entry.path), [])
    return cands[0] if len(cands) == 1 else None


def tool_keywords(entry: Entry) -> list[str]:
    """이 컷에서 `apply`가 붙인 키워드 (반영 직전에는 없던 것)."""
    return [k for k in entry.add_keywords if k not in entry.before.keywords]


def plan_rollback(backup: Backup, variants: Sequence[VariantInfo]) -> RollbackResult:
    res = RollbackResult(mode="dry-run", entries=len(backup.entries))
    by_path = {os.path.realpath(v.path): v for v in variants}
    by_name: dict[str, list[VariantInfo]] = defaultdict(list)
    for v in variants:
        by_name[os.path.basename(v.path)].append(v)
    counts: dict[str, int] = defaultdict(int)
    for e in backup.entries:
        v = find_variant(e, by_path, by_name)
        if v is None:
            res.missing.append(e.file)
            continue
        if e.after is not None and (v.rating, v.color_tag) != (e.after.rating, e.after.color_tag):
            res.user_changed.append(e.file)
        mine = set(tool_keywords(e))
        known = {*e.before.keywords, *e.add_keywords, *(e.after.keywords if e.after else [])}
        extra = [k for k in v.keywords if k not in known]
        if extra:
            res.user_keywords[e.file] = extra
        present = [k for k in tool_keywords(e) if k in v.keywords]
        if present:
            res.strip[e.file] = present
            for k in present:
                counts[k] += 1
        elif mine:
            res.already_clean += 1
    res.keyword_counts = dict(sorted(counts.items()))
    return res


def run_rollback(bridge: CaptureOneBridge, backup_path: Path, *, commit: bool = False
                 ) -> RollbackResult:
    try:
        backup = load_backup(backup_path)
    except BackupError as exc:
        return RollbackResult(mode="commit" if commit else "dry-run",
                              aborted=f"백업을 읽을 수 없어 아무것도 바꾸지 않았다: {exc}")
    if backup.catalog != bridge.catalog_name:
        return RollbackResult(
            mode="commit" if commit else "dry-run", entries=len(backup.entries),
            aborted=f"이 백업은 카탈로그 '{backup.catalog}'의 것이다 (지금 지정: "
                    f"'{bridge.catalog_name}'). 아무것도 바꾸지 않았다")
    variants = bridge.list_variants()
    res = plan_rollback(backup, variants)
    res.mode = "commit" if commit else "dry-run"
    if not commit:
        return res

    by_path = {os.path.realpath(v.path): v for v in variants}
    by_name: dict[str, list[VariantInfo]] = defaultdict(list)
    for v in variants:
        by_name[os.path.basename(v.path)].append(v)
    refs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in backup.entries:
        v = find_variant(e, by_path, by_name)
        for k in res.strip.get(e.file, []) if v else []:
            refs[k].append((v.collection_id, v.variant_id))
    for k in sorted(refs):
        bridge.strip_keyword(k, refs[k])

    after = {os.path.realpath(v.path): v for v in bridge.list_variants()}
    res.stripped_files = len(res.strip)
    res.violations = verify_rollback(backup, after, res)
    return res


def verify_rollback(backup: Backup, after: dict[str, VariantInfo], res: RollbackResult
                    ) -> list[str]:
    """되돌린 뒤 검증: 도구 키워드가 사라졌고, 원래 키워드와 사용자 키워드가 남았는가."""
    bad = []
    for e in backup.entries:
        v = after.get(os.path.realpath(e.path))
        if v is None or e.file in res.missing:
            continue
        left = [k for k in tool_keywords(e) if k in v.keywords]
        if left:
            bad.append(f"{e.file}: 도구 키워드가 남아 있다 {left}")
        lost = [k for k in e.before.keywords if k not in v.keywords]
        if lost:
            bad.append(f"{e.file}: 원래 키워드가 사라졌다 {lost}")
        lost_user = [k for k in res.user_keywords.get(e.file, []) if k not in v.keywords]
        if lost_user:
            bad.append(f"{e.file}: 사용자가 붙인 키워드가 사라졌다 {lost_user}")
    return bad
