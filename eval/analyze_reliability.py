"""T1.5 실험: 얼굴 크기와 각도에 따라 눈 감김 점수를 믿을 수 있는가.

입력: eval/features_v2_*.json (tools/extract_eye_features_v2.py 결과)
  base    = 폭 2048 전체 이미지에서 Vision 실행 (기존 방식)
  refined = 풀 해상도에서 주 얼굴 주변을 잘라 다시 실행 (두 번째 패스)

사용법:  python eval/analyze_reliability.py
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("analyze_eyes", HERE / "analyze_eyes.py")
ae = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ae)

CAND, REV = 0.134, 0.187  # T1.4 기본 임계값 (base 점수 기준)


def load(name: str) -> list[dict]:
    recs = json.loads((HERE / name).read_text(encoding="utf-8"))
    return sorted((r for r in recs if r["label"] != "UNSURE"), key=lambda r: r["file"])


def get(rec: dict, which: str, key: str):
    part = rec.get(which)
    return part.get(key) if part else None


def status(score: float | None, cand: float = CAND, rev: float = REV) -> str:
    if score is None:
        return "none"
    return "candidate" if score <= cand else ("review" if score <= rev else "normal")


def table_by_bin(recs, bin_fn, bins, score_key="base", title=""):
    print(f"\n{title}")
    print(f"{'구간':>14} {'B':>4} {'표정주의':>8} {'정상':>5} | {'B→후보':>7} {'B→후보+확인':>11} "
          f"{'음성→후보':>9} {'음성→확인':>9} | {'AUC(B vs 음성)':>14}")
    for name, pred in bins:
        sel = [r for r in recs if (v := bin_fn(r)) is not None and pred(v)]
        b = [r for r in sel if r["label"] == "B"]
        e = [r for r in sel if r["label"] == "OK_EXPR"]
        o = [r for r in sel if r["label"] == "OK"]
        neg = e + o
        st_b = Counter(status(get(r, score_key, "rmax")) for r in b)
        st_n = Counter(status(get(r, score_key, "rmax")) for r in neg)
        sb = np.array([get(r, score_key, "rmax") for r in b if get(r, score_key, "rmax") is not None])
        sn = np.array([get(r, score_key, "rmax") for r in neg if get(r, score_key, "rmax") is not None])
        a = ae.auc(sn, sb) if len(sb) >= 3 and len(sn) >= 3 else float("nan")
        print(f"{name:>14} {len(b):>4} {len(e):>8} {len(o):>5} | "
              f"{st_b['candidate']:>3}/{len(b):<3} {st_b['candidate'] + st_b['review']:>5}/{len(b):<3}   "
              f"{st_n['candidate']:>4}/{len(neg):<4} {st_n['review']:>4}/{len(neg):<4} | {a:>14.3f}")


def main() -> None:
    e2 = load("features_v2_event_a.json")
    e1 = load("features_v2_event_b.json")
    allr = e2 + e1
    print(f"E2 {len(e2)}장, E1 {len(e1)}장 (애매 제외)")

    print("\n== 1. 얼굴 검출·두 번째 패스 성공률 ==")
    for name, rs in (("E2", e2), ("E1", e1)):
        with_face = [r for r in rs if r["base"]]
        ref_ok = [r for r in with_face if r["refined"] and r["refined"]["rmax"] is not None]
        print(f"  {name}: 얼굴 있음 {len(with_face)}/{len(rs)}, 두 번째 패스 성공 {len(ref_ok)}/{len(with_face)}")

    print("\n== 2. Vision yaw 값 분포 (라벨별, base) ==")
    for lab in ("B", "OK_EXPR", "OK"):
        c = Counter(round(get(r, "base", "yaw")) for r in allr if r["label"] == lab and r["base"]
                    and get(r, "base", "yaw") is not None)
        print(f"  {lab:8} {dict(sorted(c.items()))}")
    print("  (yaw가 0, ±45처럼 몇 개 값으로만 나오면 각도 정보가 거칠다는 뜻)")

    print("\n== 3. 눈 폭(풀 해상도 px, base 기준) 분포 ==")
    for lab in ("B", "OK_EXPR", "OK"):
        v = [get(r, "base", "eye_w_full") for r in allr if r["label"] == lab and get(r, "base", "eye_w_full")]
        print(f"  {lab:8} n={len(v):3} min/p10/중앙/p90/max = {min(v):.0f}/{np.percentile(v, 10):.0f}/"
              f"{np.median(v):.0f}/{np.percentile(v, 90):.0f}/{max(v):.0f}")

    ew = lambda r: get(r, "base", "eye_w_full")  # noqa: E731
    bins_w = [("<60", lambda v: v < 60), ("60~80", lambda v: 60 <= v < 80),
              ("80~100", lambda v: 80 <= v < 100), ("100~140", lambda v: 100 <= v < 140),
              (">=140", lambda v: v >= 140)]
    table_by_bin(e2, ew, bins_w, "base", "== 4. 눈 폭 구간별 신뢰도: E2, base 점수, 기본 임계값 ==")

    yw = lambda r: abs(get(r, "base", "yaw")) if get(r, "base", "yaw") is not None else None  # noqa: E731
    bins_y = [("|yaw|=0", lambda v: v < 10), ("|yaw|>=10", lambda v: v >= 10)]
    table_by_bin(e2, yw, bins_y, "base", "== 5. 얼굴 각도(yaw)별 신뢰도: E2, base ==")

    rl = lambda r: abs(get(r, "base", "roll")) if get(r, "base", "roll") is not None else None  # noqa: E731
    bins_r = [("|roll|<10", lambda v: v < 10), ("10~25", lambda v: 10 <= v < 25),
              (">=25", lambda v: v >= 25)]
    table_by_bin(e2, rl, bins_r, "base", "== 6. 얼굴 기울기(roll)별 신뢰도: E2, base ==")

    print("\n== 7. base 점수 vs refined 점수 (E2+E1, 둘 다 있는 컷) ==")
    pairs = [(get(r, "base", "rmax"), get(r, "refined", "rmax"), r["label"]) for r in allr
             if get(r, "base", "rmax") is not None and get(r, "refined", "rmax") is not None]
    a = np.array([p[0] for p in pairs])
    b = np.array([p[1] for p in pairs])
    print(f"  n={len(pairs)}  상관 {np.corrcoef(a, b)[0, 1]:.3f}  평균차(refined-base) {np.mean(b - a):+.3f}  "
          f"|차| 중앙값 {np.median(np.abs(b - a)):.3f}  |차| p90 {np.percentile(np.abs(b - a), 90):.3f}")
    for lab in ("B", "OK_EXPR", "OK"):
        d = np.array([p[1] - p[0] for p in pairs if p[2] == lab])
        print(f"  {lab:8} 평균차 {np.mean(d):+.3f}, 표준편차 {np.std(d):.3f}")

    print("\n== 8. refined 점수로 다시 평가 (E2, 같은 방식의 4블록 교차 검증) ==")
    print(f"{'방식':10} {'AUC B vs 표정주의':>17} {'B vs 전체':>10} | {'B→후보':>7} {'후보+확인':>9} {'후보오탐':>8} {'확인부담':>8} {'묶음':>6}")
    for which in ("base", "refined"):
        scores = [get(r, which, "rmax") for r in e2]
        labels = [r["label"] for r in e2]
        pos = np.array([s for s, lab in zip(scores, labels, strict=True) if lab == "B" and s is not None])
        neg_e = np.array([s for s, lab in zip(scores, labels, strict=True) if lab == "OK_EXPR" and s is not None])
        neg_all = np.array([s for s, lab in zip(scores, labels, strict=True)
                            if lab in ("OK", "OK_EXPR") and s is not None])
        recs_like = [{"label": r["label"]} for r in e2]
        pred, _ = ae.cv_evaluate(recs_like, scores)
        s = ae.summarize(recs_like, pred)
        print(f"{which:10} {ae.auc(neg_e, pos):>17.3f} {ae.auc(neg_all, pos):>10.3f} | "
              f"{s['B_candidate']:>3}/{s['B_total']:<3} {s['B_cand_or_review']:>5}/{s['B_total']:<3} "
              f"{s['FP_candidate']:>4}/{s['neg_total']:<4} {s['review_negatives']:>4}/{s['neg_total']:<4} "
              f"{s['bursts_cand_or_review']:>3}/{s['bursts']:<3}")

    table_by_bin(e2, ew, bins_w[:3], "refined", "== 9. 눈 폭이 작은 구간에서 refined가 나아지나 (기본 임계값 그대로, refined 점수) ==")
    print("   (refined 점수는 척도가 달라 같은 임계값이 안 맞을 수 있음. 아래 표는 AUC 비교용)")


if __name__ == "__main__":
    main()
