"""T1.6·T1.7 실험용: 사진의 선명도 특징을 뽑는다. 원본과 인위적으로 흐리게 만든 상태를 함께 계산한다.

사진은 읽기만 하고, 사람이 열어 보지 않고 숫자만 저장한다. 네트워크를 쓰지 않는다.
얼굴 위치는 원본에서 한 번만 찾고, 흐리게 만든 상태에서도 같은 위치를 쓴다.

흐림 단계는 분석 입력(폭 2048px) 기준 픽셀이다 (원본 8192px에서는 4배):
  전체 흐림(가우시안) sigma 1, 2, 3, 5 / 모션 블러 길이 8, 16, 32 / 얼굴만 흐림 sigma 2, 4, 8

사용법:
    python tools/extract_sharpness_features.py --folder "<행사 폴더>" \
        --labels eval/labels_event_a.csv --out eval/sharpness_event_a.json
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
from bcut.detect.sharpness import blur_metric, inner_region, mean_gradient, tile_blur_metrics
from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.synth import blur_region, gaussian_blur, motion_blur

GAUSS = (1.0, 2.0, 3.0, 5.0)
MOTION = (8, 16, 32)
FACE_BLUR = (2.0, 4.0, 8.0)
MAX_FACES = 3


def _angle(name: str) -> float:
    """파일 이름으로 정한 (재현 가능한) 모션 블러 각도 0~180도."""
    return int(hashlib.sha1(name.encode()).hexdigest()[:6], 16) % 180


def _measure(image, faces) -> dict:
    gray = to_gray(image)
    tiles = tile_blur_metrics(gray)
    out = {
        "global": blur_metric(gray),
        "tiles_n": len(tiles),
        "tiles": [round(t, 4) for t in sorted(tiles)],
        "faces": [],
    }
    for f in faces[:MAX_FACES]:
        region = inner_region(gray, f.bbox)
        out["faces"].append({
            "area": f.face_area,
            "blur": blur_metric(region) if region is not None else None,
            "grad": mean_gradient(region) if region is not None else None,
        })
    return out


def _one(job: tuple[str, str, str, bool]) -> dict:
    path, file, label, final_a = job
    loaded = read_embedded_jpeg(Path(path))
    faces = detect_faces(loaded.image)
    img = loaded.image
    variants = {"real": _measure(img, faces)}
    for s in GAUSS:
        variants[f"gauss{s:g}"] = _measure(gaussian_blur(img, s), faces)
    angle = _angle(file)
    for n in MOTION:
        variants[f"motion{n}"] = _measure(motion_blur(img, n, angle), faces)
    if faces:
        for s in FACE_BLUR:
            variants[f"face{s:g}"] = _measure(blur_region(img, faces[0].bbox, s), faces)
    return {"file": file, "label": label, "final_a": final_a, "n_faces": len(faces),
            "variants": variants}


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
