"""폴더 스캔: 사진마다 눈 감김, 노출, 흔들림·초점을 판정하고 리포트용 썸네일을 만든다.

사진 파일은 **읽기만** 한다. 이 모듈은 행사 폴더에 아무것도 쓰지 않는다 (제약 C3, 읽기 전용).
손상된 파일이 있어도 전체를 멈추지 않고, 그 컷을 "사람이 확인"(note `read_error`)으로 보낸다.
네트워크를 쓰지 않는다 (제약 C1).

한 사진에 여러 사유가 함께 걸릴 수 있다 (눈 감김, 노출, 흔들림, 초점).
사진의 등급은 사유별 등급 중 가장 높은 것으로 정하고, 걸린 사유는 `reasons`에 모두 남긴다.
"""

from __future__ import annotations

import io
import os
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PIL import Image, ImageDraw

from bcut.detect.exposure import to_gray
from bcut.detect.face_sharp import measure_face_blurs
from bcut.detect.sharpness import best_tile_blur
from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.score.exposure import (
    ExposureThresholds,
    classify_exposure,
    exposure_severity,
    status_for_flag,
)
from bcut.score.eyes import EyesThresholds, classify_eyes
from bcut.score.sharpness import (
    SharpnessThresholds,
    classify_sharpness,
    sharpness_severity,
)

PHOTO_SUFFIXES = (".cr3",)
ALL_STATUSES = frozenset({"candidate", "review", "normal", "no_face", "unscorable"})
FLAGGED_STATUSES = frozenset({"candidate", "review", "unscorable"})
READ_ERROR = "read_error"

EYES_CLOSED = "eyes_closed"
EXPOSURE = "exposure"
BLUR = "blur"
OUT_OF_FOCUS = "out_of_focus"
SHARPNESS_REASONS = (BLUR, OUT_OF_FOCUS)
ALL_REASONS = (EYES_CLOSED, EXPOSURE, BLUR, OUT_OF_FOCUS)

# 썸네일의 얼굴 상자 색 (사진의 등급별)
_BOX_COLORS = {
    "candidate": (226, 75, 74),
    "review": (239, 159, 39),
    "normal": (99, 153, 34),
}


@dataclass(frozen=True)
class PhotoResult:
    file: str
    status: str  # 사진의 등급: candidate | review | normal | no_face | unscorable
    score: float | None  # 눈 열림 비율 (낮을수록 감김). 정렬에 쓴다
    note: str | None  # 눈 감김 쪽 참고: small_eye | group | read_error
    face_count: int
    faces_considered: int
    eye_width_frac: float | None
    thumbnail: bytes | None  # JPEG. 만들지 않았으면 None
    error: str | None = None
    seconds: float = 0.0
    # 사유별 결과 (모두 기본값이 있어 눈 감김만 쓰던 코드와 호환된다)
    eyes_status: str | None = None  # 눈 감김만의 등급. None이면 status와 같은 것으로 본다
    exposure_kind: str | None = None  # over_face | over_global | under. 걸리지 않았으면 None
    exposure_p99: float | None = None  # 사진 상위 1% 밝기
    exposure_face_hi: float | None = None  # 얼굴 날아간 비율
    exposure_global_hi: float | None = None  # 사진 전체 날아간 비율
    exposure_severity: float | None = None  # 0~1, 노출 이상이 걸렸을 때만
    sharpness_kind: str | None = None  # blur | out_of_focus. 걸리지 않았으면 None
    sharpness_best: float | None = None  # 가장 선명한 타일 쪽 흐림 (클수록 흐림)
    sharpness_face: float | None = None  # 판정에 쓴 얼굴의 흐림 (풀 해상도)
    sharpness_severity: float | None = None  # 0~1, 흐림이 걸렸을 때만
    confidence: float | None = None  # 0~1 확신도(정렬용 점수). 걸리지 않았으면 None

    @property
    def reasons(self) -> tuple[str, ...]:
        """이 사진을 사람 눈앞에 올린 사유들. 읽기 실패는 사유가 아니라 note로 남긴다."""
        out = []
        eyes = self.eyes_status if self.eyes_status is not None else self.status
        if eyes in ("candidate", "review") and self.note != READ_ERROR:
            out.append(EYES_CLOSED)
        if self.exposure_kind:
            out.append(EXPOSURE)
        if self.sharpness_kind in SHARPNESS_REASONS:
            out.append(self.sharpness_kind)
        return tuple(out)


