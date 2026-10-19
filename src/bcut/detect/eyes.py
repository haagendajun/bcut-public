"""눈 윤곽점에서 눈 열림 비율을 계산한다 (순수 수치 계산, macOS 의존 없음)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EyeOpenness:
    ratio: float  # 눈 윤곽의 세로 ÷ 가로. 낮을수록 감김
    width_px: float  # 눈 가로 길이 (입력 이미지 픽셀)


def eye_openness(points: Sequence[tuple[float, float]]) -> EyeOpenness | None:
    """윤곽점 4개 이상에서 열림 비율을 구한다.

    주성분 분석으로 눈의 긴 축과 짧은 축을 찾으므로 얼굴이 기울어져도(롤) 값이 거의 같다.
    점이 모자라거나 한 점에 몰려 있으면 None.
    """
    if len(points) < 4:
        return None
    pts = np.asarray(points, dtype=float)
    centered = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj = centered @ vt.T
    major = float(proj[:, 0].max() - proj[:, 0].min())
    minor = float(proj[:, 1].max() - proj[:, 1].min())
    if major <= 1e-9:
        return None
    return EyeOpenness(ratio=minor / major, width_px=major)
