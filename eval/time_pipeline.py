"""읽기 + 얼굴 검출 + 눈 감김 판정까지 실제 파이프라인의 속도를 잰다 (G1a, Q4 참고).

사진은 읽기만 하고 아무것도 쓰지 않는다. 네트워크를 쓰지 않는다.

사용법:  python eval/time_pipeline.py <행사 폴더> [--workers 6] [--limit 400]
"""

from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bcut.detect.vision_face import detect_faces
from bcut.imageio import read_embedded_jpeg
from bcut.score.eyes import classify_eyes


def one(path: str) -> tuple[str, float]:
    t = time.perf_counter()
    loaded = read_embedded_jpeg(Path(path))
    verdict = classify_eyes(detect_faces(loaded.image))
    return verdict.status, time.perf_counter() - t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    files = sorted(args.folder.glob("*.CR3"))[: args.limit]
    for f in files[:5]:  # 디스크 캐시를 데운다 (읽기 조건을 같게)
        f.read_bytes()

    t0 = time.perf_counter()
    single = [one(str(f))[1] for f in files]
    seq = time.perf_counter() - t0
    print(f"단일 처리 {len(files)}장: {seq:.1f}초 ({seq / len(files) * 1000:.0f} ms/장, "
          f"중앙값 {statistics.median(single) * 1000:.0f} ms, 최대 {max(single) * 1000:.0f} ms)")
    print(f"  1500장 추정: 약 {seq / len(files) * 1500 / 60:.1f}분")

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(one, [str(f) for f in files], chunksize=4))
    par = time.perf_counter() - t0
    print(f"병렬 {args.workers}개 {len(files)}장: {par:.1f}초 ({par / len(files) * 1000:.0f} ms/장, "
          f"속도 {seq / par:.1f}배)")
    print(f"  1500장 추정: 약 {par / len(files) * 1500:.0f}초")


if __name__ == "__main__":
    main()
