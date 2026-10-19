"""CR3 내장 원본 크기 JPEG를 읽는다 (T1.2 결론).

1장당 약 45 ms (draft 2048). 사진 파일은 읽기만 한다.
내장 JPEG가 없으면 EmbeddedJpegMissing을 올린다 (폴백 경로는 이후 작업에서 추가).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import rawpy
from PIL import Image

DEFAULT_WIDTH = 2048


class EmbeddedJpegMissing(RuntimeError):
    """CR3 안에서 JPEG 미리보기를 꺼내지 못했다."""


@dataclass(frozen=True)
class LoadedImage:
    image: Image.Image  # RGB
    full_width: int  # 내장 JPEG 원래 폭 (좌표를 풀 해상도로 환산할 때 쓴다)
    full_height: int

    @property
    def scale_to_full(self) -> float:
        return self.full_width / self.image.width


def read_embedded_jpeg(path: Path, width: int = DEFAULT_WIDTH) -> LoadedImage:
    """내장 JPEG를 DCT 축소로 빠르게 읽는다. 결과 폭은 width 이상 중 가장 작은 1/n."""
    try:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
    except rawpy.LibRawError as exc:
        raise EmbeddedJpegMissing(f"{path.name}: {exc}") from exc
    if thumb.format != rawpy.ThumbFormat.JPEG:
        raise EmbeddedJpegMissing(f"{path.name}: 내장 미리보기가 JPEG가 아니다")

    im = Image.open(io.BytesIO(thumb.data))
    full_w, full_h = im.size
    im.draft("RGB", (width, round(width * full_h / full_w)))
    return LoadedImage(image=im.convert("RGB"), full_width=full_w, full_height=full_h)