def eyes_strength(score: float | None, status: str, t: EyesThresholds) -> float:
    """눈 감김이 얼마나 분명한가 0~1. candidate는 0에 가까울수록, review는 경계에서 멀수록 높다."""
    if score is None:
        return 0.0
    if status == "candidate":
        return min(1.0, max(0.0, 1 - score / t.candidate_max))
    if t.review_max <= t.candidate_max:
        return 0.0
    return min(1.0, max(0.0, 1 - (score - t.candidate_max) / (t.review_max - t.candidate_max)))


def confidence_of(parts: Sequence[tuple[str, float]]) -> float | None:
    """사유별 (등급, 강도 0~1)에서 사진의 확신도를 정한다. 걸린 사유가 없으면 None.

    candidate 등급 사유는 0.5~1.0, review 등급 사유는 0~0.5로 옮긴 뒤 가장 큰 값을 쓴다.
    검증된 사유(눈 감김)가 검증 안 된 사유보다 항상 위에 오고, 확률이 아니라 **정렬용 점수**다.
    """
    vals = [(0.5 + 0.5 * s) if tier == "candidate" else 0.5 * s for tier, s in parts]
    return max(vals) if vals else None


def combine_status(
    eyes_status: str, exposure_flagged: bool, exposure_tier: str = "review",
    sharpness_flagged: bool = False, sharpness_tier: str = "review",
) -> str:
    """사유별 등급을 합쳐 사진의 등급을 정한다.

    candidate가 하나라도 있으면 candidate, 아니면 review가 하나라도 있으면 review.
    둘 다 아니면 눈 감김 판정의 등급(normal, no_face, unscorable)을 그대로 쓴다.
    노출과 흔들림·초점은 v1에서 review 전용이라 이것만으로는 candidate가 되지 않는다.
    """
    statuses = (eyes_status, status_for_flag(exposure_flagged, exposure_tier),
                status_for_flag(sharpness_flagged, sharpness_tier))
    if "candidate" in statuses:
        return "candidate"
    if "review" in statuses:
        return "review"
    return eyes_status


