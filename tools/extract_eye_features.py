"""라벨된 사진에서 눈 특징을 뽑아 JSON으로 저장한다 (T1.4 실험용 캐시).

사진은 읽기만 하고, 사람이 열어 보지 않고 숫자만 저장한다. 네트워크를 쓰지 않는다.

사용법:
    .venv/bin/python tools/extract_eye_features.py \
        --folder "<행사 폴더>" --labels eval/labels_event_a.csv --out eval/features_event_a.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

from bcut.detect.vision_face import Eye, Face, detect_faces
from bcut.imageio import read_embedded_jpeg


def pupil_offset(eye: Eye) -> float | None:
    """눈동자 점이 눈 윤곽 중심에서 얼마나 떨어졌는지 (눈 가로 길이로 나눔)."""
    if eye.pupil is None or eye.openness is None or not eye.points:
        return None
    cx = sum(p[0] for p in eye.points) / len(eye.points)
    cy = sum(p[1] for p in eye.points) / len(eye.points)
    return math.hypot(eye.pupil[0] - cx, eye.pupil[1] - cy) / eye.openness.width_px


def face_features(face: Face, scale: float) -> dict:
    ratios = face.ratios
    left = face.left.openness.ratio if face.left.openness else None
    right = face.right.openness.ratio if face.right.openness else None
    widths = [e.openness.width_px for e in (face.left, face.right) if e.openness]
    return {
        "rmin": min(ratios) if ratios else None,
        "rmean": sum(ratios) / len(ratios) if ratios else None,
        "rmax": max(ratios) if ratios else None,
        "left": left,
        "right": right,
        "asym": abs(left - right) if left is not None and right is not None else None,
        "eye_w_full": (sum(widths) / len(widths)) * scale if widths else None,
        "face_w_full": face.face_width_px * scale,
        "face_area": face.face_area,
        "yaw": face.yaw_deg,
        "roll": face.roll_deg,
        "conf": face.confidence,
        "pupil_off_l": pupil_offset(face.left),
        "pupil_off_r": pupil_offset(face.right),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = sorted(csv.DictReader(args.labels.open(encoding="utf-8")), key=lambda r: r["file"])
    records, t0 = [], time.perf_counter()
    for r in rows:
        loaded = read_embedded_jpeg(args.folder / r["file"])
        faces = detect_faces(loaded.image)
        scale = loaded.scale_to_full
        records.append({
            "file": r["file"],
            "label": r["label"],
            "reason": r["reason"],
            "n_faces": len(faces),
            "faces": [face_features(f, scale) for f in faces],
        })
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    seconds = time.perf_counter() - t0
    print(f"{len(records)}장 처리, {seconds:.1f}초 ({seconds / len(records) * 1000:.0f} ms/장) -> {args.out}")


if __name__ == "__main__":
    main()
