"""`bcut apply`: 리포트의 후보·확인 컷에 전용 키워드를 붙인다 (devplan T2.4, T2.4a).

**기본은 dry-run이다.** `commit=True`일 때만 카탈로그를 바꾸고, 바꾸는 것은 **키워드 추가뿐**이다
(별점, 컬러 태그, 기존 키워드는 읽고 저장만 한다).

순서:
1. 리포트에서 후보(`candidate`)·확인(`review`) 컷을 뽑는다. 컷마다 붙일 키워드는 등급 키워드
   (`bcut-candidate` / `bcut-review`)와 사유 키워드(`bcut-eyes_closed` 등)다.
2. 카탈로그의 변형과 짝짓는다 (T2.2). 못 찾거나 모호한 컷이 있으면 `allow_partial`이 아닌 한
   중단한다.
3. **필요한 전용 키워드가 카탈로그에 있는지 확인한다 (T2.4a).** 키워드는 스크립트로 만들 수 없어서,
   없으면 **아무것도 바꾸지 않고** 만드는 방법을 안내하며 멈춘다.
4. dry-run이면 여기서 끝: 무엇이 붙을지 요약만 낸다. 파일도 카탈로그도 쓰지 않는다.
5. commit이면 카탈로그 백업 → `bcut-backup.json`(직전 값) 저장 → 키워드 부여 → 직후 값 저장 → 검증.
   백업을 저장하지 못하면 아무것도 반영하지 않는다.
이미 붙어 있는 키워드는 다시 붙이지 않는다 (같은 명령을 두 번 실행해도 결과가 같다).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bcut.bridge.backup import (
    FILENAME,
    BackupError,
    load_backup,
    merge_backup,
    new_backup,
    record_after,
    save_backup,
)
from bcut.bridge.capture_one import CaptureOneBridge, VariantInfo
from bcut.bridge.matching import MatchResult, match_cuts
from bcut.bridge.osascript import AppleScriptError, explain_error

APPLY_STATUSES = ("candidate", "review")
DEFAULT_CHUNK = 200  # 한 번의 스크립트 호출에서 키워드를 붙이는 컷 수 (오래 걸리는 호출을 피한다)
SETUP_GUIDE = "docs/capture-one-setup.md"


class ApplyError(RuntimeError):
    """리포트를 읽을 수 없는 등, 반영을 시작할 수 없다."""


def keyword_name(prefix: str, label: str) -> str:
    return f"{prefix}{label}"


@dataclass(frozen=True)
class ReportStats:
    """리포트 전체의 개수. 비정상 비율을 알아채는 데 쓴다."""

    total: int
    by_status: dict[str, int]
    by_reason: dict[str, int]  # 후보·확인 컷에서 사유별 장수

    @property
    def candidate_ratio(self) -> float:
        return self.by_status.get("candidate", 0) / self.total if self.total else 0.0

    @property
    def raised_ratio(self) -> float:
        raised = sum(self.by_status.get(s, 0) for s in APPLY_STATUSES)
        return raised / self.total if self.total else 0.0


@dataclass(frozen=True)
class RatioLimits:
    """이 비율을 넘으면 임계값·입력이 이상하다고 보고 반영을 멈춘다 (CUJ-01 E2).

    기본값은 실제 두 행사(행사 A 후보 8%·후보+확인 15%, 행사 B 0%·8%)보다 한참 위다.
    """

    max_candidate_ratio: float = 0.20
    max_raised_ratio: float = 0.40

    def __post_init__(self) -> None:
        for v in (self.max_candidate_ratio, self.max_raised_ratio):
            if not 0 < v <= 1:
                raise ValueError("비율 한도는 0보다 크고 1 이하여야 한다")


def ratio_warnings(stats: ReportStats, limits: RatioLimits) -> list[str]:
    tail = "를 넘는다. 임계값이나 입력이 잘못됐을 수 있다"
    out = []
    if stats.candidate_ratio > limits.max_candidate_ratio:
        out.append(f"후보 비율 {stats.candidate_ratio:.0%}가 한도 "
                   f"{limits.max_candidate_ratio:.0%}{tail}")
    if stats.raised_ratio > limits.max_raised_ratio:
        out.append(f"후보+확인 비율 {stats.raised_ratio:.0%}가 한도 "
                   f"{limits.max_raised_ratio:.0%}{tail}")
    return out


def read_report(
    report_csv: Path, prefix: str = "bcut-"
) -> tuple[dict[str, list[str]], ReportStats]:
    """리포트에서 (파일명 -> 붙일 키워드 목록, 전체 통계). 계획에는 후보·확인 컷만 들어간다."""
    try:
        with report_csv.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not {"file", "status"} <= set(reader.fieldnames):
                raise ApplyError("리포트 CSV에 file, status 열이 있어야 한다")
            rows = list(reader)
    except OSError as exc:
        raise ApplyError(f"리포트를 읽을 수 없다: {exc}") from exc
    plan: dict[str, list[str]] = {}
    by_status: dict[str, int] = defaultdict(int)
    by_reason: dict[str, int] = defaultdict(int)
    for row in rows:
        status = (row["status"] or "").strip()
        by_status[status] += 1
        if status not in APPLY_STATUSES:
            continue
        reasons = [r for r in (row.get("reason") or "").split(";") if r]
        for r in reasons:
            by_reason[r] += 1
        plan[row["file"]] = [keyword_name(prefix, status),
                             *[keyword_name(prefix, r) for r in reasons]]
    stats = ReportStats(total=len(rows), by_status=dict(by_status), by_reason=dict(by_reason))
    return plan, stats


def read_plan(report_csv: Path, prefix: str = "bcut-") -> dict[str, list[str]]:
    """리포트에서 파일명 -> 붙일 키워드 목록. 후보·확인 컷만."""
    return read_report(report_csv, prefix)[0]


def needed_keywords(plan: dict[str, list[str]]) -> list[str]:
    return sorted({k for kws in plan.values() for k in kws})


@dataclass
class ApplyResult:
    mode: str  # "dry-run" | "commit"
    planned: int  # 후보·확인 컷 수
    match: MatchResult | None = None
    missing_keywords: list[str] = field(default_factory=list)
    keyword_counts: dict[str, int] = field(default_factory=dict)  # 새로 붙을(붙인) 키워드별 장수
    already: int = 0  # 이미 모든 키워드가 붙어 있어 건너뛴 컷
    aborted: str | None = None  # 중단 이유 (없으면 정상)
    backup_path: Path | None = None
    violations: list[str] = field(default_factory=list)  # 반영 후 검증에서 어긋난 항목
    applied_files: int = 0
    warnings: list[str] = field(default_factory=list)  # 비정상 비율 등. commit이면 중단 사유

    @property
    def ok(self) -> bool:
        return self.aborted is None and not self.violations


def keywords_to_add(plan: dict[str, list[str]], matched: dict[str, VariantInfo]
                    ) -> dict[str, list[str]]:
    """컷마다, 이미 붙어 있지 않은 키워드만."""
    out = {}
    for f, kws in plan.items():
        v = matched.get(f)
        if v is None:
            continue
        add = [k for k in kws if k not in v.keywords]
        if add:
            out[f] = add
    return out


def run_apply(
    bridge: CaptureOneBridge, plan: dict[str, list[str]], event_folder: Path, out_dir: Path, *,
    commit: bool = False, allow_partial: bool = False, tool_version: str = "",
    config_version: str = "", backups_dir: Path | None = None,
    now: Callable[[], str] = lambda: "",
    stats: ReportStats | None = None, limits: RatioLimits | None = None,
    ignore_ratio_warning: bool = False, chunk_size: int = DEFAULT_CHUNK,
    progress: Callable[[str, int, int], None] | None = None,
) -> ApplyResult:
    res = ApplyResult(mode="commit" if commit else "dry-run", planned=len(plan))
    if stats is not None:
        res.warnings = ratio_warnings(stats, limits or RatioLimits())
    if not plan:
        res.aborted = "후보·확인 컷이 없다. 반영할 것이 없다"
        return res

    variants = bridge.list_variants()
    res.match = match_cuts(plan, variants, event_folder)
    if not res.match.clean and not allow_partial:
        res.aborted = (f"카탈로그에서 못 찾은 컷 {len(res.match.missing)}장, "
                       f"파일명이 겹쳐 모호한 컷 {len(res.match.ambiguous)}장이 있다. "
                       "아무것도 바꾸지 않았다 (--allow-partial로 찾은 컷만 반영할 수 있다)")
        return res
    matched = res.match.matched
    usable = {f: kws for f, kws in plan.items() if f in matched}

    have = set(bridge.keywords())
    res.missing_keywords = [k for k in needed_keywords(usable) if k not in have]
    if res.missing_keywords:
        res.aborted = (f"카탈로그에 전용 키워드가 없다: {', '.join(res.missing_keywords)}. "
                       f"키워드는 스크립트로 만들 수 없다. {SETUP_GUIDE}를 보고 한 번 만든 뒤 "
                       "다시 실행한다. 아무것도 바꾸지 않았다")
        return res

    to_add = keywords_to_add(usable, matched)
    res.already = len(usable) - len(to_add)
    counts: dict[str, int] = defaultdict(int)
    for kws in to_add.values():
        for k in kws:
            counts[k] += 1
    res.keyword_counts = dict(sorted(counts.items()))
    if not commit:
        return res
    if res.warnings and not ignore_ratio_warning:
        res.aborted = ("비정상 비율 경고로 아무것도 바꾸지 않았다: " + "; ".join(res.warnings)
                       + ". 확인했다면 --ignore-ratio-warning으로 반영할 수 있다")
        return res

    # ---- commit: 백업이 먼저. 저장하지 못하면 아무것도 바꾸지 않는다 ----
    backup_path = out_dir / FILENAME
    try:
        if backups_dir is not None:
            bridge.backup_catalog(backups_dir)
        backup = new_backup(bridge.catalog_name, usable, matched, created_at=now(),
                            tool_version=tool_version, config_version=config_version)
        existing = load_existing_backup(out_dir)
        if existing is not None:  # 두 번째 이후 실행: 처음의 직전 값을 지킨다
            backup = merge_backup(existing, backup)
        save_backup(backup, backup_path)
    except (BackupError, OSError, RuntimeError) as exc:
        res.aborted = f"백업을 만들 수 없어 아무것도 바꾸지 않았다: {exc}"
        return res
    res.backup_path = backup_path

    refs_by_keyword: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for f, kws in to_add.items():
        for k in kws:
            refs_by_keyword[k].append((matched[f].collection_id, matched[f].variant_id))
    if chunk_size < 1:
        raise ValueError("chunk_size는 1 이상이어야 한다")
    try:
        for k in sorted(refs_by_keyword):
            refs = refs_by_keyword[k]
            for start in range(0, len(refs), chunk_size):
                bridge.apply_keyword(k, refs[start:start + chunk_size])
                if progress:
                    progress(k, min(start + chunk_size, len(refs)), len(refs))
    except AppleScriptError as exc:
        # 중간에 멈췄다. 이미 붙은 것은 그대로 두고, 같은 명령을 다시 실행하면 이어서 한다.
        res.aborted = (f"{explain_error(exc)}. 일부만 반영됐을 수 있다. 같은 명령을 다시 실행하면 "
                       f"이어서 하고(이미 붙은 키워드는 건너뛴다), 되돌리려면 rollback을 쓴다. "
                       f"백업: {backup_path}")
        _save_after_best_effort(bridge, backup, backup_path)
        return res

    after = {v.name: v for v in bridge.list_variants()}
    unread = record_after(backup, after)
    save_backup(backup, backup_path)
    res.applied_files = len(to_add)
    pre = {f: matched[f] for f in usable}
    res.violations = verify(pre, to_add, after, unread)
    return res


def _save_after_best_effort(bridge, backup, backup_path: Path) -> None:
    """멈춘 뒤에도 가능하면 지금 값을 백업의 직후 값으로 남긴다 (실패해도 조용히 넘어간다)."""
    try:
        record_after(backup, {v.name: v for v in bridge.list_variants()})
        save_backup(backup, backup_path)
    except (AppleScriptError, BackupError, OSError):
        pass


def verify(
    pre: dict[str, VariantInfo], expected: dict[str, list[str]],
    after: dict[str, VariantInfo], unread: Sequence[str] = (),
) -> list[str]:
    """반영 후 검증: **이번 실행 직전** 값과 비교한다.

    별점·태그 그대로, 기존 키워드 유지, 붙일 키워드가 붙었는가.

    백업의 처음 값이 아니라 이번 실행 직전 값과 비교한다. 두 실행 사이에 사용자가 바꾼 값을
    도구가 바꾼 것으로 오해하지 않기 위해서다.
    """
    bad = [f"{f}: 반영 후 값을 읽지 못했다" for f in unread]
    for f, p in pre.items():
        a = after.get(f)
        if a is None:
            if f not in unread:
                bad.append(f"{f}: 반영 후 값을 읽지 못했다")
            continue
        if (a.rating, a.color_tag) != (p.rating, p.color_tag):
            bad.append(f"{f}: 별점·컬러 태그가 바뀌었다 "
                       f"({p.rating},{p.color_tag} -> {a.rating},{a.color_tag})")
        lost = [k for k in p.keywords if k not in a.keywords]
        if lost:
            bad.append(f"{f}: 기존 키워드가 사라졌다 {lost}")
        absent = [k for k in expected.get(f, []) if k not in a.keywords]
        if absent:
            bad.append(f"{f}: 붙이려던 키워드가 없다 {absent}")
    return bad


def load_existing_backup(out_dir: Path):
    """이미 있는 백업을 읽는다 (재실행 안내용). 없으면 None."""
    path = out_dir / FILENAME
    return load_backup(path) if path.exists() else None
