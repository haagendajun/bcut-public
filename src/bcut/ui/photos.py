"""사진을 화면에 보여 줄 때 쓰는 함수들 (server.py에서 나눴다):
회전 정보 읽기, 똑바로 세우기, 큰 사진 만들기.

CR3 안의 내장 JPEG는 카메라 방향대로 눕혀 저장되어 있어서, rawpy가 알려 주는 회전 값(flip)대로
돌려야 세로 사진이 똑바로 선다. 사진 파일은 읽기만 한다.
"""

from __future__ import annotations

import io
from pathlib import Path


def default_orientation(path: Path) -> int:
    """카메라가 기록한 회전 정보. rawpy flip 값(0 없음, 3 180도,
    5 반시계 90도, 6 시계 90도). 못 읽으면 0."""
    try:
        import rawpy

        with rawpy.imread(str(path)) as raw:
            return int(raw.sizes.flip)
    except Exception:  # noqa: BLE001  회전을 못 읽어도 사진은 보여 준다
        return 0


def rotate_image(img, flip: int):
    """flip 값대로 돌려 똑바로 세운다 (세로 사진이 눕지 않게). 실제 사진으로 방향 확인함."""
    if flip == 3:
        return img.rotate(180, expand=True)
    if flip == 5:
        return img.rotate(90, expand=True)
    if flip == 6:
        return img.rotate(-90, expand=True)
    return img


def rotate_jpeg(data: bytes, flip: int) -> bytes:
    if flip not in (3, 5, 6):
        return data
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        out = io.BytesIO()
        rotate_image(im.convert("RGB"), flip).save(out, "JPEG", quality=80)
    return out.getvalue()


def default_read_photo(path: Path, size: str) -> bytes:
    from bcut.imageio import read_embedded_jpeg

    width = 2048
    if size == "full":
        width = read_embedded_jpeg(path).full_width
    img = rotate_image(read_embedded_jpeg(path, width=width).image, default_orientation(path))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()
