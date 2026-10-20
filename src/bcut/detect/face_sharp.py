"""얼굴 안쪽의 선명도를 풀 해상도에서 잰다.

분석 입력(폭 2048px)에서는 가벼운 흔들림이 거의 안 보인다 (원본의 100% 확대에서 보이는 흔들림이
입력에서는 몇 픽셀 번짐이다). 그래서 얼굴 주변만 풀 해상도로 잘라 재 본다.
얼굴 위치는 분석 입력에서 찾고, 풀 해상도에서는 그 위치를 잘라 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PIL import Image

from bcut.detect.exposure import to_gray
from bcut.detect.sharpness import blur_metric, inner_region
from bcut.detect.types import Face
from bcut.score.sharpness import FaceBlur

PAD = 0.4  # 얼굴 상자 크기의 이 비율만큼 바깥까지 자른다
MAX_FACES = 3  # 풀 해상도로 재는 얼굴 수 (큰 순서). 시간을 줄이려는 상한이다


def crop_face(full: Image.Image, bbox: tuple[float, float, float, float]):
    """풀 해상도 이미지에서 얼굴 주변을 자르고, 잘라낸 이미지 안의 얼굴 상자(비율)를 돌려준다."""
    W, H = full.size
    x, y, bw, bh = bbox
    fx0, fx1 = x * W, (x + bw) * W
    fy0, fy1 = (1 - y - bh) * H, (1 - y) * H
    px, py = (fx1 - fx0) * PAD, (fy1 - fy0) * PAD
    cx0, cx1 = max(0, int(fx0 - px)), min(W, int(fx1 + px))
    cy0, cy1 = max(0, int(fy0 - py)), min(H, int(fy1 + py))
    cw, ch = cx1 - cx0, cy1 - cy0
    nb = ((fx0 - cx0) / cw, 1 - (fy1 - cy0) / ch, (fx1 - fx0) / cw, (fy1 - fy0) / ch)
    return full.crop((cx0, cy0, cx1, cy1)), nb


def measure_face_blurs(
    faces: Sequence[Face], load_full: Callable[[], Image.Image]
) -> list[FaceBlur]:
    """큰 얼굴부터 MAX_FACES개의 흐림을 잰다. 풀 해상도 디코딩은 얼굴이 있을 때만, 한 번만 한다."""
    if not faces:
        return []
    full = load_full()
    out = []
    for f in sorted(faces, key=lambda f: -f.face_area)[:MAX_FACES]:
        crop, nb = crop_face(full, f.bbox)
        region = inner_region(to_gray(crop), nb)
        if region is None:
            out.append(FaceBlur(area=f.face_area, blur=None, px=0))
        else:
            blur = blur_metric(region)
            out.append(FaceBlur(area=f.face_area, blur=blur, px=int(region.shape[1])))
    return out
