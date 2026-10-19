"""T1.4 실험: 눈 감김 점수 규칙 비교와 두 경계(candidate / review) 선택.

입력: eval/features_*.json (tools/extract_eye_features.py 결과), 라벨은 그 안에 들어 있다.
점수는 낮을수록 눈 감김에 가깝다. 학습하는 값(임계값)은 시간순 블록 교차 검증으로 정한다.

사용법:
    .venv/bin/python eval/analyze_eyes.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
FOLDS = 4
NEIGHBOR_K = 3


def load(path: Path) -> list[dict]:
    return sorted(json.loads(path.read_text(encoding="utf-8")), key=lambda r: r["file"])


def main_face(rec: dict) -> dict | None:
    return rec["faces"][0] if rec["faces"] else None


# ---- 점수 규칙 (낮을수록 감김) ---------------------------------------------


def score_rmin(rec):
    f = main_face(rec)
    return f["rmin"] if f else None


def score_rmean(rec):
    f = main_face(rec)
    return f["rmean"] if f else None


def score_rmax(rec):
    """두 눈이 모두 감겨야 낮아진다. 윙크·한쪽 눈 찡그림에 덜 민감하다."""
    f = main_face(rec)
    return f["rmax"] if f else None


def score_rmin_any(rec):
    vals = [f["rmin"] for f in rec["faces"] if f["rmin"] is not None]
    return min(vals) if vals else None


def score_rmax_any(rec):
    vals = [f["rmax"] for f in rec["faces"] if f["rmax"] is not None]
    return min(vals) if vals else None


BASE_SCORES = {
    "rmin": score_rmin,          # 더 감긴 쪽 눈
    "rmean": score_rmean,        # 두 눈 평균
    "rmax": score_rmax,          # 덜 감긴 쪽 눈 (두 눈 모두 감겨야 낮음)
    "rmin_any": score_rmin_any,  # 모든 얼굴 중 가장 감긴 눈
    "rmax_any": score_rmax_any,  # 모든 얼굴의 덜 감긴 쪽 눈 중 최저
}


def relative_scores(recs: list[dict], base) -> list[float | None]:
    """연사 이웃(앞뒤 K장)의 중앙값 대비 비율. 이웃은 같은 인물·같은 장면일 가능성이 높다."""
    raw = [base(r) for r in recs]
    out: list[float | None] = []
    for i, v in enumerate(raw):
        neigh = [raw[j] for j in range(max(0, i - NEIGHBOR_K), min(len(raw), i + NEIGHBOR_K + 1))
                 if j != i and raw[j] is not None]
        if v is None or len(neigh) < 2:
            out.append(None)
            continue
        med = statistics.median(neigh)
        out.append(v / med if med > 0 else None)
    return out


# ---- 평가 도구 ---------------------------------------------------------------


def auc(neg: np.ndarray, pos: np.ndarray) -> float:
    """pos가 neg보다 낮을 확률."""
    if len(neg) == 0 or len(pos) == 0:
        return float("nan")
    wins = (pos[:, None] < neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


def runs(flags: list[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        if not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def choose_thresholds(neg: np.ndarray, pos: np.ndarray, review_recall: float, margin_q: float):
    """학습 블록에서 두 경계를 정한다.

    t_cand: 학습 음성 중 하위 margin_q 분위보다 낮은 값 (0이면 가장 낮은 음성보다 낮게).
    t_rev:  학습 양성의 review_recall 만큼을 포함하는 값.
    """
    t_cand = (neg.min() - 1e-9) if margin_q == 0 else float(np.quantile(neg, margin_q))
    t_rev = float(np.quantile(pos, review_recall))
    return float(t_cand), max(float(t_rev), float(t_cand))


def cv_evaluate(recs: list[dict], scores: list[float | None], review_recall=0.9, margin_q=0.0):
    n = len(recs)
    size = n // FOLDS
    pred = ["normal"] * n  # 'candidate' | 'review' | 'normal'
    fold_rows = []
    for k in range(FOLDS):
        lo, hi = k * size, (k + 1) * size if k < FOLDS - 1 else n
        test_idx = list(range(lo, hi))
        train_idx = [i for i in range(n) if i not in set(test_idx)]
        tr_neg = np.array([scores[i] for i in train_idx
                           if recs[i]["label"] in ("OK", "OK_EXPR") and scores[i] is not None])
        tr_pos = np.array([scores[i] for i in train_idx
                           if recs[i]["label"] == "B" and scores[i] is not None])
        t_cand, t_rev = choose_thresholds(tr_neg, tr_pos, review_recall, margin_q)
        for i in test_idx:
            s = scores[i]
            if s is None:
                continue
            pred[i] = "candidate" if s <= t_cand else ("review" if s <= t_rev else "normal")
        fold_rows.append((k, t_cand, t_rev))
    return pred, fold_rows


def summarize(recs, pred):
    pos = [i for i, r in enumerate(recs) if r["label"] == "B"]
    neg = [i for i, r in enumerate(recs) if r["label"] in ("OK", "OK_EXPR")]
    expr = [i for i, r in enumerate(recs) if r["label"] == "OK_EXPR"]
    b_cand = sum(pred[i] == "candidate" for i in pos)
    b_any = sum(pred[i] in ("candidate", "review") for i in pos)
    fp_cand = sum(pred[i] == "candidate" for i in neg)
    fp_cand_expr = sum(pred[i] == "candidate" for i in expr)
    review_neg = sum(pred[i] == "review" for i in neg)
    clusters = runs([r["label"] == "B" for r in recs])
    bursts_any = sum(any(pred[j] in ("candidate", "review") for j in range(a, b + 1))
                     for a, b in clusters)
    bursts_cand = sum(any(pred[j] == "candidate" for j in range(a, b + 1)) for a, b in clusters)
    return {
        "B_total": len(pos),
        "B_candidate": b_cand,
        "B_cand_or_review": b_any,
        "FP_candidate": fp_cand,
        "FP_candidate_in_OK_EXPR": fp_cand_expr,
        "review_negatives": review_neg,
        "neg_total": len(neg),
        "bursts": len(clusters),
        "bursts_candidate": bursts_cand,
        "bursts_cand_or_review": bursts_any,
    }


def main() -> None:
    event_a = load(HERE / "features_event_a.json")
    event_b = load(HERE / "features_event_b.json")
    recs = [r for r in event_a if r["label"] != "UNSURE"]
    print(f"E2(EVENT_A): {len(recs)}장 (UNSURE 제외), B {sum(r['label']=='B' for r in recs)}, "
          f"OK_EXPR {sum(r['label']=='OK_EXPR' for r in recs)}, OK {sum(r['label']=='OK' for r in recs)}")

    scores_all: dict[str, list[float | None]] = {n: [f(r) for r in recs]
                                                  for n, f in BASE_SCORES.items()}
    for n in ("rmin", "rmax"):
        scores_all[f"{n}_rel"] = relative_scores(recs, BASE_SCORES[n])

    labels = [r["label"] for r in recs]

    def arr(name, want):
        return np.array([s for s, lab in zip(scores_all[name], labels, strict=True)
                         if lab in want and s is not None])

    print("\n== 1. 점수 규칙별 분리력 (E2 전체, 임계값 없음) ==")
    print(f"{'규칙':10} {'B vs 정상':>10} {'B vs 표정주의':>14} {'B vs 전체':>10}")
    for name in scores_all:
        pos = arr(name, {"B"})
        print(f"{name:10} {auc(arr(name, {'OK'}), pos):10.3f} {auc(arr(name, {'OK_EXPR'}), pos):14.3f}"
              f" {auc(arr(name, {'OK', 'OK_EXPR'}), pos):10.3f}")

    print("\n== 2. 시간순 4블록 교차 검증 (임계값은 학습 블록에서만 정함) ==")
    print("   candidate 경계: 학습 음성 중 가장 낮은 값 아래(오탐 0 기준)  /  review 경계: 학습 B의 90% 포함")
    hdr = (f"{'규칙':10} {'B→후보':>8} {'B→후보+확인':>11} {'후보 오탐':>9} "
           f"{'(표정주의)':>9} {'review 부담':>11} {'묶음→후보+확인':>13}")
    print(hdr)
    results = {}
    for name in scores_all:
        pred, _ = cv_evaluate(recs, scores_all[name])
        s = summarize(recs, pred)
        results[name] = s
        print(f"{name:10} {s['B_candidate']:>3}/{s['B_total']:<3}  {s['B_cand_or_review']:>5}/{s['B_total']:<3}   "
              f"{s['FP_candidate']:>4}/{s['neg_total']:<4} {s['FP_candidate_in_OK_EXPR']:>6}   "
              f"{s['review_negatives']:>4}/{s['neg_total']:<4}   "
              f"{s['bursts_cand_or_review']:>4}/{s['bursts']:<3}")

    print("\n== 3. 안전 여유를 둔 candidate 경계 (학습 음성 하위 1% 분위) ==")
    print(f"{'규칙':10} {'B→후보':>8} {'후보 오탐':>9} {'(표정주의)':>9} {'review 부담':>11}")
    for name in ("rmin", "rmean", "rmax"):
        pred, _ = cv_evaluate(recs, scores_all[name], margin_q=0.01)
        s = summarize(recs, pred)
        print(f"{name:10} {s['B_candidate']:>3}/{s['B_total']:<3}  {s['FP_candidate']:>4}/{s['neg_total']:<4} "
              f"{s['FP_candidate_in_OK_EXPR']:>6}   {s['review_negatives']:>4}/{s['neg_total']:<4}")

    json.dump(results, (HERE / "eyes_cv_results.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\n== 3b. 동작점 표 (교차 검증 합산): candidate 경계를 얼마나 공격적으로 잡을지 ==")
    print("   margin_q = 학습 음성 중 하위 몇 %까지 후보로 허용할지 (0 = 학습 음성보다 낮은 값만)")
    print(f"{'규칙':7} {'margin_q':>8} {'review재현':>10} {'B→후보':>8} {'B→후보+확인':>11} "
          f"{'후보 오탐':>9} {'review 부담':>11} {'묶음→후보+확인':>13}")
    for name in ("rmax", "rmin"):
        for rr in (0.90, 0.95):
            for mq in (0.0, 0.005, 0.01, 0.02):
                pred, _ = cv_evaluate(recs, scores_all[name], review_recall=rr, margin_q=mq)
                s = summarize(recs, pred)
                print(f"{name:7} {mq:8.3f} {rr:10.2f} {s['B_candidate']:>3}/{s['B_total']:<3}  "
                      f"{s['B_cand_or_review']:>5}/{s['B_total']:<3}   "
                      f"{s['FP_candidate']:>4}/{s['neg_total']:<4} {s['review_negatives']:>5}/{s['neg_total']:<4}   "
                      f"{s['bursts_cand_or_review']:>4}/{s['bursts']:<3}")

    print("\n== 3c. 다른 단서가 도움이 되는지 (E2 전체 AUC, 낮을수록 B로 가정) ==")
    for key, sign in (("asym", -1), ("conf", 1)):
        vals = [(main_face(r)[key] if main_face(r) else None) for r in recs]
        pos = np.array([v * sign for v, lab in zip(vals, labels, strict=True)
                        if lab == "B" and v is not None])
        neg = np.array([v * sign for v, lab in zip(vals, labels, strict=True)
                        if lab in ("OK", "OK_EXPR") and v is not None])
        print(f"  {key:6} B vs 전체 AUC {auc(neg, pos):.3f}")
    off = []
    for r in recs:
        f = main_face(r)
        v = [x for x in (f["pupil_off_l"], f["pupil_off_r"]) if x is not None] if f else []
        off.append(float(np.mean(v)) if v else None)
    pos = np.array([v for v, lab in zip(off, labels, strict=True) if lab == "B" and v is not None])
    neg = np.array([v for v, lab in zip(off, labels, strict=True)
                    if lab in ("OK", "OK_EXPR") and v is not None])
    print(f"  pupil_off B vs 전체 AUC {auc(neg, pos):.3f} (낮을수록 B) / 반대 방향 {auc(-neg, -pos):.3f}")

    print("\n== 4. 블록별 임계값 안정성 (rmin, 오탐 0 기준) ==")
    _, rows = cv_evaluate(recs, scores_all["rmin"])
    for k, tc, tr in rows:
        print(f"  블록 {k + 1}: t_candidate {tc:.3f}, t_review {tr:.3f}")

    print("\n== 5. 얼굴 정보 분포 (B 표본) ==")
    bf = [r["faces"][0] for r in recs if r["label"] == "B" and r["faces"]]
    for key in ("yaw", "eye_w_full", "face_w_full", "conf"):
        v = [f[key] for f in bf if f[key] is not None]
        print(f"  {key:12} p10/중앙/p90 = {np.percentile(v, 10):.2f}/{np.median(v):.2f}/{np.percentile(v, 90):.2f}")

    print("\n== 6. EVENT_B(E1) 음성 점검: E2 전체로 정한 경계를 그대로 적용 ==")
    e1 = [r for r in event_b if r["label"] != "UNSURE"]
    for name in ("rmin", "rmax"):
        s2 = scores_all[name]
        neg2 = np.array([s for s, lab in zip(s2, labels, strict=True)
                         if lab in ("OK", "OK_EXPR") and s is not None])
        pos2 = np.array([s for s, lab in zip(s2, labels, strict=True) if lab == "B" and s is not None])
        t_cand, t_rev = choose_thresholds(neg2, pos2, 0.9, 0.0)
        e1_scores = [BASE_SCORES[name](r) for r in e1]
        n_neg = sum(1 for r, s in zip(e1, e1_scores, strict=True)
                    if r["label"] in ("OK", "OK_EXPR") and s is not None)
        cand = [r["file"] for r, s in zip(e1, e1_scores, strict=True)
                if r["label"] in ("OK", "OK_EXPR") and s is not None and s <= t_cand]
        rev = sum(1 for r, s in zip(e1, e1_scores, strict=True)
                  if r["label"] in ("OK", "OK_EXPR") and s is not None and t_cand < s <= t_rev)
        print(f"  {name}: t_cand {t_cand:.3f}, t_rev {t_rev:.3f} -> E1 음성 {n_neg}장 중 "
              f"후보 오탐 {len(cand)}장 {cand[:4]}, review {rev}장")


if __name__ == "__main__":
    main()
