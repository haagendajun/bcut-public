"""노출 판정: 심하게 날아가거나 심하게 어두운 사진을 찾는다 (devplan T1.17).

규칙은 실험으로 정했다 (docs/exposure-experiment.md).

- **과노출 (얼굴 있음):** 판정에 쓰는 얼굴 영역에서 날아간 픽셀(밝기 >= 250) 비율이 face_hi_frac
  이상이면 과노출. 사진 전체가 아니라 **얼굴**을 보는 이유는 배경이 원래 하얗거나 밝은 사진이
  있기 때문이다.
- **과노출 (얼굴 없음):** 얼굴이 없으면 사진 전체의 날아간 비율이 global_hi_frac 이상일 때만.
  이 경우의 근거는 약하다 (얼굴 없는 사진이 22장뿐, 하얀 배경의 제품 사진은 시험하지 못했다).
- **저노출:** 사진에서 **가장 밝은 부분(상위 1%)** 의 밝기가 dark_p99 이하이면 저노출.
  어두운 행사 사진에도 조명 같은 밝은 점이 있어서, 얼굴이나 사진의 평균 밝기로는 정상적으로
  어두운 컷과 가를 수 없지만 "밝은 곳이 아예 없다"는 가를 수 있다.
- 얼굴은 눈 감김 판정과 같은 기준으로 고른다: 가장 큰 얼굴 면적의 group_face_ratio 배 이상.

노출은 **증거가 없는 사유라서 v1에서는 사람이 확인(review)으로만 보낸다** (devplan 1-F).
이 모듈은 "걸렸는가"와 이유만 돌려주고, 등급은 `status_for_flag`가 정한다.
임계값은 입력 경로(CR3 내장 JPEG draft 2048)와 두 행사의 사진으로 정했다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from bcut.detect.exposure import face_region, luma_stats
from bcut.detect.types import Face

Kind = Literal["over_face", "over_global", "under"]
Status = Literal["candidate", "review", "normal"]

# 두 행사(행사 A 구간 397장, 행사 B 138장)의 실제 사진에서 한 장도 안 걸리고,
# 노출을 인위적으로 바꾼 합성에서 어느 정도 잡히는 값 (docs/exposure-experiment.md)
DEFAULT_FACE_HI_FRAC = 0.20  # 실제 사진 최대 11.3%, 노출 +2단계 합성의 83%를 잡는다
DEFAULT_GLOBAL_HI_FRAC = 0.30  # 얼굴 없는 사진. 근거 약함
DEFAULT_DARK_P99 = 120.0  # 실제 사진 최소 137, 노출 -3단계 합성의 100%를 잡는다
DEFAULT_GROUP_FACE_RATIO = 0.5


@dataclass(frozen=True)
class ExposureThresholds:
    face_hi_frac: float = DEFAULT_FACE_HI_FRAC
    global_hi_frac: float = DEFAULT_GLOBAL_HI_FRAC
    dark_p99: float = DEFAULT_DARK_P99
    group_face_ratio: float = DEFAULT_GROUP_FACE_RATIO

    def __post_init__(self) -> None:
        for name in ("face_hi_frac", "global_hi_frac"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name}는 0보다 크고 1 이하여야 한다")
        if not 0 <= self.dark_p99 <= 255:
            raise ValueError("dark_p99는 0~255여야 한다")
        if not 0 < self.group_face_ratio <= 1:
            raise ValueError("group_face_ratio는 0보다 크고 1 이하여야 한다")


@dataclass(frozen=True)
class ExposureVerdict:
    flagged: bool
    kind: Kind | None  # 걸린 이유. 걸리지 않았으면 None
    global_p99: float  # 사진 전체 상위 1% 밝기
    global_hi: float  # 사진 전체 날아간 비율
    face_hi: float | None  # 판정에 쓴 얼굴 중 가장 많이 날아간 비율. 쓸 얼굴이 없으면 None
    faces_considered: int  # 통계를 낸(비슷한 크기의) 얼굴 수


def considered_face_regions(
    gray: np.ndarray, faces: list[Face], group_face_ratio: float
) -> list[np.ndarray]:
    """가장 큰 얼굴과 비슷한 크기의 얼굴들의 영역. 너무 작아 통계를 못 내는 얼굴은 뺀다."""
    if not faces:
        return []
    largest = max(f.face_area for f in faces)
    regions = []
    for f in faces:
        if f.face_area < group_face_ratio * largest:
            continue
        region = face_region(gray, f.bbox)
        if region is not None:
            regions.append(region)
    return regions


def classify_exposure(
    gray: np.ndarray, faces: list[Face], thresholds: ExposureThresholds | None = None
) -> ExposureVerdict:
    """밝기 배열(8비트, 높이×폭)과 얼굴 목록으로 노출 이상을 판정한다."""
    t = thresholds or ExposureThresholds()
    g = luma_stats(gray)
    regions = considered_face_regions(gray, faces, t.group_face_ratio)
    face_hi = max(luma_stats(r).frac_hi for r in regions) if regions else None

    kind: Kind | None = None
    if face_hi is not None and face_hi >= t.face_hi_frac:
        kind = "over_face"
    elif g.p99 <= t.dark_p99:
        kind = "under"
    elif face_hi is None and g.frac_hi >= t.global_hi_frac:
        kind = "over_global"
    return ExposureVerdict(
        flagged=kind is not None, kind=kind, global_p99=g.p99, global_hi=g.frac_hi,
        face_hi=face_hi, faces_considered=len(regions),
    )


def exposure_severity(v: ExposureVerdict) -> float | None:
    """노출 이상이 얼마나 심한지 0~1 (클수록 심하다). 걸리지 않았으면 None. 리포트 정렬용."""
    if not v.flagged:
        return None
    if v.kind == "over_face" and v.face_hi is not None:
        return min(1.0, v.face_hi)
    if v.kind == "over_global":
        return min(1.0, v.global_hi)
    return min(1.0, max(0.0, 1.0 - v.global_p99 / 255.0))  # under: 가장 밝은 곳이 어두울수록 심하다


def status_for_flag(flagged: bool, tier: str = "review") -> Status:
    """걸린 사진의 등급. 노출은 v1에서 review 전용이다 (설정에서 candidate로 승급할 수 있다)."""
    if not flagged:
        return "normal"
    if tier not in ("candidate", "review"):
        raise ValueError(f"등급이 올바르지 않다: {tier}")
    return tier  # type: ignore[return-value]
