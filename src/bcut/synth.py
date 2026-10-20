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


# ---- 흐림 (흔들림, 초점 실패) ---------------------------------------------------------
# 값의 단위는 분석 입력(폭 2048px) 기준 픽셀이다. 원본(8192px)에서의 같은 흐림은 4배 크다.


def gaussian_blur(image: Image.Image, sigma: float) -> Image.Image:
    """전체를 가우시안으로 흐리게 한다 (초점이 사진 전체에서 나간 경우)."""
    from PIL import ImageFilter
    if sigma <= 0:
        return image.convert("RGB")
    return image.convert("RGB").filter(ImageFilter.GaussianBlur(radius=sigma))


def motion_blur(image: Image.Image, length: int, angle_deg: float = 0.0) -> Image.Image:
    """한 방향으로 length 픽셀 번지게 한다 (카메라 흔들림이나 피사체의 움직임).

    각도 방향으로 길이 length인 선을 따라 이미지를 평균 낸다 (정수 이동의 평균).
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    if length <= 1:
        return Image.fromarray(rgb.astype(np.uint8))
    h, w = rgb.shape[:2]
    dx, dy = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    pad = int(length) + 1
    padded = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    acc = np.zeros_like(rgb)
    for k in range(int(length)):
        t = k - (int(length) - 1) / 2.0
        ox, oy = int(round(t * dx)), int(round(t * dy))
        acc += padded[pad + oy:pad + oy + h, pad + ox:pad + ox + w]
    return Image.fromarray(np.clip(acc / int(length) + 0.5, 0, 255).astype(np.uint8))


def blur_region(
    image: Image.Image, bbox: tuple[float, float, float, float], sigma: float, margin: float = 0.25
) -> Image.Image:
    """얼굴 상자 주변만 흐리게 하고 배경은 그대로 둔다 (초점이 얼굴이 아닌 곳에 맞은 경우, 뒷핀).

    bbox는 이미지 대비 비율 (x, y, 폭, 높이), 원점은 왼쪽 아래. 상자를 margin만큼 넓힌 타원 안을
    흐리게 하고, 가장자리는 부드럽게 이어 붙인다.
    """
    from PIL import ImageDraw, ImageFilter
    base = image.convert("RGB")
    w, h = base.size
    x, y, bw, bh = bbox
    cx, cy = (x + bw / 2) * w, (1 - y - bh / 2) * h
    rx, ry = bw * w / 2 * (1 + margin), bh * h / 2 * (1 + margin)
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2.0, min(rx, ry) * 0.15)))
    return Image.composite(gaussian_blur(base, sigma), base, mask)