def list_photos(folder: Path) -> list[Path]:
    """폴더 바로 아래의 사진 파일을 이름순으로 돌려준다 (하위 폴더, 숨김 파일은 건너뛴다)."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in PHOTO_SUFFIXES
    )


def _thumbnail(image: Image.Image, faces, considered: Sequence[int], deciding: int | None,
               status: str, width: int) -> bytes:
    thumb = image.resize((width, round(image.height * width / image.width)), Image.BILINEAR)
    color = _BOX_COLORS.get(status)
    if color is not None and faces:
        draw = ImageDraw.Draw(thumb)
        w, h = thumb.size
        for i in considered:
            x, y, bw, bh = faces[i].bbox  # 비율, 원점은 왼쪽 아래
            box = (x * w, (1 - y - bh) * h, (x + bw) * w, (1 - y) * h)
            draw.rectangle(box, outline=color, width=3 if i == deciding else 1)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=72, optimize=True)
    return buf.getvalue()


def analyze_photo(
    path: str | Path,
    thumb_width: int = 320,
    thumb_statuses: Collection[str] = ALL_STATUSES,
    thresholds: EyesThresholds | None = None,
    exposure_thresholds: ExposureThresholds | None = None,
    exposure_tier: str = "review",
    sharpness_thresholds: SharpnessThresholds | None = None,
    sharpness_tiers: Mapping[str, str] | None = None,
    eyes_tier: str = "candidate",
) -> PhotoResult:
    """사진 한 장을 읽어 판정한다. 실패해도 예외를 올리지 않고 read_error로 돌려준다."""
    path = Path(path)
    started = time.perf_counter()
    try:
        loaded = read_embedded_jpeg(path)
        faces = detect_faces(loaded.image)
        eyes = classify_eyes(faces, thresholds)
        eyes_status = eyes.status
        if eyes_status == "candidate" and eyes_tier == "review":
            eyes_status = "review"  # 설정으로 눈 감김을 review 전용으로 낮춘 경우
        gray = to_gray(loaded.image)
        exposure = classify_exposure(gray, faces, exposure_thresholds)
        face_blurs = measure_face_blurs(
            faces, lambda: read_embedded_jpeg(path, width=loaded.full_width).image)
        sharp = classify_sharpness(best_tile_blur(gray), face_blurs, sharpness_thresholds)
        sharp_tier = (sharpness_tiers or {}).get(sharp.kind, "review")
        parts = []
        if eyes_status in ("candidate", "review"):
            strength = eyes_strength(eyes.score, eyes_status, thresholds or EyesThresholds())
            parts.append((eyes_status, strength))
        if exposure.flagged:
            parts.append((exposure_tier, exposure_severity(exposure) or 0.0))
        if sharp.flagged:
            parts.append((sharp_tier, sharpness_severity(sharp) or 0.0))
        status = combine_status(eyes_status, exposure.flagged, exposure_tier,
                                sharp.flagged, sharp_tier)
        thumb = None
        if thumb_width > 0 and status in thumb_statuses:
            thumb = _thumbnail(loaded.image, faces, eyes.considered_indices, eyes.deciding_index,
                               status, thumb_width)
        return PhotoResult(
            file=path.name, status=status, score=eyes.score, note=eyes.note,
            face_count=eyes.face_count, faces_considered=eyes.faces_considered,
            eye_width_frac=eyes.eye_width_frac, thumbnail=thumb,
            seconds=time.perf_counter() - started,
            eyes_status=eyes_status, exposure_kind=exposure.kind, exposure_p99=exposure.global_p99,
            exposure_face_hi=exposure.face_hi, exposure_global_hi=exposure.global_hi,
            exposure_severity=exposure_severity(exposure),
            sharpness_kind=sharp.kind, sharpness_best=sharp.best, sharpness_face=sharp.face_blur,
            sharpness_severity=sharpness_severity(sharp), confidence=confidence_of(parts),
        )
    except Exception as exc:  # noqa: BLE001  손상 파일 하나가 전체 스캔을 멈추면 안 된다
        return PhotoResult(
            file=path.name, status="review", score=None, note=READ_ERROR, face_count=0,
            faces_considered=0, eye_width_frac=None, thumbnail=None,
            error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - started,
            eyes_status="review", confidence=0.0,
        )


def scan_folder(
    folder: Path,
    *,
    thresholds: EyesThresholds | None = None,
    exposure_thresholds: ExposureThresholds | None = None,
    exposure_tier: str = "review",
    sharpness_thresholds: SharpnessThresholds | None = None,
    sharpness_tiers: Mapping[str, str] | None = None,
    eyes_tier: str = "candidate",
    thumb_width: int = 320,
    thumb_statuses: Collection[str] = ALL_STATUSES,
    workers: int | None = None,
    analyze: Callable[..., PhotoResult] = analyze_photo,
    progress: Callable[[int, int], None] | None = None,
) -> list[PhotoResult]:
    """폴더의 사진을 모두 판정한다. 결과는 파일 이름순. 행사 폴더에는 아무것도 쓰지 않는다."""
    photos = list_photos(folder)
    total = len(photos)
    if workers is None:
        workers = min(6, os.cpu_count() or 1)
    job = partial(analyze, thumb_width=thumb_width, thumb_statuses=thumb_statuses,
                  thresholds=thresholds, exposure_thresholds=exposure_thresholds,
                  exposure_tier=exposure_tier, sharpness_thresholds=sharpness_thresholds,
                  sharpness_tiers=sharpness_tiers, eyes_tier=eyes_tier)

    results: list[PhotoResult] = []

    def collect(it):
        for r in it:
            results.append(r)
            if progress:
                progress(len(results), total)

    if workers <= 1 or total < 4:
        collect(job(p) for p in photos)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            collect(pool.map(job, photos, chunksize=4))
    return results


def count_by_status(results: Sequence[PhotoResult]) -> dict[str, int]:
    counts = dict.fromkeys(("candidate", "review", "normal", "no_face", "unscorable"), 0)
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def count_by_reason(results: Sequence[PhotoResult]) -> dict[str, int]:
    """사유별 장수. both는 사유가 둘 이상 함께 걸린 사진 수다 (각 사유 수에도 포함된다)."""
    counts = {**dict.fromkeys(ALL_REASONS, 0), "both": 0}
    for r in results:
        reasons = r.reasons
        for reason in ALL_REASONS:
            if reason in reasons:
                counts[reason] += 1
        if len(reasons) >= 2:
            counts["both"] += 1
    return counts
