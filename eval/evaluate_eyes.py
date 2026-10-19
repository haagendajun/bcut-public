"""G1a 체크포인트: 눈 감김만으로 합격 기준을 충족하는지 평가한다 (devplan T1.13).

방법
- E2(EVENT_A 구간 397장): 시간순 4블록 교차 검증. B 묶음이 잘리지 않게 블록 경계를 조정한다.
  임계값(candidate, review)은 학습 블록에서만 정하고, 평가는 학습에 쓰지 않은 블록에서만 한다.
  좁은 눈 규칙(눈 폭 비율)은 T1.5에서 E2를 보고 정한 값이라 **교차 검증 밖에서 정해진 값**이다.
- E1(EVENT_B 138장): E2 전체로 정한 임계값을 그대로 적용하는 **새 행사 점검** (B는 1장뿐).
  이 행사는 최종 선택(별점 5) 16장이 있어 "좋은 컷이 후보로 걸렸는가"를 직접 본다.

입력: eval/features_*.json (얼굴 전체), 라벨 CSV (최종 선택 정보). 평가는 운영 코드 classify_eyes를 그대로 쓴다.

사용법:  python eval/evaluate_eyes.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import numpy as np
from features_io import load_event

from bcut.evaluation import (
    Item,
    block_bounds,
    burst_recall,
    burst_recall_stat,
    cluster_bootstrap_ci,
    frame_recall_candidate,
    frame_recall_raised,
    merge,
    recall_candidate,
    recall_raised,
    summarize,
    wilson,
)
from bcut.score.eyes import EyesThresholds, classify_eyes

HERE = Path(__file__).parent
MIN_FRAC = EyesThresholds().min_eye_width_frac
FOLDS = 4
REVIEW_RECALL = 0.95  # review 경계: 학습 B의 95%가 들어가는 값 (민감도 표로 선택, 아래 참고)


def to_items(recs: list[dict], t: EyesThresholds) -> list[Item]:
    """운영 코드(classify_eyes)로 사진마다 등급을 정한다. 단체 사진 정책도 그대로 적용된다."""
    items = []
    for r in recs:
        verdict = classify_eyes(r["faces"], t)
        items.append(Item(file=r["file"], label=r["label"], status=verdict.status,
                          note=verdict.note, final_a=r["final_a"]))
    return items


def fit_thresholds(train: list[dict], review_recall: float = REVIEW_RECALL) -> EyesThresholds:
    """학습 블록에서 두 경계를 정한다. 눈이 좁은 컷은 점수를 믿을 수 없으니 학습에서 뺀다."""
    scorable = [r for r in train if r["score"] is not None
                and (r["frac"] is None or r["frac"] >= MIN_FRAC)]
    neg = [r["score"] for r in scorable if r["label"] in ("OK", "OK_EXPR")]
    pos = [r["score"] for r in scorable if r["label"] == "B"]
    t_cand = min(neg) - 1e-9  # 학습 음성보다 낮은 값만 후보 (오탐 0 기준)
    t_rev = max(float(np.quantile(pos, review_recall)), t_cand)
    return EyesThresholds(candidate_max=t_cand, review_max=t_rev, min_eye_width_frac=MIN_FRAC)


def cross_validate(e2: list[dict], review_recall: float):
    labels = [r["label"] for r in e2]
    summaries, items_all, folds = [], [], []
    for lo, hi in block_bounds(labels, FOLDS):
        train = [r for i, r in enumerate(e2) if not lo <= i < hi]
        t = fit_thresholds(train, review_recall)
        items = to_items(e2[lo:hi], t)
        summaries.append(summarize(items))
        items_all += items
        folds.append((lo, hi, t))
    return merge(summaries), items_all, summaries, folds


def sensitivity(e2: list[dict], e1: list[dict]) -> None:
    print("\n[review 경계 민감도: 학습 B의 몇 %를 review 안에 넣을지]")
    print(f"{'학습 B 포함':>10} {'review 경계(전체 학습)':>20} | {'눈 감김 후보+확인':>16} {'후보만':>8} {'놓침':>4} | "
          f"{'후보 오탐':>8} {'확인 부담':>10} | {'E1 확인(음성)':>12}")
    for rr in (0.80, 0.90, 0.95, 1.00):
        pooled, _, _, _ = cross_validate(e2, rr)
        t_all = fit_thresholds(e2, rr)
        s1 = summarize(to_items(e1, t_all))
        print(f"{rr:>10.0%} {t_all.review_max:>20.3f} | "
              f"{pooled['B_candidate'] + pooled['B_review']:>7}/{pooled['B']:<3} ({recall_raised(pooled):.0%}) "
              f"{pooled['B_candidate']:>4}/{pooled['B']:<3} {pooled['B_missed']:>4} | "
              f"{pooled['neg_candidate']:>4}/{pooled['neg']:<3} {pooled['neg_review']:>5}/{pooled['neg']:<3} ({pooled['neg_review'] / pooled['neg']:.1%}) | "
              f"{s1['neg_review']:>5}/{s1['neg']:<3}")


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else f"{a}/{b}"


def main() -> None:
    e2 = load_event("features_event_a.json", "labels_event_a.csv")
    e1 = load_event("features_event_b.json", "labels.csv")
    print(f"E2 EVENT_A {len(e2)}장, E1 EVENT_B {len(e1)}장 (애매 제외)")

    # ---- E2 교차 검증 --------------------------------------------------------
    labels = [r["label"] for r in e2]
    bounds = block_bounds(labels, FOLDS)
    print(f"\n[E2] 시간순 {FOLDS}블록 교차 검증 (B 묶음이 잘리지 않게 경계 조정)")
    print(f"{'블록':>4} {'범위':>22} {'학습 임계값':>19} {'B':>3} {'후보':>4} {'확인':>4} {'놓침':>4} "
          f"{'후보오탐':>7} {'확인부담':>8} {'묶음':>7}")
    fold_summaries, all_items = [], []
    for k, (lo, hi) in enumerate(bounds):
        train = [r for i, r in enumerate(e2) if not lo <= i < hi]
        test = e2[lo:hi]
        t = fit_thresholds(train)
        items = to_items(test, t)
        s = summarize(items)
        fold_summaries.append(s)
        all_items += items
        print(f"{k + 1:>4} {test[0]['file'][4:8]}~{test[-1]['file'][4:8]:<5} ({len(test):>3}장) "
              f"  {t.candidate_max:.3f} / {t.review_max:.3f} {s['B']:>3} {s['B_candidate']:>4} "
              f"{s['B_review']:>4} {s['B_missed']:>4} {s['neg_candidate']:>4}/{s['neg']:<3} "
              f"{s['neg_review']:>5}/{s['neg']:<3} {s['bursts_raised']:>3}/{s['bursts']:<3}")
    pooled = merge(fold_summaries)
    ci_raised = cluster_bootstrap_ci(all_items, frame_recall_raised)
    ci_cand = cluster_bootstrap_ci(all_items, frame_recall_candidate)
    ci_burst = cluster_bootstrap_ci(all_items, burst_recall_stat)
    fp_lo, fp_hi = wilson(pooled["neg_candidate"], pooled["neg"])
    ex_lo, ex_hi = wilson(pooled["expr_candidate"], pooled["expr"])

    print("\n[E2 합산, 학습에 쓰지 않은 블록에서만 평가]")
    print(f"  눈 감김 {pooled['B']}장 (연사 묶음 {pooled['bursts']}개)")
    print(f"  장 단위 재현율 (후보 또는 확인): {pct(pooled['B_candidate'] + pooled['B_review'], pooled['B'])}"
          f"   95% 구간(묶음 부트스트랩) {ci_raised[0]:.0%}~{ci_raised[1]:.0%}")
    print(f"  장 단위 재현율 (후보만):        {pct(pooled['B_candidate'], pooled['B'])}"
          f"   95% 구간 {ci_cand[0]:.0%}~{ci_cand[1]:.0%}")
    print(f"  묶음 단위 재현율 (한 장이라도 올라온 묶음): {pct(pooled['bursts_raised'], pooled['bursts'])}"
          f"   95% 구간 {ci_burst[0]:.0%}~{ci_burst[1]:.0%}")
    print(f"  └ 좁은 눈 규칙으로 올라온 눈 감김: {pooled['B_review_small_eye']}장 (경계를 사후에 정한 규칙)")
    print(f"  놓친 눈 감김: {pooled['B_missed']}장")
    print(f"  후보 오탐: {pooled['neg_candidate']}/{pooled['neg']} ({pooled['neg_candidate'] / pooled['neg']:.2%}), "
          f"95% 구간 {fp_lo:.2%}~{fp_hi:.2%}")
    print(f"  └ 표정 주의 {pooled['expr']}장 중 후보 {pooled['expr_candidate']}장 "
          f"(95% 구간 {ex_lo:.1%}~{ex_hi:.1%}), 확인 {pooled['expr_review']}장")
    print(f"  확인 부담(정상·표정 주의 중 사람이 직접 봐야 하는 컷): {pct(pooled['neg_review'], pooled['neg'])}"
          f" (이 중 좁은 눈 {pooled['neg_review_small_eye']}장)")
    print(f"  얼굴이 없어 판정하지 않은 음성: {pooled['neg_no_face']}장")

    sensitivity(e2, e1)

    # ---- E1 새 행사 점검 -------------------------------------------------------
    final_t = fit_thresholds(e2)
    items1 = to_items(e1, final_t)
    s1 = summarize(items1)
    print(f"\n[E1 EVENT_B] E2 전체로 정한 임계값(candidate {final_t.candidate_max:.3f}, "
          f"review {final_t.review_max:.3f})을 그대로 적용")
    print(f"  최종 선택(별점 5) {s1['final_a']}장 중 후보 {s1['final_a_candidate']}장, "
          f"확인 {s1['final_a_review']}장")
    print(f"  음성 {s1['neg']}장 중 후보 오탐 {s1['neg_candidate']}장, 확인 {s1['neg_review']}장 "
          f"(좁은 눈 {s1['neg_review_small_eye']}), 얼굴 없음 {s1['neg_no_face']}장")
    print(f"  표정 주의 {s1['expr']}장 중 후보 {s1['expr_candidate']}장, 확인 {s1['expr_review']}장")
    print(f"  눈 감김 {s1['B']}장 중 후보 {s1['B_candidate']}장, 확인 {s1['B_review']}장 "
          f"(표본이 1장뿐이라 재현율은 의미 없음)")

    # ---- 합격 기준과 비교 -------------------------------------------------------
    r_raised, r_cand, r_burst = recall_raised(pooled), recall_candidate(pooled), burst_recall(pooled)
    print("\n[합격 기준과 비교 (devplan G1, 기준값은 제안값이며 본인 확정 필요)]")
    rows = [
        ("눈 감김 장 단위 재현율(후보+확인) ≥ 50% (의미) / ≥ 70% (우수)", r_raised,
         "우수" if r_raised >= 0.7 else ("의미 있음" if r_raised >= 0.5 else "미달")),
        ("눈 감김 장 단위 재현율(후보만)", r_cand,
         "우수" if r_cand >= 0.7 else ("의미 있음" if r_cand >= 0.5 else "미달")),
        ("눈 감김 묶음 단위 재현율", r_burst,
         "우수" if r_burst >= 0.7 else ("의미 있음" if r_burst >= 0.5 else "미달")),
    ]
    for name, v, verdict in rows:
        print(f"  {name}: {v:.0%} -> {verdict}")
    print(f"  최종 선택 컷이 후보로 걸린 수 (E1, 한두 장 이내): {s1['final_a_candidate']}장 -> "
          f"{'충족' if s1['final_a_candidate'] <= 2 else '미충족'}")
    print(f"  후보 오탐(E2 교차 검증, 0에 가깝게): {pooled['neg_candidate']}장/{pooled['neg']}장")

    out = {"cv_pooled": pooled, "cv_folds": fold_summaries, "e1": s1,
           "ci": {"raised": ci_raised, "candidate": ci_cand, "burst": ci_burst},
           "final_thresholds": {"candidate_max": final_t.candidate_max,
                                "review_max": final_t.review_max}}
    (HERE / "g1a_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"\n결과 저장: eval/g1a_results.json (블록별 합계는 {statistics.mean([s['n'] for s in fold_summaries]):.0f}장 안팎)")


if __name__ == "__main__":
    main()
