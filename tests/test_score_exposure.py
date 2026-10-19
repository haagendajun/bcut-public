import numpy as np
import pytest

from bcut.detect.eyes import EyeOpenness
from bcut.detect.types import Eye, Face
from bcut.score.exposure import (
    DEFAULT_DARK_P99,
    DEFAULT_FACE_HI_FRAC,
    DEFAULT_GLOBAL_HI_FRAC,
    ExposureThresholds,
    classify_exposure,
    considered_face_regions,
    status_for_flag,
)

W, H = 400, 300


def face(x=0.4, y=0.4, w=0.2, h=0.2) -> Face:
    eye = Eye(openness=EyeOpenness(ratio=0.3, width_px=10.0), pupil=None, points=())
    return Face(face_width_px=w * W, face_area=w * h, yaw_deg=0, roll_deg=0, confidence=1.0,
                left=eye, right=eye, bbox=(x, y, w, h), image_width_px=W)


def photo(base=130, bright_top=None) -> np.ndarray:
    """밝기 base로 채운 사진. 정상 사진처럼 위쪽 일부에 밝은 하늘(240)을 둔다."""
    gray = np.full((H, W), base, dtype=np.uint8)
    gray[:10, :] = 240 if bright_top is None else bright_top
    return gray


def blow_face(gray: np.ndarray, fraction: float, bbox=(0.4, 0.4, 0.2, 0.2)) -> np.ndarray:
    """얼굴 상자 안쪽 영역에서 fraction 만큼의 픽셀을 255로 만든다."""
    from bcut.detect.exposure import face_region
    out = gray.copy()
    x, y, bw, bh = bbox
    x0, x1 = int((x + bw * 0.15) * W), int((x + bw * 0.85) * W)
    y0, y1 = int((1 - y - bh * 0.85) * H), int((1 - y - bh * 0.15) * H)
    rows = int(round((y1 - y0) * fraction))
    out[y0:y0 + rows, x0:x1] = 255
    assert face_region(out, bbox) is not None
    return out


# ---- 과노출 (얼굴 있음) -------------------------------------------------------


def test_blown_face_is_flagged_as_over_face():
    gray = blow_face(photo(), 0.5)
    v = classify_exposure(gray, [face()])
    assert v.flagged and v.kind == "over_face"
    assert v.face_hi == pytest.approx(0.5, abs=0.06)


def test_face_with_a_little_highlight_is_not_flagged():
    gray = blow_face(photo(), 0.11)  # 실제 정상 사진의 최대(11%) 수준
    v = classify_exposure(gray, [face()])
    assert not v.flagged and v.kind is None


def test_threshold_boundary_is_inclusive():
    gray = blow_face(photo(), DEFAULT_FACE_HI_FRAC + 0.03)
    assert classify_exposure(gray, [face()]).flagged
    assert not classify_exposure(blow_face(photo(), DEFAULT_FACE_HI_FRAC - 0.06), [face()]).flagged


def test_bright_background_alone_does_not_flag_a_photo_with_a_normal_face():
    gray = np.full((H, W), 255, dtype=np.uint8)  # 배경이 온통 하얗다
    gray[100:200, 160:240] = 130  # 얼굴 영역은 정상 밝기
    v = classify_exposure(gray, [face()])
    assert not v.flagged and v.global_hi > 0.6


# ---- 저노출 ------------------------------------------------------------------


def test_photo_with_nothing_bright_is_flagged_as_under():
    gray = np.full((H, W), 40, dtype=np.uint8)
    gray[:10, :] = 90
    v = classify_exposure(gray, [face()])
    assert v.flagged and v.kind == "under"
    assert v.global_p99 <= DEFAULT_DARK_P99


def test_dark_event_photo_with_bright_lights_is_not_flagged():
    gray = np.full((H, W), 20, dtype=np.uint8)  # 어두운 실내
    gray[50:60, 50:200] = 250  # 조명 (사진의 1%보다 많다)
    v = classify_exposure(gray, [face()])
    assert not v.flagged


