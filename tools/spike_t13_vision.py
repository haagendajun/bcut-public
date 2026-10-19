"""T1.3 스파이크: macOS Vision 얼굴 랜드마크 시험 (눈 감김 분리력 포함).

스파이크 전용 가상환경(numpy, pillow, scipy, rawpy, pyobjc-framework-Vision/Quartz)에서 실행한다.
사진은 읽기만 하고, 사람이 열어 보지 않고 숫자 지표만 계산한다. 네트워크를 쓰지 않는다.

사용법:
    spike-venv/bin/python tools/spike_t13_vision.py \
        --folder "<행사 폴더>" --labels eval/labels_event_a.csv --out results.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import statistics
import time
from pathlib import Path

import Foundation
import numpy as np
import Quartz
import rawpy
import Vision
from PIL import Image
from scipy.stats import rankdata

FULL_WIDTH = 8192  # 내장 JPEG 폭 (T1.2에서 확인)
INPUT_WIDTH = 2048  # 분석 입력 폭


def load_input(path: Path) -> tuple[Image.Image, float]:
    """내장 원본 JPEG를 draft 2048로 읽는다. (이미지, 읽는 데 걸린 초)"""
    t = time.perf_counter()
    with rawpy.imread(str(path)) as raw:
        data = raw.extract_thumb().data
    im = Image.open(io.BytesIO(data))
    im.draft("RGB", (INPUT_WIDTH, int(INPUT_WIDTH * im.height / im.width)))
    im = im.convert("RGB")
    return im, time.perf_counter() - t


def to_cgimage(im: Image.Image):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    data = buf.getvalue()
    nsdata = Foundation.NSData.dataWithBytes_length_(data, len(data))
    src = Quartz.CGImageSourceCreateWithData(nsdata, None)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def eye_stats(region, size: tuple[int, int]) -> dict | None:
    """눈 윤곽점에서 열림 비율과 눈 폭(분석 입력 픽셀)을 구한다. 롤 각도에 영향 없게 PCA를 쓴다."""
    if region is None or region.pointCount() < 4:
        return None
    n = int(region.pointCount())
    raw_pts = region.pointsInImageOfSize_(size)  # 길이를 모르는 포인터라 개수만큼만 읽는다
    pts = np.array([(raw_pts[i][0], raw_pts[i][1]) for i in range(n)], dtype=float)
    centered = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj = centered @ vt.T
    major = float(proj[:, 0].max() - proj[:, 0].min())
    minor = float(proj[:, 1].max() - proj[:, 1].min())
    if major <= 0:
        return None
    return {"ratio": minor / major, "width_px": major, "n": int(region.pointCount())}


def analyze(im: Image.Image) -> tuple[list[dict], float, bool]:
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(to_cgimage(im), None)
    req = Vision.VNDetectFaceLandmarksRequest.alloc().init()
    t = time.perf_counter()
    ok, _err = handler.performRequests_error_([req], None)
    dt = time.perf_counter() - t
    faces = []
    scale = FULL_WIDTH / im.width
    for obs in req.results() or []:
        bb = obs.boundingBox()
        lm = obs.landmarks()
        left = eye_stats(lm.leftEye(), im.size) if lm is not None else None
        right = eye_stats(lm.rightEye(), im.size) if lm is not None else None
        yaw = obs.yaw()
        roll = obs.roll()
        faces.append({
            "face_w_full": bb.size.width * FULL_WIDTH,
            "face_area": bb.size.width * bb.size.height,
            "yaw_deg": float(yaw) * 180 / np.pi if yaw is not None else None,
            "roll_deg": float(roll) * 180 / np.pi if roll is not None else None,
            "left": left,
            "right": right,
            "eye_w_full": (
                statistics.mean(e["width_px"] for e in (left, right) if e) * scale
                if (left or right) else None
            ),
        })
    faces.sort(key=lambda f: f["face_area"], reverse=True)
    return faces, dt, bool(ok)


def openness(face: dict) -> float | None:
    vals = [e["ratio"] for e in (face["left"], face["right"]) if e]
    return min(vals) if vals else None  # 더 감긴 쪽 눈 기준 (낮을수록 감김)


def auc(neg: list[float], pos: list[float]) -> float:
    """pos(눈 감김)가 neg보다 값이 낮을 확률. 1.0에 가까울수록 분리가 잘 됨."""
    if not neg or not pos:
        return float("nan")
    scores = np.array(neg + pos)
    ranks = rankdata(-scores)  # 값이 낮을수록 높은 순위
    r_pos = ranks[len(neg):].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def recall_at_fpr(neg: list[float], pos: list[float], fpr: float) -> float:
    """neg 중 fpr 이하만 잘못 걸리게 하는 임계값에서 pos의 재현율."""
    if not neg or not pos:
        return float("nan")
    thr = np.quantile(neg, fpr) if fpr > 0 else min(neg) - 1e-9
    caught = sum(1 for v in pos if v <= thr)
    return caught / len(pos)


def pick(folder: Path, labels_csv: Path, seed: int, n_expr: int, n_ok: int):
    rows = list(csv.DictReader(labels_csv.open(encoding="utf-8")))
    rng = random.Random(seed)
    groups = {"B": sorted(r["file"] for r in rows if r["label"] == "B")}
    for label, n in (("OK_EXPR", n_expr), ("OK", n_ok)):
        pool = sorted(r["file"] for r in rows if r["label"] == label)
        groups[label] = rng.sample(pool, min(n, len(pool)))
    return {k: [folder / f for f in v] for k, v in groups.items()}


def pct(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--n-expr", type=int, default=40)
    ap.add_argument("--n-ok", type=int, default=60)
    args = ap.parse_args()

    groups = pick(args.folder, args.labels, args.seed, args.n_expr, args.n_ok)
    records = []
    for label, paths in groups.items():
        for p in paths:
            im, t_load = load_input(p)
            faces, t_vis, ok = analyze(im)
            records.append({"label": label, "file": p.name, "ok": ok, "t_load": t_load,
                            "t_vision": t_vis, "faces": faces})
    print(f"분석 {len(records)}장 (B {len(groups['B'])}, 표정 주의 {len(groups['OK_EXPR'])}, "
          f"정상 {len(groups['OK'])})")

    print("== 시간 (1장) ==")
    print(f"  읽기(draft 2048) 중앙값 {statistics.median(r['t_load'] for r in records)*1000:.0f} ms,"
          f" Vision 중앙값 {statistics.median(r['t_vision'] for r in records)*1000:.0f} ms,"
          f" Vision p90 {pct([r['t_vision'] for r in records], 90)*1000:.0f} ms")

    print("== 얼굴 검출 (라벨별) ==")
    for label in ("B", "OK_EXPR", "OK"):
        rs = [r for r in records if r["label"] == label]
        with_face = [r for r in rs if r["faces"]]
        with_eyes = [r for r in with_face if openness(r["faces"][0]) is not None]
        counts = [len(r["faces"]) for r in rs]
        print(f"  {label:8} {len(rs):3}장: 얼굴 있음 {len(with_face)} ({len(with_face)/len(rs):.0%}), "
              f"눈 랜드마크 있음 {len(with_eyes)} ({len(with_eyes)/len(rs):.0%}), "
              f"얼굴 수 중앙값 {statistics.median(counts):.0f} 최대 {max(counts)}")

    print("== 주 얼굴(가장 큰 얼굴) 크기, 풀 해상도 기준 px ==")
    for label in ("B", "OK_EXPR", "OK"):
        fw = [r["faces"][0]["face_w_full"] for r in records if r["label"] == label and r["faces"]]
        ew = [r["faces"][0]["eye_w_full"] for r in records
              if r["label"] == label and r["faces"] and r["faces"][0]["eye_w_full"]]
        print(f"  {label:8} 얼굴 폭 p10/중앙/p90 = {pct(fw,10):.0f}/{pct(fw,50):.0f}/{pct(fw,90):.0f}  "
              f"눈 폭 p10/중앙/p90 = {pct(ew,10):.0f}/{pct(ew,50):.0f}/{pct(ew,90):.0f}")

    print("== 눈 열림 비율 분포 (주 얼굴, 낮을수록 감김) ==")
    vals = {}
    for label in ("B", "OK_EXPR", "OK"):
        vals[label] = [openness(r["faces"][0]) for r in records
                       if r["label"] == label and r["faces"] and openness(r["faces"][0]) is not None]
        v = vals[label]
        print(f"  {label:8} n={len(v):3}  p10/중앙/p90 = {pct(v,10):.3f}/{pct(v,50):.3f}/{pct(v,90):.3f}")

    print("== 눈 감김 분리력 (주 얼굴 기준, 이 표본만의 참고치. 임계값 튜닝 아님) ==")
    results = {}
    for name, neg in (("B vs 정상", vals["OK"]), ("B vs 표정 주의", vals["OK_EXPR"]),
                      ("B vs 정상+표정 주의", vals["OK"] + vals["OK_EXPR"])):
        a = auc(neg, vals["B"])
        r0 = recall_at_fpr(neg, vals["B"], 0.0)
        r1 = recall_at_fpr(neg, vals["B"], 0.01)
        r5 = recall_at_fpr(neg, vals["B"], 0.05)
        results[name] = {"auc": a, "recall_fpr0": r0, "recall_fpr1": r1, "recall_fpr5": r5}
        print(f"  {name:22} AUC {a:.3f} | 오탐 0%에서 재현율 {r0:.0%} | 1% {r1:.0%} | 5% {r5:.0%}")

    no_face_b = [r["file"] for r in records if r["label"] == "B" and not r["faces"]]
    print(f"== 눈 감김(B)인데 얼굴을 못 찾은 컷: {len(no_face_b)}장 {no_face_b[:5]}")

    args.out.write_text(json.dumps({"records": records, "summary": results},
                                   ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"결과 저장: {args.out}")


if __name__ == "__main__":
    main()
