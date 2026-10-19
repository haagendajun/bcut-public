import pytest

from bcut.detect.eyes import EyeOpenness
from bcut.detect.types import Eye, Face
from bcut.score.eyes import (
    DEFAULT_CANDIDATE_MAX,
    DEFAULT_MIN_EYE_WIDTH_FRAC,
    DEFAULT_REVIEW_MAX,
    EyesThresholds,
    classify_eyes,
    eye_width_fraction,
    eyes_score,
    status_for_measurements,
    status_for_score,
)


def face(left: float | None, right: float | None, area: float = 0.01,
         eye_w: float = 20.0, image_w: int = 0) -> Face:
    def make(ratio):
        if ratio is None:
            return Eye(openness=None, pupil=None, points=())
        return Eye(openness=EyeOpenness(ratio=ratio, width_px=eye_w), pupil=None, points=())
    return Face(face_width_px=400, face_area=area, yaw_deg=0, roll_deg=0, confidence=1.0,
                left=make(left), right=make(right), image_width_px=image_w)


T = EyesThresholds()


def test_defaults_are_ordered():
    assert 0 < DEFAULT_CANDIDATE_MAX <= DEFAULT_REVIEW_MAX


def test_invalid_thresholds_are_rejected():
    with pytest.raises(ValueError):
        EyesThresholds(candidate_max=0.2, review_max=0.1)
    with pytest.raises(ValueError):
        EyesThresholds(candidate_max=0.0, review_max=0.1)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.05, "candidate"),
        (DEFAULT_CANDIDATE_MAX, "candidate"),  # 경계는 candidate에 포함
        (DEFAULT_CANDIDATE_MAX + 0.001, "review"),
        (DEFAULT_REVIEW_MAX, "review"),
        (DEFAULT_REVIEW_MAX + 0.001, "normal"),
        (0.35, "normal"),
    ],
)
def test_status_for_score(score, expected):
    assert status_for_score(score, T) == expected


def test_score_uses_the_more_open_eye():
    # 한쪽 눈만 감김(윙크) -> 덜 감긴 눈 기준이라 점수가 높다
    assert eyes_score(face(0.05, 0.30)) == pytest.approx(0.30)


def test_wink_is_not_a_candidate():
    verdict = classify_eyes([face(0.05, 0.30)])
    assert verdict.status == "normal"


def test_both_eyes_closed_is_candidate():
    verdict = classify_eyes([face(0.08, 0.10)])
    assert verdict.status == "candidate"
    assert verdict.score == pytest.approx(0.10)


def test_squint_zone_goes_to_review_not_candidate():
    verdict = classify_eyes([face(0.14, 0.15)])
    assert verdict.status == "review"
    assert DEFAULT_CANDIDATE_MAX < 0.15 <= DEFAULT_REVIEW_MAX  # 입력값이 review 구간 안에 있다


def test_only_the_largest_face_counts():
    big_open = face(0.30, 0.31, area=0.05)
    small_closed = face(0.05, 0.06, area=0.001)
    verdict = classify_eyes([small_closed, big_open])
    assert verdict.status == "normal"
    assert verdict.face_count == 2


def test_no_face():
    verdict = classify_eyes([])
    assert (verdict.status, verdict.score, verdict.face_count) == ("no_face", None, 0)


def test_face_without_eye_landmarks_is_unscorable():
    verdict = classify_eyes([face(None, None)])
    assert verdict.status == "unscorable"
    assert verdict.score is None


def test_one_eye_missing_uses_the_other():
    assert classify_eyes([face(None, 0.09)]).status == "candidate"


def test_custom_thresholds_can_promote_a_zone():
    strict = EyesThresholds(candidate_max=0.10, review_max=0.12)
    assert classify_eyes([face(0.13, 0.13)], strict).status == "normal"


# ---- 판정 불가: 눈이 너무 좁은 얼굴 (T1.5) ----------------------------------

IMG = 2048  # 입력 폭
SMALL = 12.0  # 입력 2048px에서 눈 폭 12px -> 비율 0.0059, 기본 경계(0.0073) 미만
NORMAL = 21.0  # 비율 0.0103


def test_eye_width_fraction_uses_input_width():
    frac = eye_width_fraction(face(0.2, 0.2, eye_w=20.0, image_w=IMG))
    assert frac == pytest.approx(20.0 / IMG)


def test_eye_width_fraction_is_none_when_input_width_unknown():
    assert eye_width_fraction(face(0.2, 0.2, eye_w=20.0, image_w=0)) is None


def test_narrow_eyes_go_to_review_even_if_score_says_normal():
    verdict = classify_eyes([face(0.30, 0.30, eye_w=SMALL, image_w=IMG)])
    assert verdict.status == "review"
    assert verdict.note == "small_eye"


def test_narrow_eyes_go_to_review_even_if_score_says_candidate():
    # 눈이 좁으면 점수 자체를 믿을 수 없으므로 후보로 확정하지 않는다
    verdict = classify_eyes([face(0.08, 0.09, eye_w=SMALL, image_w=IMG)])
    assert verdict.status == "review"
    assert verdict.note == "small_eye"


def test_normal_width_eyes_use_score_thresholds():
    verdict = classify_eyes([face(0.08, 0.09, eye_w=NORMAL, image_w=IMG)])
    assert verdict.status == "candidate"
    assert verdict.note is None


