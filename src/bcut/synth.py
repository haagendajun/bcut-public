"""합성 열화: 깨끗한 사진에 인위적인 결함을 입힌다 (평가용, devplan T1.15의 일부).

실제 결함이 거의 없는 행사에서 판정기가 어느 정도부터 잡는지 보기 위한 도구다. 합성은 실제
결함과 질감이 다르므로 **경향을 보는 용도**로만 쓰고 합격 판정에는 쓰지 않는다
(docs/recall-eval-plan.md). 원본 이미지는 바꾸지 않고 새 이미지를 돌려준다.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def exposure_lut(ev: float) -> np.ndarray:
    """노출을 ev 단계만큼 바꾸는 8비트 변환표. 선형 빛에서 2**ev배 하고 다시 sRGB로 되돌린다."""
    levels = np.arange(256, dtype=np.float64) / 255.0
    shifted = np.clip(_srgb_to_linear(levels) * (2.0 ** ev), 0.0, 1.0)
    return np.clip(np.round(_linear_to_srgb(shifted) * 255.0), 0, 255).astype(np.uint8)


def shift_exposure(image: Image.Image, ev: float) -> Image.Image:
    """노출을 ev 단계만큼 밝게(+) 또는 어둡게(-) 만든 새 RGB 이미지를 돌려준다."""
    rgb = np.asarray(image.convert("RGB"))
    return Image.fromarray(exposure_lut(ev)[rgb])
