"""T1.5 실험용: 눈 특징을 두 방식으로 뽑는다.

- base:    분석 입력(폭 2048) 전체 이미지에서 Vision 실행 (기존 방식)
- refined: 풀 해상도(8192)에서 주 얼굴 주변을 잘라 그 자르기만 Vision에 넣는 두 번째 패스

사진은 읽기만 한다. 사람이 열어 보지 않고 숫자만 저장한다. 네트워크를 쓰지 않는다.

사용법:
    python tools/extract_eye_features_v2.py --folder "<행사 폴더>" \
        --labels eval/labels_event_a.csv --out eval/features_v2_event_a.json
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from PIL import Image

from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg

MARGIN = 0.6  # 얼굴 상자 크기의 몇 배만큼 바깥까지 자를지
TARGET = 1024  # 잘라낸 이미지의 긴 변을 이 크기로 맞춘다


def summarize(face, scale: float) -> dict:
    ratios = face.ratios
    widths = [e.openness.width_px for e in (face.left, face.right) if e.openness]
    return {
        "rmin": min(ratios) if ratios else None,
        "rmax": max(ratios) if ratios else None,
        "left": face.left.openness.ratio if face.left.openness else None,
        "right": face.right.openness.ratio if face.right.openness else None,
        "eye_w_full": (sum(widths) / len(widths)) * scale if widths else None,
        "yaw": face.yaw_deg,
        "roll": face.roll_deg,
    }


def refine(full: Image.Image, face) -> dict | None:
    """풀 해상도 이미지에서 주 얼굴 주변을 잘라 다시 검출한다."""
    bx, by, bw, bh = face.bbox
    w, h = full.size
    fw, fh = bw * w, bh * h
    cx, cy = (bx + bw / 2) * w, (1 - (by + bh / 2)) * h  # Vision은 y가 아래에서 위
    half_w, half_h = fw * (0.5 + MARGIN), fh * (0.5 + MARGIN)
    box = (max(0, int(cx - half_w)), max(0, int(cy - half_h)),
           min(w, int(cx + half_w)), min(h, int(cy + half_h)))
    crop = full.crop(box)
    shrink = TARGET / max(crop.size)
    resized = crop.resize((round(crop.width * shrink), round(crop.height * shrink)), Image.LANCZOS)
    faces = detect_faces(resized)
    if not faces:
        return None
    out = summarize(faces[0], scale=1 / shrink)  # 잘라낸 이미지 픽셀을 풀 해상도 픽셀로
    out["crop_face_w_full"] = faces[0].face_width_px / shrink
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = sorted(csv.DictReader(args.labels.open(encoding="utf-8")), key=lambda r: r["file"])
    records, t0 = [], time.perf_counter()
    for r in rows:
        path = args.folder / r["file"]
        base_img = read_embedded_jpeg(path)
        faces = detect_faces(base_img.image)
        rec = {"file": r["file"], "label": r["label"], "n_faces": len(faces),
               "base": None, "refined": None}
        if faces:
            main_face = faces[0]
            rec["base"] = summarize(main_face, base_img.scale_to_full)
            rec["base"]["face_w_full"] = main_face.face_width_px * base_img.scale_to_full
            full = read_embedded_jpeg(path, width=base_img.full_width).image
            rec["refined"] = refine(full, main_face)
        records.append(rec)
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    seconds = time.perf_counter() - t0
    print(f"{len(records)}장, {seconds:.0f}초 ({seconds / len(records) * 1000:.0f} ms/장) -> {args.out}")


if __name__ == "__main__":
    main()