def test_unknown_input_width_skips_the_width_rule():
    verdict = classify_eyes([face(0.08, 0.09, eye_w=SMALL, image_w=0)])
    assert verdict.status == "candidate"


def test_default_min_eye_width_is_about_60px_at_8192():
    assert DEFAULT_MIN_EYE_WIDTH_FRAC * 8192 == pytest.approx(60, abs=1)


def test_width_rule_can_be_disabled_with_zero():
    off = EyesThresholds(min_eye_width_frac=0.0)
    assert classify_eyes([face(0.30, 0.30, eye_w=1.0, image_w=IMG)], off).status == "normal"


def test_negative_min_width_is_rejected():
    with pytest.raises(ValueError):
        EyesThresholds(min_eye_width_frac=-0.1)


def test_status_for_measurements_without_width_uses_score_only():
    assert status_for_measurements(0.10, None, T) == ("candidate", None)
    assert status_for_measurements(0.10, 0.002, T) == ("review", "small_eye")


# ---- 단체 사진 정책 (2026-10-19 확정: 비슷한 크기 얼굴을 모두 보고, 후보는 확인으로) -----

BIG = 0.04
CLOSED = (0.08, 0.09)   # 후보 구간
OPEN = (0.30, 0.31)     # 정상
SQUINT = (0.14, 0.15)   # 확인 구간


def test_single_face_candidate_stays_candidate():
    verdict = classify_eyes([face(*CLOSED, area=BIG)])
    assert verdict.status == "candidate"
    assert verdict.note is None
    assert verdict.faces_considered == 1


def test_group_with_one_closed_face_goes_to_review_not_candidate():
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*CLOSED, area=BIG * 0.8)])
    assert verdict.status == "review"
    assert verdict.note == "group"
    assert verdict.faces_considered == 2
    assert verdict.score == pytest.approx(CLOSED[1])  # 등급을 정한 얼굴은 감긴 쪽


def test_group_downgrade_can_be_turned_off():
    keep = EyesThresholds(group_downgrades_candidate=False)
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*CLOSED, area=BIG * 0.8)], keep)
    assert verdict.status == "candidate"
    assert verdict.note is None


def test_small_background_face_is_ignored():
    # 뒷사람(면적 20%)은 비슷한 크기가 아니다 -> 눈을 감아도 보지 않는다
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*CLOSED, area=BIG * 0.2)])
    assert verdict.status == "normal"
    assert verdict.faces_considered == 1


def test_face_exactly_at_the_ratio_counts():
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*CLOSED, area=BIG * 0.5)])
    assert verdict.faces_considered == 2
    assert verdict.status == "review"


def test_group_where_everyone_is_open_is_normal():
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*OPEN, area=BIG * 0.9)])
    assert verdict.status == "normal"
    assert verdict.faces_considered == 2


def test_group_review_zone_stays_review_without_group_note():
    verdict = classify_eyes([face(*OPEN, area=BIG), face(*SQUINT, area=BIG * 0.9)])
    assert verdict.status == "review"
    assert verdict.note is None


def test_group_picks_the_most_closed_face_among_equal_status():
    verdict = classify_eyes([face(0.14, 0.16, area=BIG), face(0.13, 0.145, area=BIG)])
    assert verdict.score == pytest.approx(0.145)


def test_group_ignores_faces_without_eye_landmarks():
    verdict = classify_eyes([face(None, None, area=BIG), face(*SQUINT, area=BIG * 0.9)])
    assert verdict.status == "review"
    assert verdict.score == pytest.approx(SQUINT[1])


def test_group_with_no_scorable_face_is_unscorable():
    verdict = classify_eyes([face(None, None, area=BIG), face(None, None, area=BIG * 0.9)])
    assert verdict.status == "unscorable"
    assert verdict.faces_considered == 2


def test_group_small_eye_note_is_kept_when_it_decides_the_status():
    narrow = face(0.30, 0.30, area=BIG, eye_w=SMALL, image_w=IMG)
    verdict = classify_eyes([narrow, face(*OPEN, area=BIG * 0.9, eye_w=NORMAL, image_w=IMG)])
    assert verdict.status == "review"
    assert verdict.note == "small_eye"


def test_group_face_ratio_is_validated():
    with pytest.raises(ValueError):
        EyesThresholds(group_face_ratio=0.0)
    with pytest.raises(ValueError):
        EyesThresholds(group_face_ratio=1.5)
    assert EyesThresholds(group_face_ratio=1.0).group_face_ratio == 1.0


def test_verdict_reports_which_faces_were_considered_and_which_decided():
    faces = [face(*OPEN, area=BIG), face(*CLOSED, area=BIG * 0.8), face(*CLOSED, area=BIG * 0.1)]
    verdict = classify_eyes(faces)
    assert verdict.considered_indices == (0, 1)  # 셋째 얼굴은 너무 작아 제외
    assert verdict.deciding_index == 1  # 감긴 얼굴이 등급을 정했다


def test_verdict_for_single_face_points_at_it():
    verdict = classify_eyes([face(*OPEN, area=BIG)])
    assert verdict.considered_indices == (0,)
    assert verdict.deciding_index == 0


def test_verdict_without_faces_has_no_indices():
    verdict = classify_eyes([])
    assert verdict.considered_indices == () and verdict.deciding_index is None
