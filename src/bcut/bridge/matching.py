"""리포트의 컷과 Capture One 카탈로그의 변형을 짝짓는다 (devplan T2.2).

짝짓기 규칙 (위에서부터):
1. **경로가 정확히 같으면** 그것. (`행사 폴더/파일명`과 카탈로그의 원본 경로를 정규화해서 비교)
2. 경로로 못 찾으면 **파일명**으로 찾되, 같은 파일명이 카탈로그에 둘 이상이면 **모호함**으로 분류해
   **반영하지 않는다** (엉뚱한 사진에 표시하는 것이 가장 나쁘다).
3. 카탈로그에 없으면 `missing`. 리포트에 없는 카탈로그 사진은 `extra`(정보용)다.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bcut.bridge.capture_one import VariantInfo


@dataclass(frozen=True)
class MatchResult:
    matched: dict[str, VariantInfo]  # 리포트 파일명 -> 변형
    missing: list[str] = field(default_factory=list)  # 카탈로그에 없는 컷
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # 파일명 -> 후보 경로들
    extra: list[str] = field(default_factory=list)  # 리포트에 없는 카탈로그 사진(파일명)
    by_name: list[str] = field(default_factory=list)  # 경로가 아니라 파일명으로 짝지은 컷

    @property
    def clean(self) -> bool:
        return not self.missing and not self.ambiguous


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def match_cuts(
    files: Iterable[str], variants: Sequence[VariantInfo], event_folder: Path | None = None
) -> MatchResult:
    """`files`(리포트의 파일명)를 카탈로그 변형과 짝짓는다."""
    by_path = {_norm(v.path): v for v in variants}
    by_name: dict[str, list[VariantInfo]] = defaultdict(list)
    for v in variants:
        by_name[os.path.basename(v.path)].append(v)

    matched: dict[str, VariantInfo] = {}
    missing: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    named: list[str] = []
    wanted = list(files)
    for f in wanted:
        hit = by_path.get(_norm(event_folder / f)) if event_folder is not None else None
        if hit is not None:
            matched[f] = hit
            continue
        cands = by_name.get(f, [])
        if len(cands) == 1:
            matched[f] = cands[0]
            named.append(f)
        elif len(cands) > 1:
            ambiguous[f] = sorted(c.path for c in cands)
        else:
            missing.append(f)
    used = {id(v) for v in matched.values()}
    extra = sorted(os.path.basename(v.path) for v in variants if id(v) not in used)
    return MatchResult(matched=matched, missing=missing, ambiguous=ambiguous, extra=extra,
                       by_name=named)
