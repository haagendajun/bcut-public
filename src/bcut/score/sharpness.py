"""흔들림·초점 판정 (devplan T1.6, T1.7). 규칙은 실험으로 정했다 (docs/sharpness-experiment.md).

두 가지 사유를 나눠서 본다.

- **blur (흔들림·전체 흐림):** 사진에서 **가장 선명한 타일 쪽** (타일 흐림의 하위 10% 지점)이
  best_blur_min 이상이면 "사진 어디에도 선명한 곳이 없다"로 본다. 배경이 보케인 인물 사진도 얼굴
  쪽 타일은 선명해서 걸리지 않는다.
- **out_of_focus (초점 실패):** 얼굴 안쪽을 **풀 해상도**로 재서 흐림이 face_blur_min 이상인데
  사진 어딘가는 선명하다 (best < best_blur_min). 초점이 배경에 맞은 경우다.
  얼굴 폭이 min_face_px(풀 해상도 기준) 미만이면 이 규칙은 쓰지 않는다. 얼굴이 작을수록 정상
  사진에서도 값이 높게 나와 (EVENT_A 끝 구간 얼굴 355~380px에서 최대 0.74) 구분할 수 없었다.
  face 규칙에서 blur로 걸린 경우(best도 높음)는 blur로 센다.
- 얼굴은 눈 감김·노출과 같은 기준으로 고른다: 가장 큰 얼굴 면적의 group_face_ratio 배 이상.

실제 결함이 한 장도 없어서(정탐 근거 없음) **v1에서는 사람이 확인(review)으로만 보낸다**
(devplan 1-F). 이 모듈은 "걸렸는가"와 이유만 돌려주고, 등급은 `status_for_flag`가 정한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from bcut.score.exposure import status_for_flag  # noqa: F401  (등급 규칙은 노출과 같다)

Kind = Literal["blur", "out_of_focus"]

# 실제 사진(EVENT_A·EVENT_B 535장, 100% 확대로 결함 없음 확인)에서 한 장도 안 걸리는 값
DEFAULT_BEST_BLUR_MIN = 0.55
DEFAULT_FACE_BLUR_MIN = 0.62  # 얼굴 폭 420px 이상에서 실제 사진 최대 0.569, 여유 0.05
DEFAULT_MIN_FACE_PX = 420
DEFAULT_GROUP_FACE_RATIO = 0.5


@dataclass(frozen=True)
class SharpnessThresholds:
    best_blur_min: float = DEFAULT_BEST_BLUR_MIN
    face_blur_min: float = DEFAULT_FACE_BLUR_MIN
    min_face_px: int = DEFAULT_MIN_FACE_PX
    group_face_ratio: float = DEFAULT_GROUP_FACE_RATIO

    def __post_init__(self) -> None:
        for name in ("best_blur_min", "face_blur_min"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name}는 0보다 크고 1 이하여야 한다")
        if self.min_face_px < 0:
            raise ValueError("min_face_px는 0 이상이어야 한다")
        if not 0 < self.group_face_ratio <= 1:
            raise ValueError("group_face_ratio는 0보다 크고 1 이하여야 한다")


@dataclass(frozen=True)
class FaceBlur:
    """풀 해상도에서 잰 얼굴 하나의 흐림. blur가 None이면 재지 못한 것(평탄하거나 너무 작음)."""

    area: float  # 얼굴 면적 (비율). 비슷한 크기 얼굴을 고르는 데 쓴다
    blur: float | None
    px: int  # 측정한 안쪽 영역의 폭 (풀 해상도 픽셀)


@dataclass(frozen=True)
class SharpnessVerdict:
    flagged: bool
    kind: Kind | None
    best: float | None  # 가장 선명한 타일 쪽 흐림. 유효 타일이 없으면 None
    face_blur: float | None  # 판정에 쓴 얼굴 중 가장 흐린 값. 쓸 얼굴이 없으면 None
    face_px: int | None  # 그 얼굴의 폭
    faces_considered: int  # 판정에 쓴 얼굴 수


def considered_faces(faces: Sequence[FaceBlur], t: SharpnessThresholds) -> list[FaceBlur]:
    """비슷한 크기이고, 잴 수 있고, 폭이 충분한 얼굴."""
    if not faces:
        return []
    largest = max(f.area for f in faces)
    return [
        f for f in faces
        if f.area >= t.group_face_ratio * largest and f.blur is not None and f.px >= t.min_face_px
    ]


def classify_sharpness(
    best: float | None, faces: Sequence[FaceBlur], thresholds: SharpnessThresholds | None = None
) -> SharpnessVerdict:
    t = thresholds or SharpnessThresholds()
    used = considered_faces(faces, t)
    worst = max(used, key=lambda f: f.blur) if used else None  # type: ignore[arg-type,return-value]
    face_blur = worst.blur if worst else None

    kind: Kind | None = None
    if best is not None and best >= t.best_blur_min:
        kind = "blur"
    elif face_blur is not None and face_blur >= t.face_blur_min:
        kind = "out_of_focus"
    return SharpnessVerdict(
        flagged=kind is not None, kind=kind, best=best, face_blur=face_blur,
        face_px=worst.px if worst else None, faces_considered=len(used),
    )


def sharpness_severity(v: SharpnessVerdict) -> float | None:
    """흐림이 얼마나 심한지 0~1 (클수록 심하다). 걸리지 않았으면 None. 리포트 정렬용."""
    if not v.flagged:
        return None
    if v.kind == "blur" and v.best is not None:
        return min(1.0, v.best)
    return min(1.0, v.face_blur or 0.0)
