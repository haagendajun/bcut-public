"""T1.17 실험: 노출 신호의 분포와 노출 판정 경계 선택.

입력: eval/exposure_*.json (tools/extract_exposure_features.py 결과)
- 실제 사진(EV 0)은 사용자가 100% 확대까지 확인해 노출 결함이 없다고 본 컷들이다
  (눈 감김 B와 표정 주의 포함, 애매 제외). 즉 **판정기가 잡으면 모두 오탐**이다.
- 합성(EV -3 ~ +3)은 같은 사진의 노출을 인위적으로 바꾼 것이다. 경향을 보는 용도다.

사용법:  python eval/analyze_exposure.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
GROUP_RATIO = 0.5  # 눈 감김 판정과 같은 기준: 가장 큰 얼굴 면적의 이 비율 이상인 얼굴을 함께 본다


def load(name: str) -> list[dict]:
    recs = json.loads((HERE / name).read_text(encoding="utf-8"))
    return [r for r in recs if r["label"] != "UNSURE"]


def considered_faces(variant: dict) -> list[dict]:
    """통계가 있는 얼굴 중 가장 큰 얼굴과 비슷한 크기인 것."""
    faces = [f for f in variant["faces"] if f["stats"] is not None]
    if not faces:
        return []
    biggest = max(f["area"] for f in faces)
    return [f for f in faces if f["area"] >= GROUP_RATIO * biggest]


def signals(variant: dict) -> dict:
    """한 사진(한 노출 상태)의 판정 신호."""
    g = variant["global"]
    faces = considered_faces(variant)
    out = {
        "g_median": g["median"], "g_mean": g["mean"], "g_hi": g["frac_hi"], "g_lo": g["frac_lo"],
        "g_p1": g["p1"], "g_p99": g["p99"],
        "has_face": bool(faces),
    }
    if faces:
        means = [f["stats"]["mean"] for f in faces]
        out |= {
            "f_mean_min": min(means), "f_mean_max": max(means),
            "f_hi_max": max(f["stats"]["frac_hi"] for f in faces),
            "f_lo_max": max(f["stats"]["frac_lo"] for f in faces),
            "f_p99_max": max(f["stats"]["p99"] for f in faces),
            "f_p1_min": min(f["stats"]["p1"] for f in faces),
        }
    return out


def quantiles(values, qs=(0, 1, 5, 50, 95, 99, 100)):
    v = np.asarray([x for x in values if x is not None])
    return [float(np.percentile(v, q)) for q in qs] if len(v) else [float("nan")] * len(qs)


def fmt(q, digits=1):
    return " / ".join(f"{x:.{digits}f}" for x in q)


def main() -> None:
    events = {"E2 EVENT_A": load("exposure_event_a.json"), "E1 EVENT_B": load("exposure_event_b.json")}
    real = {n: [signals(r["variants"]["0"]) for r in recs] for n, recs in events.items()}

    print("== 1. 실제 사진의 분포 (최소 / 1% / 5% / 중앙 / 95% / 99% / 최대) ==")
    for name, sig in real.items():
        faced = [s for s in sig if s["has_face"]]
        print(f"\n[{name}] 사진 {len(sig)}장, 얼굴 있음 {len(faced)}장, 얼굴 없음 {len(sig) - len(faced)}장")
        print(f"  사진 전체 중앙 밝기      {fmt(quantiles([s['g_median'] for s in sig]))}")
        print(f"  사진 전체 날아간 비율(%) {fmt(quantiles([s['g_hi'] * 100 for s in sig]), 2)}")
        print(f"  사진 전체 뭉개진 비율(%) {fmt(quantiles([s['g_lo'] * 100 for s in sig]), 2)}")
        if faced:
            print(f"  얼굴 평균 밝기 (가장 어두운 얼굴)  {fmt(quantiles([s['f_mean_min'] for s in faced]))}")
            print(f"  얼굴 평균 밝기 (가장 밝은 얼굴)    {fmt(quantiles([s['f_mean_max'] for s in faced]))}")
            print(f"  얼굴 날아간 비율(%) (최대)         {fmt(quantiles([s['f_hi_max'] * 100 for s in faced]), 2)}")
            print(f"  얼굴 뭉개진 비율(%) (최대)         {fmt(quantiles([s['f_lo_max'] * 100 for s in faced]), 2)}")

    print("\n== 2. 합성 노출 변화에 따른 얼굴 평균 밝기 (얼굴 있는 사진의 중앙값, E2+E1) ==")
    evs = ["-3", "-2", "-1.5", "-1", "0", "1", "1.5", "2", "3"]
    allrecs = events["E2 EVENT_A"] + events["E1 EVENT_B"]
    print(f"{'EV':>6} {'얼굴 밝기 중앙':>12} {'얼굴 밝기 5%':>12} {'95%':>6} {'얼굴 날아간(%) 95%':>16} {'얼굴 뭉개진(%) 95%':>16} {'사진 중앙 밝기':>12}")
    for ev in evs:
        sig = [signals(r["variants"][ev]) for r in allrecs]
        faced = [s for s in sig if s["has_face"]]
        fm = [s["f_mean_max"] for s in faced]
        print(f"{ev:>6} {np.median(fm):>12.1f} {np.percentile(fm, 5):>12.1f} {np.percentile(fm, 95):>6.1f} "
              f"{np.percentile([s['f_hi_max'] * 100 for s in faced], 95):>16.2f} "
              f"{np.percentile([s['f_lo_max'] * 100 for s in faced], 95):>16.2f} "
              f"{np.median([s['g_median'] for s in sig]):>12.1f}")


if __name__ == "__main__":
    main()


# ---- 규칙 후보 훑기 ----------------------------------------------------------

EVS_OVER = ["1", "1.5", "2", "3"]
EVS_UNDER = ["-1", "-1.5", "-2", "-3"]


def sweep(title, rules, evs, recs_by_event, want_face):
    """rules: [(이름, 판정 함수(신호) -> bool)]. 실제 사진에서 걸리는 수(오탐)와 합성에서 걸리는 비율."""
    print(f"\n{title}")
    print(f"{'규칙':34} {'오탐 EVENT_A':>10} {'오탐 EVENT_B':>11} | " + " ".join(f"{'EV ' + e:>7}" for e in evs))
    allrecs = [r for recs in recs_by_event.values() for r in recs]
    for name, fn in rules:
        fp = []
        for recs in recs_by_event.values():
            sig = [signals(r["variants"]["0"]) for r in recs]
            sig = [s for s in sig if s["has_face"] == want_face]
            fp.append(f"{sum(1 for s in sig if fn(s))}/{len(sig)}")
        rec = []
        for ev in evs:
            sig = [signals(r["variants"][ev]) for r in allrecs]
            sig = [s for s in sig if s["has_face"] == want_face]
            rec.append(f"{sum(1 for s in sig if fn(s)) / len(sig):>6.0%}")
        print(f"{name:34} {fp[0]:>10} {fp[1]:>11} | " + " ".join(f"{x:>7}" for x in rec))


def sweeps() -> None:
    ev = {"E2": load("exposure_event_a.json"), "E1": load("exposure_event_b.json")}
    print("\n\n######## 규칙 후보 훑기 (오탐은 실제 사진에서 걸리는 수, 합성은 노출을 바꾼 사진 중 걸리는 비율) ########")
    sweep("[과노출] 얼굴이 있는 사진", [(f"얼굴 날아간 비율 >= {t:.0%}", lambda s, t=t: s["f_hi_max"] >= t)
                                  for t in (0.15, 0.20, 0.25, 0.30, 0.40, 0.50)], EVS_OVER, ev, True)
    sweep("[과노출] 얼굴 평균 밝기", [(f"얼굴 평균 밝기 >= {t}", lambda s, t=t: s["f_mean_max"] >= t)
                              for t in (215, 225, 235)], EVS_OVER, ev, True)
    sweep("[과노출] 얼굴 없는 사진 (사진 전체)", [(f"전체 날아간 비율 >= {t:.0%}", lambda s, t=t: s["g_hi"] >= t)
                                      for t in (0.20, 0.30, 0.40, 0.50)], EVS_OVER, ev, False)
    sweep("[저노출] 얼굴 평균 밝기", [(f"얼굴 평균 밝기 <= {t}", lambda s, t=t: s["f_mean_min"] <= t)
                              for t in (15, 20, 25, 30, 40)], EVS_UNDER, ev, True)
    sweep("[저노출] 얼굴의 가장 밝은 부분(99%)", [(f"얼굴 99% 밝기 <= {t}", lambda s, t=t: s["f_p99_max"] <= t)
                                        for t in (40, 60, 80, 100)], EVS_UNDER, ev, True)
    sweep("[저노출] 사진 전체의 가장 밝은 부분(99%)", [(f"전체 99% 밝기 <= {t}", lambda s, t=t: s["g_p99"] <= t)
                                         for t in (60, 80, 100, 120)], EVS_UNDER, ev, True)
    sweep("[저노출] 얼굴 없는 사진: 전체 99% 밝기", [(f"전체 99% 밝기 <= {t}", lambda s, t=t: s["g_p99"] <= t)
                                         for t in (40, 60, 80, 100)], EVS_UNDER, ev, False)
    sweep("[저노출] 얼굴 없는 사진: 전체 중앙 밝기", [(f"전체 중앙 밝기 <= {t}", lambda s, t=t: s["g_median"] <= t)
                                         for t in (10, 20, 30, 40)], EVS_UNDER, ev, False)


if __name__ == "__main__":
    sweeps()