def test_dark_face_in_a_scene_with_highlights_is_not_flagged():
    gray = np.full((H, W), 60, dtype=np.uint8)
    gray[:30, :] = 230  # 사진의 일부는 밝다
    assert not classify_exposure(gray, [face()]).flagged


def test_under_applies_to_photos_without_faces_too():
    gray = np.full((H, W), 30, dtype=np.uint8)
    v = classify_exposure(gray, [])
    assert v.flagged and v.kind == "under" and v.face_hi is None


# ---- 얼굴 없는 사진 ------------------------------------------------------------


def test_no_face_photo_flagged_only_when_mostly_blown():
    gray = np.full((H, W), 140, dtype=np.uint8)
    gray[: int(H * (DEFAULT_GLOBAL_HI_FRAC + 0.05))] = 255
    v = classify_exposure(gray, [])
    assert v.flagged and v.kind == "over_global"


def test_no_face_photo_with_some_highlights_is_not_flagged():
    gray = np.full((H, W), 140, dtype=np.uint8)
    gray[: int(H * 0.15)] = 255  # 15%
    assert not classify_exposure(gray, []).flagged


def test_global_overexposure_rule_is_not_used_when_a_face_is_present():
    gray = np.full((H, W), 255, dtype=np.uint8)
    gray[100:200, 160:240] = 130  # 얼굴은 정상
    assert classify_exposure(gray, [face()]).kind is None


# ---- 단체 사진 / 얼굴 선택 ------------------------------------------------------


def test_small_background_face_is_ignored():
    big = face(x=0.1, y=0.3, w=0.3, h=0.4)
    small = face(x=0.7, y=0.7, w=0.06, h=0.08)  # 면적이 큰 얼굴의 4%
    gray = blow_face(photo(), 0.9, bbox=small.bbox)  # 작은 얼굴만 날아갔다
    v = classify_exposure(gray, [big, small])
    assert not v.flagged and v.faces_considered == 1


def test_comparable_face_that_is_blown_flags_the_photo():
    a = face(x=0.1, y=0.3, w=0.2, h=0.2)
    b = face(x=0.6, y=0.3, w=0.2, h=0.2)
    gray = blow_face(photo(), 0.6, bbox=b.bbox)
    v = classify_exposure(gray, [a, b])
    assert v.flagged and v.kind == "over_face" and v.faces_considered == 2


def test_considered_face_regions_skips_unmeasurable_faces():
    tiny = face(x=0.5, y=0.5, w=0.001, h=0.001)
    assert considered_face_regions(photo(), [tiny], 0.5) == []
    assert considered_face_regions(photo(), [], 0.5) == []


def test_face_too_small_to_measure_falls_back_to_the_no_face_rule():
    tiny = face(x=0.5, y=0.5, w=0.001, h=0.001)
    gray = np.full((H, W), 140, dtype=np.uint8)
    gray[: int(H * 0.5)] = 255
    v = classify_exposure(gray, [tiny])
    assert v.kind == "over_global" and v.faces_considered == 0


# ---- 설정과 등급 ---------------------------------------------------------------


def test_custom_thresholds_change_the_outcome():
    gray = blow_face(photo(), 0.3)
    assert classify_exposure(gray, [face()]).flagged
    assert not classify_exposure(gray, [face()], ExposureThresholds(face_hi_frac=0.9)).flagged


@pytest.mark.parametrize("kwargs", [
    {"face_hi_frac": 0.0}, {"face_hi_frac": 1.5}, {"global_hi_frac": 0.0},
    {"dark_p99": -1}, {"dark_p99": 300}, {"group_face_ratio": 0.0}, {"group_face_ratio": 2.0},
])
def test_invalid_thresholds_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ExposureThresholds(**kwargs)


def test_exposure_is_review_only_by_default():
    assert status_for_flag(True) == "review"
    assert status_for_flag(False) == "normal"


def test_exposure_can_be_promoted_to_candidate_later():
    assert status_for_flag(True, "candidate") == "candidate"
    assert status_for_flag(False, "candidate") == "normal"


def test_invalid_tier_is_rejected():
    with pytest.raises(ValueError):
        status_for_flag(True, "delete")
