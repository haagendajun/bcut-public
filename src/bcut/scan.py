"""폴더 스캔: 사진마다 눈 감김과 노출을 판정하고 리포트용 썸네일을 만든다.

사진 파일은 **읽기만** 한다. 이 모듈은 행사 폴더에 아무것도 쓰지 않는다 (제약 C3, 읽기 전용).
손상된 파일이 있어도 전체를 멈추지 않고, 그 컷을 "사람이 확인"(note `read_error`)으로 보낸다.
네트워크를 쓰지 않는다 (제약 C1).

한 사진에 여러 사유가 함께 걸릴 수 있다 (눈 감김과 노출). 사진의 등급은 사유별 등급 중 가장
높은 것으로 정하고, 걸린 사유는 `reasons`에 모두 남긴다.
"""

from __future__ import annotations

import io
import os
import time
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PIL import Image, ImageDraw

from bcut.detect.exposure import to_gray
from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.score.exposure import (
    ExposureThresholds,
    classify_exposure,
    exposure_severity,
    status_for_flag,
)
from bcut.score.eyes import EyesThresholds, classify_eyes

PHOTO_SUFFIXES = (".cr3",)
ALL_STATUSES = frozenset({"candidate", "review", "normal", "no_face", "unscorable"})
FLAGGED_STATUSES = frozenset({"candidate", "review", "unscorable"})
READ_ERROR = "read_error"

EYES_CLOSED = "eyes_closed"
EXPOSURE = "exposure"

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

    @property
    def reasons(self) -> tuple[str, ...]:
        """이 사진을 사람 눈앞에 올린 사유들. 읽기 실패는 사유가 아니라 note로 남긴다."""
        out = []
        eyes = self.eyes_status if self.eyes_status is not None else self.status
        if eyes in ("candidate", "review") and self.note != READ_ERROR:
            out.append(EYES_CLOSED)
        if self.exposure_kind:
            out.append(EXPOSURE)
        return tuple(out)


def combine_status(eyes_status: str, exposure_flagged: bool, exposure_tier: str = "review") -> str:
    """사유별 등급을 합쳐 사진의 등급을 정한다.

    candidate가 하나라도 있으면 candidate, 아니면 review가 하나라도 있으면 review.
    둘 다 아니면 눈 감김 판정의 등급(normal, no_face, unscorable)을 그대로 쓴다.
    노출은 v1에서 review 전용이라 노출만으로는 candidate가 되지 않는다.
    """
    statuses = (eyes_status, status_for_flag(exposure_flagged, exposure_tier))
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
) -> PhotoResult:
    """사진 한 장을 읽어 판정한다. 실패해도 예외를 올리지 않고 read_error로 돌려준다."""
    path = Path(path)
    started = time.perf_counter()
    try:
        loaded = read_embedded_jpeg(path)
        faces = detect_faces(loaded.image)
        eyes = classify_eyes(faces, thresholds)
        exposure = classify_exposure(to_gray(loaded.image), faces, exposure_thresholds)
        status = combine_status(eyes.status, exposure.flagged, exposure_tier)
        thumb = None
        if thumb_width > 0 and status in thumb_statuses:
            thumb = _thumbnail(loaded.image, faces, eyes.considered_indices, eyes.deciding_index,
                               status, thumb_width)
        return PhotoResult(
            file=path.name, status=status, score=eyes.score, note=eyes.note,
            face_count=eyes.face_count, faces_considered=eyes.faces_considered,
            eye_width_frac=eyes.eye_width_frac, thumbnail=thumb,
            seconds=time.perf_counter() - started,
            eyes_status=eyes.status, exposure_kind=exposure.kind, exposure_p99=exposure.global_p99,
            exposure_face_hi=exposure.face_hi, exposure_global_hi=exposure.global_hi,
            exposure_severity=exposure_severity(exposure),
        )
    except Exception as exc:  # noqa: BLE001  손상 파일 하나가 전체 스캔을 멈추면 안 된다
        return PhotoResult(
            file=path.name, status="review", score=None, note=READ_ERROR, face_count=0,
            faces_considered=0, eye_width_frac=None, thumbnail=None,
            error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - started,
            eyes_status="review",
        )


def scan_folder(
    folder: Path,
    *,
    thresholds: EyesThresholds | None = None,
    exposure_thresholds: ExposureThresholds | None = None,
    exposure_tier: str = "review",
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
                  exposure_tier=exposure_tier)

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
    """사유별 장수. both는 두 사유가 함께 걸린 사진 수다 (각 사유 수에도 포함된다)."""
    counts = {EYES_CLOSED: 0, EXPOSURE: 0, "both": 0}
    for r in results:
        reasons = r.reasons
        for reason in (EYES_CLOSED, EXPOSURE):
            if reason in reasons:
                counts[reason] += 1
        if len(reasons) == 2:
            counts["both"] += 1
    return counts
