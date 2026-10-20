"""선명도 측정 (순수 수치 계산, macOS 의존 없음).

측정 방법은 "재블러 지표"(Crete 등, 2007)다. 이미지를 한 번 더 흐리게 만들었을 때 이웃 픽셀
사이의 밝기 변화가 얼마나 줄어드는지 본다.
- 선명한 이미지: 한 번 더 흐리게 하면 변화가 많이 줄어든다 -> 값이 작다
- 이미 흐린 이미지: 더 흐리게 해도 변화가 거의 안 줄어든다 -> 값이 1에 가깝다
값은 0~1이고 **클수록 흐리다**. 밝기나 대비 자체에는 크게 흔들리지 않아서, 라플라시안 분산
같은 방식보다 사진 사이에 비교하기 쉽다.

평탄한 영역(하늘, 매끈한 피부)은 변화가 거의 없어 값이 의미가 없으므로 None으로 돌려준다.
"""

from __future__ import annotations

import numpy as np

BLUR_KERNEL = 9  # 재블러에 쓰는 평균 필터 길이
MIN_GRADIENT = 1.0  # 이웃 픽셀 밝기 차이의 평균이 이보다 작으면 "평탄"해서 측정하지 않는다
MIN_SIDE = 24  # 이보다 작은 영역은 측정하지 않는다
GRID = (8, 6)  # 사진을 나누는 타일 수 (가로, 세로)


def mean_gradient(gray: np.ndarray) -> float:
    """이웃 픽셀 밝기 차이의 평균 (가로·세로 합). 영역에 질감이 얼마나 있는지."""
    g = gray.astype(np.float64)
    dx = np.abs(np.diff(g, axis=1)).mean() if g.shape[1] > 1 else 0.0
    dy = np.abs(np.diff(g, axis=0)).mean() if g.shape[0] > 1 else 0.0
    return float(dx + dy)


# 변화를 재는 방향: (가로 이동, 세로 이동). 가로와 세로만 쓴다.
# 대각선(1, 1), (1, -1)까지 넣어 시험했지만 정상 사진에서도 값이 높게 나와
# (정상 컷의 중앙값이 0.6~0.8)
# 정상과 흐린 사진이 겹쳤다 (docs/sharpness-experiment.md). 실험용으로 바꿔 쓸 수 있다.
DIRECTIONS = ((1, 0), (0, 1))
DIAGONAL_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def _line_blur(g: np.ndarray, dx: int, dy: int, size: int) -> np.ndarray:
    """(dx, dy) 방향의 선을 따라 size개를 평균 낸다 (가장자리는 가장자리 값으로 채움)."""
    r = size // 2
    h, w = g.shape
    padded = np.pad(g, r, mode="edge")
    acc = np.zeros_like(g)
    for k in range(-r, r + 1):
        acc += padded[r + k * dy:r + k * dy + h, r + k * dx:r + k * dx + w]
    return acc / size


def _step_diff(a: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """(dx, dy) 방향으로 이웃한 픽셀 사이의 밝기 차이."""
    h, w = a.shape
    if dx >= 0:
        x0, x1 = 0, w - dx
        x2, x3 = dx, w
    else:
        x0, x1 = -dx, w
        x2, x3 = 0, w + dx
    return a[dy:h, x2:x3][:h - dy, :x3 - x2] - a[0:h - dy, x0:x1][:, :x1 - x0]


def blur_metric(
    gray: np.ndarray, directions: tuple[tuple[int, int], ...] = DIRECTIONS
) -> float | None:
    """흐림 정도 0~1 (클수록 흐리다). 작거나 평탄한 영역이면 None.

    가로와 세로 방향에서 재블러 지표를 재고, **더 흐린 방향**의 값을 쓴다.
    모션 블러는 번진 방향으로만 흐려지므로 한 방향만 봐서는 놓칠 수 있다.
    """
    h, w = gray.shape
    if h < MIN_SIDE or w < MIN_SIDE or mean_gradient(gray) < MIN_GRADIENT:
        return None
    g = gray.astype(np.float64)
    scores = []
    for dx, dy in directions:
        blurred = _line_blur(g, dx, dy, BLUR_KERNEL)
        d_orig = np.abs(_step_diff(g, dx, dy))
        d_blur = np.abs(_step_diff(blurred, dx, dy))
        total = d_orig.sum()
        if total <= 0:
            return None
        lost = np.maximum(0.0, d_orig - d_blur).sum()  # 다시 흐리게 했을 때 사라진 변화
        scores.append((total - lost) / total)
    return float(max(scores))


def tile_blur_metrics(gray: np.ndarray, grid: tuple[int, int] = GRID) -> list[float]:
    """사진을 격자로 나눠 타일마다 흐림 정도를 잰다. 평탄한 타일은 뺀다."""
    h, w = gray.shape
    gx, gy = grid
    out = []
    for j in range(gy):
        for i in range(gx):
            tile = gray[j * h // gy:(j + 1) * h // gy, i * w // gx:(i + 1) * w // gx]
            m = blur_metric(tile)
            if m is not None:
                out.append(m)
    return out


def inner_region(
    gray: np.ndarray, bbox: tuple[float, float, float, float], margin: float = 0.15
) -> np.ndarray | None:
    """얼굴 상자(이미지 대비 비율, 원점 왼쪽 아래)의 안쪽 영역. 너무 작으면 None."""
    h, w = gray.shape
    x, y, bw, bh = bbox
    x0, x1 = int(round((x + bw * margin) * w)), int(round((x + bw * (1 - margin)) * w))
    y0 = int(round((1 - y - bh * (1 - margin)) * h))
    y1 = int(round((1 - y - bh * margin) * h))
    x0, x1, y0, y1 = max(0, x0), min(w, x1), max(0, y0), min(h, y1)
    if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
        return None
    return gray[y0:y1, x0:x1]


BEST_QUANTILE = 0.10  # "가장 선명한 쪽"으로 보는 타일 흐림의 분위


def best_tile_blur(gray: np.ndarray) -> float | None:
    """사진에서 가장 선명한 타일 쪽의 흐림 (타일 흐림의 하위 10% 지점). 유효 타일이 없으면 None.

    값이 높으면 사진 어디에도 선명한 곳이 없다는 뜻이다.
    """
    tiles = sorted(tile_blur_metrics(gray))
    if not tiles:
        return None
    return tiles[int(BEST_QUANTILE * len(tiles))]
