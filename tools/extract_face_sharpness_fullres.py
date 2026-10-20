"""T1.6 실험용: 얼굴 영역의 선명도를 **풀 해상도(8192px)** 에서 잰다. 합성 흐림도 풀 해상도 기준이다.

분석 입력(폭 2048px)에서는 가벼운 흔들림이 거의 안 보인다. 원본에서 100% 확대로 보이는 흔들림은
입력에서는 몇 픽셀 번짐이기 때문이다. 그래서 얼굴 영역만 풀 해상도로 잘라 재 본다.

얼굴 위치는 분석 입력(2048px)에서 찾고, 풀 해상도에서는 그 위치를 잘라 쓴다. 흐림은 잘라낸 부분에만
입힌다 (효율을 위해. 얼굴 안쪽의 선명도만 재므로 결과는 같다).
흐림 단계 (풀 해상도 픽셀): 가우시안 sigma 2, 4, 8 / 모션 블러 길이 8, 16, 32

사진은 읽기만 하고, 사람이 열어 보지 않고 숫자만 저장한다. 네트워크를 쓰지 않는다.

사용법:
    python tools/extract_face_sharpness_fullres.py --folder "<행사 폴더>" \
        --labels eval/labels_event_a.csv --out eval/facefull_event_a.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from bcut.detect.exposure import to_gray
from bcut.detect.sharpness import DIAGONAL_DIRECTIONS, blur_metric, inner_region, mean_gradient
from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.synth import gaussian_blur, motion_blur

GAUSS = (2.0, 4.0, 8.0)
MOTION = (8, 16, 32)
MAX_FACES = 3
PAD = 0.4  # 얼굴 상자 크기의 이 비율만큼 바깥까지 잘라 흐림 가장자리 효과를 피한다


def _angle(name: str) -> float:
    return int(hashlib.sha1(name.encode()).hexdigest()[:6], 16) % 180


def _measure(crop_img, nbbox) -> dict:
    gray = to_gray(crop_img)
    region = inner_region(gray, nbbox)
    if region is None:
        return {"blur": None, "blur4": None, "grad": None, "px": 0}
    return {
        "blur": blur_metric(region),
        "blur4": blur_metric(region, DIAGONAL_DIRECTIONS),
        "grad": mean_gradient(region),
        "px": int(region.shape[1]),
    }


def _crop(full, bbox):
    """풀 해상도 이미지에서 얼굴 주변을 자르고, 잘라낸 이미지 안에서의 얼굴 상자(비율)를 돌려준다."""
    W, H = full.size
    x, y, bw, bh = bbox
    fx0, fx1 = x * W, (x + bw) * W
    fy0, fy1 = (1 - y - bh) * H, (1 - y) * H
    px, py = (fx1 - fx0) * PAD, (fy1 - fy0) * PAD
    cx0, cx1 = max(0, int(fx0 - px)), min(W, int(fx1 + px))
    cy0, cy1 = max(0, int(fy0 - py)), min(H, int(fy1 + py))
    cw, ch = cx1 - cx0, cy1 - cy0
    nb = ((fx0 - cx0) / cw, 1 - (fy1 - cy0) / ch, (fx1 - fx0) / cw, (fy1 - fy0) / ch)
    return full.crop((cx0, cy0, cx1, cy1)), nb


def _one(job: tuple[str, str, str, bool]) -> dict:
    path, file, label, final_a = job
    small = read_embedded_jpeg(Path(path))
    faces = detect_faces(small.image)
    rec = {"file": file, "label": label, "final_a": final_a, "n_faces": len(faces), "faces": []}
    if not faces:
        return rec
    full = read_embedded_jpeg(Path(path), width=small.full_width).image
    angle = _angle(file)
    for f in faces[:MAX_FACES]:
        crop, nb = _crop(full, f.bbox)
        variants = {"real": _measure(crop, nb)}
        for s in GAUSS:
            variants[f"gauss{s:g}"] = _measure(gaussian_blur(crop, s), nb)
        for n in MOTION:
            variants[f"motion{n}"] = _measure(motion_blur(crop, n, angle), nb)
        rec["faces"].append({"area": f.face_area, "variants": variants})
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    rows = sorted(csv.DictReader(args.labels.open(encoding="utf-8")), key=lambda r: r["file"])
    jobs = [(str(args.folder / r["file"]), r["file"], r["label"], r.get("is_final_a") == "1")
            for r in rows]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(_one, jobs, chunksize=2))
    args.out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    print(f"{len(records)}장, {time.perf_counter() - t0:.0f}초 -> {args.out}")


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
