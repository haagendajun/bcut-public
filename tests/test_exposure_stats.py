import numpy as np
import pytest
from PIL import Image

from bcut.detect.exposure import HI_LEVEL, LO_LEVEL, face_region, luma_stats, to_gray
from bcut.synth import exposure_lut, shift_exposure


def solid(value: int, size=(40, 30)) -> np.ndarray:
    return np.full((size[1], size[0]), value, dtype=np.uint8)


# ---- 밝기 통계 --------------------------------------------------------------


def test_stats_of_a_flat_gray_image():
    s = luma_stats(solid(120))
    assert s.mean == pytest.approx(120) and s.median == 120
    assert s.p1 == 120 and s.p99 == 120
    assert s.frac_hi == 0 and s.frac_lo == 0


def test_blown_and_crushed_fractions():
    gray = np.concatenate([solid(255)[:10], solid(0)[:5], solid(120)[:15]])  # 10:5:15행
    s = luma_stats(gray)
    assert s.frac_hi == pytest.approx(10 / 30)
    assert s.frac_lo == pytest.approx(5 / 30)


def test_thresholds_are_inclusive():
    gray = np.array([[HI_LEVEL, HI_LEVEL - 1, LO_LEVEL, LO_LEVEL + 1]], dtype=np.uint8)
    s = luma_stats(gray)
    assert s.frac_hi == pytest.approx(0.25) and s.frac_lo == pytest.approx(0.25)


def test_empty_image_is_rejected():
    with pytest.raises(ValueError):
        luma_stats(np.zeros((0, 0), dtype=np.uint8))


def test_to_gray_returns_uint8_2d():
    gray = to_gray(Image.new("RGB", (8, 6), (255, 255, 255)))
    assert gray.shape == (6, 8) and gray.dtype == np.uint8 and gray.min() == 255


# ---- 얼굴 영역 ---------------------------------------------------------------


def test_face_region_uses_the_inner_part_and_vision_orientation():
    gray = solid(0, (100, 100))
    # 얼굴 상자: x 0.4~0.6, y(아래 기준) 0.4~0.6 -> 이미지 가운데. 그 안쪽만 밝게 칠한다
    gray[40:60, 40:60] = 200
    region = face_region(gray, (0.4, 0.4, 0.2, 0.2), margin=0.0)
    assert region.shape == (20, 20) and region.min() == 200


def test_face_region_origin_is_bottom_left():
    gray = solid(0, (100, 100))
    gray[0:20, 0:20] = 255  # 이미지 왼쪽 위
    top_left = face_region(gray, (0.0, 0.8, 0.2, 0.2), margin=0.0)  # 아래 기준 y=0.8이면 위쪽
    bottom_left = face_region(gray, (0.0, 0.0, 0.2, 0.2), margin=0.0)
    assert top_left.min() == 255
    assert bottom_left.max() == 0


def test_face_region_margin_shrinks_the_crop():
    gray = solid(100, (100, 100))
    full = face_region(gray, (0.2, 0.2, 0.5, 0.5), margin=0.0)
    inner = face_region(gray, (0.2, 0.2, 0.5, 0.5), margin=0.15)
    assert inner.shape[0] < full.shape[0] and inner.shape[1] < full.shape[1]


def test_tiny_face_region_is_none():
    assert face_region(solid(100, (100, 100)), (0.5, 0.5, 0.02, 0.02)) is None


def test_face_region_is_clamped_to_the_image():
    region = face_region(solid(100, (100, 100)), (0.9, 0.9, 0.5, 0.5), margin=0.0)
    assert region is not None and region.shape[0] <= 100 and region.shape[1] <= 100


# ---- 합성 노출 ---------------------------------------------------------------


def test_zero_ev_is_identity():
    lut = exposure_lut(0.0)
    assert np.array_equal(lut, np.arange(256, dtype=np.uint8))


def test_positive_ev_brightens_and_negative_darkens_midtones():
    mid = 118
    assert exposure_lut(1.0)[mid] > mid
    assert exposure_lut(2.0)[mid] > exposure_lut(1.0)[mid]
    assert exposure_lut(-1.0)[mid] < mid
    assert exposure_lut(-2.0)[mid] < exposure_lut(-1.0)[mid]


def test_one_stop_up_roughly_doubles_linear_light():
    # sRGB 118은 선형 약 0.18. 1단계 위는 약 0.36 -> sRGB 약 162
    assert 158 <= exposure_lut(1.0)[118] <= 166


def test_large_shifts_clip_to_pure_white_or_black():
    assert exposure_lut(5.0)[200] == 255
    assert exposure_lut(-8.0)[60] <= 1
    assert exposure_lut(3.0)[0] == 0  # 완전한 검정은 밝게 해도 검정


def test_lut_is_monotonic():
    for ev in (-3, -1, 1, 3):
        assert np.all(np.diff(exposure_lut(ev).astype(int)) >= 0)


def test_shift_exposure_returns_a_new_image_and_keeps_the_original():
    src = Image.new("RGB", (4, 4), (118, 118, 118))
    out = shift_exposure(src, 2.0)
    assert out is not src and out.size == src.size and out.mode == "RGB"
    assert src.getpixel((0, 0)) == (118, 118, 118)  # 원본은 그대로
    assert out.getpixel((0, 0))[0] > 118
