import numpy as np
import pytest
from PIL import Image

from bcut.detect.sharpness import (
    BLUR_KERNEL,
    blur_metric,
    inner_region,
    mean_gradient,
    tile_blur_metrics,
)
from bcut.synth import blur_region, gaussian_blur, motion_blur


def textured(size=(160, 120), seed=0) -> np.ndarray:
    """선명한 질감(무작위 격자 무늬)을 가진 8비트 밝기 배열."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, size=(size[1] // 4, size[0] // 4), dtype=np.uint8)
    return np.kron(base, np.ones((4, 4), dtype=np.uint8))


def blurred(gray: np.ndarray, sigma: float) -> np.ndarray:
    return np.asarray(gaussian_blur(Image.fromarray(gray).convert("RGB"), sigma).convert("L"))


def test_flat_region_has_no_measurement():
    flat = np.full((100, 100), 128, dtype=np.uint8)
    assert blur_metric(flat) is None
    assert mean_gradient(flat) == 0.0


def test_tiny_region_has_no_measurement():
    assert blur_metric(textured((16, 16))) is None


def test_sharp_texture_scores_low_and_blurred_scores_high():
    sharp = blur_metric(textured())
    soft = blur_metric(blurred(textured(), 2.0))
    very_soft = blur_metric(blurred(textured(), 5.0))
    assert sharp is not None and soft is not None and very_soft is not None
    assert sharp < soft < very_soft <= 1.0
    assert sharp < 0.5 < very_soft


def test_metric_is_between_zero_and_one():
    for sigma in (0, 1, 3, 8):
        m = blur_metric(blurred(textured(), sigma))
        assert m is None or 0.0 <= m <= 1.0


def test_metric_ignores_overall_brightness_and_contrast():
    base = textured()
    dim = (base * 0.4 + 20).astype(np.uint8)  # 어둡고 대비가 낮은 같은 장면
    assert blur_metric(dim) == pytest.approx(blur_metric(base), abs=0.08)


def test_blurring_a_dim_image_is_still_detected():
    dim = (textured() * 0.4 + 20).astype(np.uint8)
    assert blur_metric(blurred(dim, 3.0)) > blur_metric(dim) + 0.15


def test_motion_blur_is_detected_along_its_direction():
    base = textured((200, 150))
    shaken = np.asarray(motion_blur(Image.fromarray(base).convert("RGB"), 15, 0).convert("L"))
    assert blur_metric(shaken) > blur_metric(base) + 0.10


def test_tile_metrics_skip_flat_tiles():
    img = np.full((120, 160), 128, dtype=np.uint8)
    img[:60, :80] = textured((80, 60))  # 왼쪽 위 4분의 1만 질감이 있다
    tiles = tile_blur_metrics(img, grid=(4, 3))
    assert 0 < len(tiles) < 12


def test_tile_metrics_of_sharp_vs_blurred_photo():
    sharp = tile_blur_metrics(textured((320, 240)), grid=(4, 3))
    soft = tile_blur_metrics(blurred(textured((320, 240)), 4.0), grid=(4, 3))
    assert np.median(sharp) < np.median(soft)


def test_inner_region_is_clamped_and_oriented():
    gray = np.zeros((200, 200), dtype=np.uint8)
    gray[0:60, 0:60] = 255  # 이미지 왼쪽 위
    top_left = inner_region(gray, (0.0, 0.7, 0.3, 0.3), margin=0.0)
    assert top_left.min() == 255
    assert inner_region(gray, (0.5, 0.5, 0.02, 0.02)) is None


def test_kernel_constant_is_odd():
    assert BLUR_KERNEL % 2 == 1


# ---- 흐림 합성 ----------------------------------------------------------------


def test_gaussian_blur_zero_is_identity():
    img = Image.fromarray(np.stack([textured()] * 3, axis=-1))
    assert np.array_equal(np.asarray(gaussian_blur(img, 0)), np.asarray(img))


def test_motion_blur_length_one_is_identity_and_keeps_size():
    img = Image.fromarray(np.stack([textured()] * 3, axis=-1))
    out = motion_blur(img, 1)
    assert out.size == img.size and np.array_equal(np.asarray(out), np.asarray(img))
    assert motion_blur(img, 9, 30).size == img.size


def test_motion_blur_is_directional():
    base = textured((200, 150))
    img = Image.fromarray(np.stack([base] * 3, axis=-1))
    horizontal = np.asarray(motion_blur(img, 15, 0).convert("L")).astype(float)
    vertical = np.asarray(motion_blur(img, 15, 90).convert("L")).astype(float)
    grad_x = lambda a: np.abs(np.diff(a, axis=1)).mean()  # noqa: E731
    grad_y = lambda a: np.abs(np.diff(a, axis=0)).mean()  # noqa: E731
    assert grad_x(horizontal) < grad_y(horizontal)  # 가로로 번졌으니 가로 변화가 줄었다
    assert grad_y(vertical) < grad_x(vertical)


def test_blur_region_blurs_the_face_and_keeps_the_background():
    base = textured((320, 240))
    img = Image.fromarray(np.stack([base] * 3, axis=-1))
    bbox = (0.35, 0.3, 0.3, 0.4)  # 가운데
    out = np.asarray(blur_region(img, bbox, sigma=4.0).convert("L"))
    face_before, face_after = inner_region(base, bbox), inner_region(out, bbox)
    assert blur_metric(face_after) > blur_metric(face_before) + 0.2
    corner_before, corner_after = base[:40, :40], out[:40, :40]
    assert np.array_equal(corner_before, corner_after)  # 먼 배경은 그대로


def test_blur_region_does_not_modify_the_source_image():
    img = Image.fromarray(np.stack([textured()] * 3, axis=-1))
    before = np.asarray(img).copy()
    blur_region(img, (0.3, 0.3, 0.4, 0.4), 5.0)
    assert np.array_equal(np.asarray(img), before)
