"""얼굴 박스·눈 위치 변환 시험 (spec FR-24): 왼쪽 아래 원점 -> 화면용 왼쪽 위 원점 비율."""

from pathlib import Path

import pytest
from PIL import Image

from bcut.detect.types import Eye, Face
from bcut.ui.faces import face_info, faces_payload


def eye(points):
    return Eye(openness=None, pupil=None, points=tuple(points))


def face(bbox, left=(), right=(), area=None):
    return Face(face_width_px=100, face_area=area if area is not None else bbox[2] * bbox[3],
                yaw_deg=None, roll_deg=None, confidence=0.9, left=eye(left), right=eye(right), bbox=bbox)


def test_box_origin_moves_from_bottom_left_to_top_left():
    out = faces_payload([face((0.1, 0.2, 0.3, 0.4))], (1000, 500))
    assert out["w"] == 1000 and out["h"] == 500
    # 아래에서 0.2~0.6 구간 -> 위에서 0.4~0.8: 위쪽 가장자리는 1 - (0.2 + 0.4) = 0.4
    assert out["faces"][0]["box"] == [0.1, 0.4, 0.3, 0.4]


def test_eye_points_become_a_box_in_picture_ratios():
    left = [(100, 400), (140, 410), (180, 400), (140, 390)]  # 사진 1000x500, 아래가 0
    out = faces_payload([face((0.0, 0.0, 1.0, 1.0), left=left)], (1000, 500))
    (box,) = out["faces"][0]["eyes"]
    assert box == [0.1, 0.18, 0.08, 0.04]  # x 100~180 -> 0.1, 폭 0.08 / y 390~410 -> 위에서 0.18, 높이 0.04


def test_eyes_without_outline_points_are_left_out_and_faces_sort_by_size():
    small = face((0.0, 0.0, 0.1, 0.1), left=[(1, 1)])  # 점이 모자라서 눈 위치 없음
    big = face((0.2, 0.2, 0.5, 0.5), left=[(300, 200), (340, 210), (380, 200)], right=[(500, 200), (540, 205)])
    out = faces_payload([small, big], (1000, 1000))
    assert [f["area"] for f in out["faces"]] == [0.25, 0.01]  # 큰 얼굴이 먼저
    assert len(out["faces"][0]["eyes"]) == 2 and out["faces"][1]["eyes"] == []


def test_no_face_gives_an_empty_list():
    assert faces_payload([], (800, 600)) == {"w": 800, "h": 600, "faces": []}


def test_face_info_rotates_before_detecting_so_boxes_match_the_screen():
    seen = {}

    def load(path):
        class Loaded:
            image = Image.new("RGB", (8, 4))
        return Loaded()

    def detect(image):
        seen["size"] = image.size
        return [face((0.25, 0.25, 0.5, 0.5))]

    def rotate(image, flip):
        seen["flip"] = flip
        return image.rotate(90, expand=True)  # 가로 8x4 -> 세로 4x8

    out = face_info(Path("x.CR3"), 5, load=load, detect=detect, rotate=rotate)
    assert seen == {"flip": 5, "size": (4, 8)} and (out["w"], out["h"]) == (4, 8)


@pytest.mark.parametrize("flip", [0, 3, 5, 6])
def test_default_rotate_keeps_picture_size_for_every_flip(flip):
    from bcut.ui.photos import rotate_image
    out = rotate_image(Image.new("RGB", (8, 4)), flip)
    assert out.size == ((4, 8) if flip in (5, 6) else (8, 4))
