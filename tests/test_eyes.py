import math

import pytest

from bcut.detect.eyes import eye_openness


def ellipse(width: float, height: float, n: int = 6, angle_deg: float = 0.0, center=(100.0, 50.0)):
    """폭 width, 높이 height인 타원 위의 점 n개 (눈 윤곽 모양 흉내)."""
    a = math.radians(angle_deg)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = width / 2 * math.cos(t), height / 2 * math.sin(t)
        pts.append((center[0] + x * math.cos(a) - y * math.sin(a),
                    center[1] + x * math.sin(a) + y * math.cos(a)))
    return pts


def test_open_eye_has_higher_ratio_than_closed_eye():
    open_eye = eye_openness(ellipse(30, 10, n=8))
    closed_eye = eye_openness(ellipse(30, 2, n=8))
    assert open_eye and closed_eye
    assert open_eye.ratio > closed_eye.ratio
    assert open_eye.ratio == pytest.approx(10 / 30, abs=0.03)


def test_ratio_is_stable_when_face_is_rolled():
    base = eye_openness(ellipse(30, 10, n=8))
    rolled = eye_openness(ellipse(30, 10, n=8, angle_deg=35))
    assert base and rolled
    assert rolled.ratio == pytest.approx(base.ratio, abs=0.02)


def test_width_is_reported():
    eye = eye_openness(ellipse(40, 8, n=8))
    assert eye and eye.width_px == pytest.approx(40, abs=1)


def test_too_few_points_gives_none():
    assert eye_openness([(0, 0), (1, 1), (2, 2)]) is None


def test_degenerate_points_give_none():
    assert eye_openness([(5.0, 5.0)] * 6) is None
