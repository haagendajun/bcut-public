"""얼굴·눈 자료형. Vision에 의존하지 않아 어디서든 테스트에서 만들 수 있다."""

from __future__ import annotations

from dataclasses import dataclass

from bcut.detect.eyes import EyeOpenness


@dataclass(frozen=True)
class Eye:
    openness: EyeOpenness | None
    pupil: tuple[float, float] | None  # 입력 이미지 픽셀, 원점은 왼쪽 아래
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Face:
    face_width_px: float  # 입력 이미지 기준
    face_area: float  # 이미지 대비 비율 (0~1)
    yaw_deg: float | None
    roll_deg: float | None
    confidence: float
    left: Eye
    right: Eye
    # 이미지 대비 비율 (x, y, 폭, 높이). 원점은 왼쪽 아래 (Vision 규약)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # 분석에 쓴 입력 이미지의 폭(px). 눈 폭을 입력 크기와 무관한 비율로 바꿀 때 쓴다. 0이면 모름
    image_width_px: int = 0

    @property
    def ratios(self) -> list[float]:
        return [e.openness.ratio for e in (self.left, self.right) if e.openness]
