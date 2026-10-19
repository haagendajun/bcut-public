"""노출 측정: 사진과 얼굴 영역의 밝기 통계 (순수 수치 계산, macOS 의존 없음).

밝기(luma)는 0~255. 많이 날아간 밝은 부분(>= HI_LEVEL)과 완전히 뭉개진 어두운 부분(<= LO_LEVEL)의
비율을 함께 본다. 배경이 원래 어둡거나 하얀 사진이 있으므로, 사진 전체의 값만으로는 노출 실패를
가를 수 없고 **얼굴 영역의 밝기**가 더 믿을 만한 단서다 (docs/exposure-experiment.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

HI_LEVEL = 250  # 이 값 이상이면 "날아갔다"
LO_LEVEL = 5  # 이 값 이하면 "뭉개졌다"
MIN_FACE_PIXELS = 24  # 얼굴 영역이 이보다 작으면 통계를 믿지 않는다


@dataclass(frozen=True)
class LumaStats:
    mean: float
    median: float
    p1: float  # 가장 어두운 1% 지점의 밝기
    p99: float  # 가장 밝은 1% 지점의 밝기
    frac_hi: float  # 날아간 픽셀 비율 (0~1)
    frac_lo: float  # 뭉개진 픽셀 비율 (0~1)


def to_gray(image: Image.Image) -> np.ndarray:
    """RGB 이미지를 8비트 밝기 배열 (높이, 폭)로 바꾼다."""
    return np.asarray(image.convert("L"))


def luma_stats(gray: np.ndarray) -> LumaStats:
    if gray.size == 0:
        raise ValueError("빈 이미지의 밝기는 잴 수 없다")
    p1, median, p99 = np.percentile(gray, [1, 50, 99])
    return LumaStats(
        mean=float(gray.mean()),
        median=float(median),
        p1=float(p1),
        p99=float(p99),
        frac_hi=float((gray >= HI_LEVEL).mean()),
        frac_lo=float((gray <= LO_LEVEL).mean()),
    )


def face_region(
    gray: np.ndarray,
    bbox: tuple[float, float, float, float],
    margin: float = 0.15,
) -> np.ndarray | None:
    """얼굴 상자의 안쪽 영역(가장자리 margin 만큼 제외)을 잘라 낸다.

    bbox는 이미지 대비 비율 (x, y, 폭, 높이), 원점은 왼쪽 아래 (Vision 규약).
    머리카락·배경이 섞이는 가장자리를 빼려고 안쪽만 쓴다. 너무 작으면 None.
    """
    h, w = gray.shape
    x, y, bw, bh = bbox
    x0 = int(round((x + bw * margin) * w))
    x1 = int(round((x + bw * (1 - margin)) * w))
    y0 = int(round((1 - y - bh * (1 - margin)) * h))
    y1 = int(round((1 - y - bh * margin) * h))
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if (x1 - x0) * (y1 - y0) < MIN_FACE_PIXELS:
        return None
    return gray[y0:y1, x0:x1]
