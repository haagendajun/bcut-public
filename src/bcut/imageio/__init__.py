"""사진 읽기. 기본 입력은 CR3 내장 원본 JPEG (docs/image-reading-spike.md)."""

from bcut.imageio.embedded import LoadedImage, read_embedded_jpeg

__all__ = ["LoadedImage", "read_embedded_jpeg"]
