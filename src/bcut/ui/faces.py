"""훑기 모드에서 크게 볼 때 쓰는 얼굴 박스와 눈 위치 (spec FR-24, plan 2-3).

판정 때 계산한 얼굴 위치는 결과에 저장되지 않는다. 판정 코드(`detect/`, `scan.py`)는 고치지 않고,
크게 볼 때 **같은 얼굴 인식을 한 번 더 불러서** 위치만 받는다. 사진은 화면에 보이는 방향으로
돌려서 인식하므로, 돌려준 좌표는 화면의 사진에 그대로 맞는다.

돌려주는 좌표는 모두 사진 크기에 대한 비율(0~1)이고 원점은 왼쪽 위다 (화면에서 그대로 쓰도록
Vision의 왼쪽 아래 원점에서 바꿨다). 눈 위치는 윤곽점이 있는 눈만 준다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bcut.detect.types import Face


def _top_left_box(x: float, y: float, w: float, h: float) -> list[float]:
    """왼쪽 아래 원점의 (x, y, w, h)를 왼쪽 위 원점으로 바꾼다."""
    return [round(x, 5), round(1.0 - (y + h), 5), round(w, 5), round(h, 5)]


def _eye_box(points: tuple[tuple[float, float], ...], size: tuple[int, int]) -> list[float] | None:
    if len(points) < 2:
        return None
    width, height = size
    xs = [p[0] / width for p in points]
    ys = [p[1] / height for p in points]
    return _top_left_box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def faces_payload(faces: list[Face], size: tuple[int, int]) -> dict:
    """화면이 쓰는 모양. 얼굴은 큰 순서."""
    out = []
    for f in sorted(faces, key=lambda x: x.face_area, reverse=True):
        eyes = [b for b in (_eye_box(f.left.points, size), _eye_box(f.right.points, size)) if b]
        out.append({"box": _top_left_box(*f.bbox), "area": round(f.face_area, 5), "eyes": eyes})
    return {"w": size[0], "h": size[1], "faces": out}


def face_info(path: Path, flip: int, *, load: Callable | None = None,
              detect: Callable | None = None, rotate: Callable | None = None) -> dict:
    """사진 한 장의 얼굴 정보. load, detect, rotate는 시험에서 바꿔 끼울 수 있다."""
    if rotate is None:
        from bcut.ui.photos import rotate_image as rotate
    if load is None:
        from bcut.imageio import read_embedded_jpeg as load
    if detect is None:
        from bcut.detect.vision_face import detect_faces as detect
    image = rotate(load(path).image, flip)
    return faces_payload(detect(image), image.size)
