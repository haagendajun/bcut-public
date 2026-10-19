"""macOS Vision으로 얼굴과 눈 랜드마크를 찾는다 (T1.3 결론).

주의: Vision이 돌려주는 좌표 목록(`pointsInImageOfSize_`)은 길이를 모르는 포인터다.
반드시 `pointCount()` 만큼만 읽는다. 개수 없이 순회하면 프로세스가 SIGBUS로 죽는다.
"""

from __future__ import annotations

import io
import math

import Foundation
import Quartz
import Vision
from PIL import Image

from bcut.detect.eyes import eye_openness
from bcut.detect.types import Eye, Face

__all__ = ["Eye", "Face", "detect_faces"]


def _to_cgimage(image: Image.Image):
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=92)
    data = buf.getvalue()
    nsdata = Foundation.NSData.dataWithBytes_length_(data, len(data))
    source = Quartz.CGImageSourceCreateWithData(nsdata, None)
    return Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)


def _region_points(region, size: tuple[int, int]) -> tuple[tuple[float, float], ...]:
    if region is None:
        return ()
    n = int(region.pointCount())
    raw = region.pointsInImageOfSize_(size)  # 길이를 모르는 포인터: n개만 읽는다
    return tuple((float(raw[i][0]), float(raw[i][1])) for i in range(n))


def _eye(contour, pupil, size: tuple[int, int]) -> Eye:
    pts = _region_points(contour, size)
    pupil_pts = _region_points(pupil, size)
    return Eye(
        openness=eye_openness(pts),
        pupil=pupil_pts[0] if pupil_pts else None,
        points=pts,
    )


def _deg(value) -> float | None:
    return None if value is None else math.degrees(float(value))


def detect_faces(image: Image.Image) -> list[Face]:
    """얼굴을 큰 순서로 돌려준다. 얼굴이 없으면 빈 목록."""
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        _to_cgimage(image), None
    )
    request = Vision.VNDetectFaceLandmarksRequest.alloc().init()
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision 요청 실패: {error}")

    size = image.size
    faces = []
    for obs in request.results() or []:
        box = obs.boundingBox()
        lm = obs.landmarks()
        if lm is None:
            continue
        faces.append(
            Face(
                face_width_px=float(box.size.width) * size[0],
                face_area=float(box.size.width * box.size.height),
                yaw_deg=_deg(obs.yaw()),
                roll_deg=_deg(obs.roll()),
                confidence=float(obs.confidence()),
                left=_eye(lm.leftEye(), lm.leftPupil(), size),
                right=_eye(lm.rightEye(), lm.rightPupil(), size),
                bbox=(
                    float(box.origin.x), float(box.origin.y),
                    float(box.size.width), float(box.size.height),
                ),
                image_width_px=size[0],
            )
        )
    faces.sort(key=lambda f: f.face_area, reverse=True)
    return faces
