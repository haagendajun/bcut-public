"""T1.2 스파이크: CR3 읽기 방법별 시간과 충실도 비교.

프로젝트 의존성이 아니라 스파이크 전용 가상환경(numpy, pillow, scipy, rawpy)에서 실행한다.
사진은 읽기만 한다. 사진 내용을 사람이 보지 않고 숫자 지표만 계산한다.

사용법:
    spike-venv/bin/python tools/spike_t12_image_reading.py \
        --folder "<행사 폴더>" --labels eval/labels_event_a.csv --out results.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image
from scipy import ndimage, stats

WIDTH = 1600  # 비교 기준 폭


def pct(values: list[float], q: float) -> float:
    return float(np.percentile(values, q))


def timed(fn, *args):
    t = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t


# ---- 읽기 방법 ---------------------------------------------------------------


def sips_resample(path: Path, width: int = WIDTH) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o.jpg"
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "--resampleWidth", str(width), str(path),
             "--out", str(out)],
            check=True, capture_output=True,
        )
        return np.asarray(Image.open(out).convert("RGB"))


def embedded_full_jpeg(path: Path) -> bytes:
    with rawpy.imread(str(path)) as raw:
        return raw.extract_thumb().data


def decode_draft(data: bytes, min_width: int) -> Image.Image:
    """JPEG를 DCT 축소로 빠르게 푼다. 결과 폭은 min_width 이상 중 가장 작은 1/n."""
    im = Image.open(io.BytesIO(data))
    h = int(min_width * im.height / im.width)
    im.draft("RGB", (min_width, h))
    return im.convert("RGB")


def to_width(im: Image.Image, width: int) -> np.ndarray:
    if im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return np.asarray(im)


def embedded_preview_1620(path: Path) -> bytes:
    """파일 앞부분에서 1620x1080 미리보기 JPEG를 찾는다."""
    with path.open("rb") as f:
        head = f.read(1_000_000)
    pos = 0
    while True:
        i = head.find(b"\xff\xd8\xff", pos)
        if i < 0:
            raise ValueError("미리보기를 찾지 못했다")
        j = head.find(b"\xff\xd9", i + 2)
        if j > 0:
            try:
                im = Image.open(io.BytesIO(head[i:j + 2]))
                if im.size == (1620, 1080):
                    return head[i:j + 2]
            except OSError:
                pass
        pos = i + 3


def rawpy_postprocess(path: Path, half: bool) -> np.ndarray:
    with rawpy.imread(str(path)) as raw:
        return raw.postprocess(half_size=half, use_camera_wb=True, output_bps=8)


# ---- 지표 ------------------------------------------------------------------


def metrics(rgb: np.ndarray) -> dict[str, float]:
    gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32)
    h, w = gray.shape
    center = gray[h // 4:3 * h // 4, w // 4:3 * w // 4]
    return {
        "lap_global": float(ndimage.laplace(gray).var()),
        "lap_center": float(ndimage.laplace(center).var()),
        "mean_luma": float(gray.mean()),
        "hi_clip": float((gray >= 250).mean()),
        "lo_clip": float((gray <= 5).mean()),
    }


# ---- 표본 ------------------------------------------------------------------


def pick_sample(folder: Path, labels_csv: Path, seed: int) -> list[Path]:
    rows = list(csv.DictReader(labels_csv.open(encoding="utf-8")))
    rng = random.Random(seed)
    chosen = []
    for label, n in (("B", 10), ("OK_EXPR", 10), ("OK", 10)):
        pool = sorted(r["file"] for r in rows if r["label"] == label)
        chosen += rng.sample(pool, min(n, len(pool)))
    return [folder / name for name in chosen]


# ---- 병렬 처리량 -----------------------------------------------------------


def _embedded_to_2048(path: str) -> int:
    data = embedded_full_jpeg(Path(path))
    return decode_draft(data, 2048).width


def _sips_1600(path: str) -> int:
    return sips_resample(Path(path)).shape[1]


def throughput(fn, paths: list[Path], workers: int) -> float:
    t = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        list(ex.map(fn, [str(p) for p in paths], chunksize=4))
    return time.perf_counter() - t


# ---- 메인 ------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--light", action="store_true", help="400장 병렬 처리량 시험을 건너뛴다")
    args = ap.parse_args()

    sample = pick_sample(args.folder, args.labels, args.seed)
    for p in sample:  # 시간 측정 전에 한 번 읽어 디스크 캐시를 데운다 (모든 방법에 같은 조건)
        p.read_bytes()
    print(f"표본 {len(sample)}장 (B 10, 표정 주의 10, 정상 10), 캐시 데움")

    results: dict = {"n": len(sample), "timing_s": {}, "metrics": {}}
    per_method_images: dict[str, list[dict]] = {}

    def run(name, load):
        times, ms = [], []
        for p in sample:
            rgb, dt = timed(load, p)
            times.append(dt)
            ms.append(metrics(rgb))
        results["timing_s"][name] = {
            "median": statistics.median(times), "p90": pct(times, 90), "max": max(times),
        }
        per_method_images[name] = ms
        print(f"  {name:<34} 중앙값 {statistics.median(times)*1000:8.1f} ms  "
              f"p90 {pct(times, 90)*1000:8.1f} ms")

    print("== 시간 (1장, 폭 1600 기준 결과까지) ==")
    run("M0 sips 1600 (RAW 디코딩, 기준)", lambda p: sips_resample(p))
    run("M1 내장 원본JPEG, 풀 디코딩+1600",
        lambda p: to_width(Image.open(io.BytesIO(embedded_full_jpeg(p))).convert("RGB"), WIDTH))
    run("M2 내장 원본JPEG, draft 2048→1600",
        lambda p: to_width(decode_draft(embedded_full_jpeg(p), 2048), WIDTH))
    run("M3 내장 원본JPEG, draft 1024(→1600 확대)",
        lambda p: to_width(decode_draft(embedded_full_jpeg(p), 1024), WIDTH))
    run("M4 내장 미리보기 1620x1080→1600",
        lambda p: to_width(Image.open(io.BytesIO(embedded_preview_1620(p))).convert("RGB"), WIDTH))
    run("M5 rawpy half_size 4096→1600",
        lambda p: to_width(Image.fromarray(rawpy_postprocess(p, True)), WIDTH))

    print("== 해상도별 디코딩 시간 (내장 원본 JPEG, 결과 해상도) ==")
    results["draft_s"] = {}
    for w in (1024, 2048, 4096, 8192):
        ts = []
        for p in sample[:10]:
            data = embedded_full_jpeg(p)
            _, dt = timed(decode_draft, data, w)
            ts.append(dt)
        results["draft_s"][w] = statistics.median(ts)
        print(f"  폭 {w:>5}: 중앙값 {statistics.median(ts)*1000:7.1f} ms")

    print("== 풀 디코딩 시간 (3장) ==")
    full_ts = [timed(rawpy_postprocess, p, False)[1] for p in sample[:3]]
    results["rawpy_full_s"] = statistics.median(full_ts)
    print(f"  rawpy 풀 디코딩 중앙값 {statistics.median(full_ts):.2f} s")

    print("== 충실도: 기준 M0 대비 (표본 30장) ==")
    ref = per_method_images["M0 sips 1600 (RAW 디코딩, 기준)"]
    for name, ms in per_method_images.items():
        if name.startswith("M0"):
            continue
        row = {}
        for key in ("lap_global", "lap_center"):
            a = [m[key] for m in ref]
            b = [m[key] for m in ms]
            rho = stats.spearmanr(a, b).statistic
            ratio = statistics.median(y / x for x, y in zip(a, b, strict=True) if x > 0)
            row[key] = {"spearman": float(rho), "median_ratio": ratio}
        luma_diff = [m["mean_luma"] - r["mean_luma"] for m, r in zip(ms, ref, strict=True)]
        row["mean_luma_diff"] = {"mean": statistics.mean(luma_diff),
                                 "abs_max": max(abs(x) for x in luma_diff)}
        row["hi_clip_diff_pp"] = statistics.mean(
            (m["hi_clip"] - r["hi_clip"]) * 100 for m, r in zip(ms, ref, strict=True))
        row["lo_clip_diff_pp"] = statistics.mean(
            (m["lo_clip"] - r["lo_clip"]) * 100 for m, r in zip(ms, ref, strict=True))
        results["metrics"][name] = row
        print(f"  {name}")
        print(f"     선명도 순위상관(전체) {row['lap_global']['spearman']:.3f}, "
              f"(중앙) {row['lap_center']['spearman']:.3f}, "
              f"값 비율(중앙값) 전체 {row['lap_global']['median_ratio']:.2f}x")
        print(f"     평균 밝기 차 {row['mean_luma_diff']['mean']:+.1f} "
              f"(최대 {row['mean_luma_diff']['abs_max']:.1f}), "
              f"하이라이트 클리핑 차 {row['hi_clip_diff_pp']:+.2f}%p, "
              f"섀도 클리핑 차 {row['lo_clip_diff_pp']:+.2f}%p")

    if not args.light:
        print("== 처리량 (병렬) ==")
        all_files = sorted(args.folder.glob("*.CR3"))
        t_emb = throughput(_embedded_to_2048, all_files, args.workers)
        results["throughput"] = {
            "embedded_2048_all": {
                "files": len(all_files), "seconds": t_emb, "workers": args.workers}
        }
        print(f"  M2 내장 JPEG→2048, {len(all_files)}장, {args.workers}개 병렬: "
              f"{t_emb:.1f} s ({t_emb/len(all_files)*1000:.0f} ms/장)")
        sips_subset = all_files[:80]
        t_sips = throughput(_sips_1600, sips_subset, args.workers)
        results["throughput"]["sips_1600_80"] = {
            "files": len(sips_subset), "seconds": t_sips, "workers": args.workers}
        print(f"  M0 sips 1600, {len(sips_subset)}장, {args.workers}개 병렬: "
              f"{t_sips:.1f} s ({t_sips/len(sips_subset)*1000:.0f} ms/장)")

    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {args.out}")


if __name__ == "__main__":
    main()
