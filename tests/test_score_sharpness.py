from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from bcut.detect.face_sharp import crop_face, measure_face_blurs
from bcut.detect.sharpness import best_tile_blur
from bcut.score.sharpness import (
    FaceBlur,
    SharpnessThresholds,
    classify_sharpness,
    sharpness_severity,
)

T = SharpnessThresholds()


def face(area=0.05, blur=0.3, px=600):
    return FaceBlur(area=area, blur=blur, px=px)


def test_sharp_photo_not_flagged():
    v = classify_sharpness(0.30, [face(blur=0.4)], T)
    assert not v.flagged and v.kind is None and v.faces_considered == 1


def test_global_blur_flagged_as_blur():
    v = classify_sharpness(0.60, [face(blur=0.7)], T)
    assert v.kind == "blur"  # best도 높으면 face 규칙보다 blur가 우선


def test_face_blurry_but_background_sharp_is_out_of_focus():
    v = classify_sharpness(0.30, [face(blur=0.70)], T)
    assert v.kind == "out_of_focus" and v.face_blur == 0.70 and v.face_px == 600


def test_small_face_is_ignored():
    v = classify_sharpness(0.30, [face(blur=0.9, px=T.min_face_px - 1)], T)
    assert not v.flagged and v.faces_considered == 0 and v.face_blur is None


def test_unmeasurable_face_is_ignored():
    v = classify_sharpness(0.30, [FaceBlur(area=0.05, blur=None, px=0)], T)
    assert not v.flagged and v.faces_considered == 0


def test_no_faces_uses_best_only():
    assert classify_sharpness(0.60, [], T).kind == "blur"
    assert not classify_sharpness(0.40, [], T).flagged
    assert not classify_sharpness(None, [], T).flagged


def test_group_uses_comparable_faces_only():
    faces = [face(area=0.10, blur=0.3), face(area=0.04, blur=0.9)]  # 작은 얼굴은 0.5배 미만
    assert not classify_sharpness(0.30, faces, T).flagged
    faces = [face(area=0.10, blur=0.3), face(area=0.06, blur=0.9)]
    assert classify_sharpness(0.30, faces, T).kind == "out_of_focus"


def test_threshold_boundaries_are_inclusive():
    assert classify_sharpness(T.best_blur_min, [], T).kind == "blur"
    assert classify_sharpness(0.30, [face(blur=T.face_blur_min)], T).kind == "out_of_focus"


def test_severity():
    assert sharpness_severity(classify_sharpness(0.3, [face()], T)) is None
    assert sharpness_severity(classify_sharpness(0.7, [], T)) == pytest.approx(0.7)
    assert sharpness_severity(classify_sharpness(0.3, [face(blur=0.8)], T)) == pytest.approx(0.8)
    assert sharpness_severity(classify_sharpness(1.2, [], SharpnessThresholds())) == 1.0


@pytest.mark.parametrize("kwargs", [
    {"best_blur_min": 0}, {"face_blur_min": 1.5}, {"min_face_px": -1}, {"group_face_ratio": 0},
])
def test_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        SharpnessThresholds(**kwargs)


def _noise(h=240, w=320, seed=0):
    return np.random.default_rng(seed).integers(0, 255, (h, w)).astype(np.uint8)


def test_best_tile_blur_sharp_vs_flat():
    assert best_tile_blur(_noise()) < 0.5
    assert best_tile_blur(np.full((240, 320), 128, np.uint8)) is None


def test_crop_face_box_inside_crop():
    full = Image.new("RGB", (1000, 800))
    crop, nb = crop_face(full, (0.4, 0.4, 0.2, 0.2))
    assert all(0 <= v <= 1 for v in nb)
    assert crop.size[0] > 200  # 얼굴 폭 200 + 여백


def test_measure_face_blurs_loads_full_only_with_faces():
    calls = []

    def load():
        calls.append(1)
        return Image.fromarray(np.stack([_noise(800, 1000)] * 3, axis=-1))

    assert measure_face_blurs([], load) == [] and not calls
    faces = [SimpleNamespace(bbox=(0.3, 0.3, 0.4, 0.4), face_area=0.16)]
    out = measure_face_blurs(faces, load)
    assert len(calls) == 1 and len(out) == 1
    assert out[0].blur is not None and out[0].px > 100


def test_measure_face_blurs_tiny_face_unmeasurable():
    img = Image.fromarray(np.stack([_noise(800, 1000)] * 3, axis=-1))
    faces = [SimpleNamespace(bbox=(0.3, 0.3, 0.01, 0.01), face_area=0.0001)]
    out = measure_face_blurs(faces, lambda: img)
    assert out[0].blur is None and out[0].px == 0
