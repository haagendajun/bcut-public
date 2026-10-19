"""T1.17 실험용: 사진의 밝기 통계를 뽑는다. 원본과 인위적으로 노출을 바꾼 상태(합성)를 함께 계산한다.

사진은 읽기만 하고, 사람이 열어 보지 않고 숫자만 저장한다. 네트워크를 쓰지 않는다.
얼굴 위치는 원본에서 한 번만 찾고, 노출을 바꾼 상태에서도 같은 위치를 쓴다 (노출을 바꿔도 위치는 같다).

사용법:
    python tools/extract_exposure_features.py --folder "<행사 폴더>" \
        --labels eval/labels_event_a.csv --out eval/exposure_event_a.json
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from bcut.detect.exposure import face_region, luma_stats, to_gray
from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.synth import shift_exposure

EVS = (0.0, -3.0, -2.0, -1.5, -1.0, 1.0, 1.5, 2.0, 3.0)  # 0이 원본
MAX_FACES = 3


def _variant(image, faces, ev: float) -> dict:
    img = image if ev == 0 else shift_exposure(image, ev)
    gray = to_gray(img)
    out = {"global": asdict(luma_stats(gray)), "faces": []}
    for f in faces[:MAX_FACES]:
        region = face_region(gray, f.bbox)
        out["faces"].append({
            "area": f.face_area,
            "stats": asdict(luma_stats(region)) if region is not None else None,
        })
    return out


def _one(args: tuple[str, str, str, bool]) -> dict:
    path, file, label, final_a = args
    loaded = read_embedded_jpeg(Path(path))
    faces = detect_faces(loaded.image)
    return {
        "file": file, "label": label, "final_a": final_a, "n_faces": len(faces),
        "variants": {f"{ev:g}": _variant(loaded.image, faces, ev) for ev in EVS},
    }


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
        records = list(pool.map(_one, jobs, chunksize=4))
    args.out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    seconds = time.perf_counter() - t0
    print(f"{len(records)}장, {seconds:.0f}초 -> {args.out}")


if __name__ == "__main__":
    main()
