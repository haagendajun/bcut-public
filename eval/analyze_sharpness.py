"""T1.6·T1.7 실험: 선명도 신호의 분포와 흔들림·초점 판정 경계 선택.

입력: eval/sharpness_*.json (tools/extract_sharpness_features.py 결과)
- 실제 사진(real)은 사용자가 100% 확대까지 확인해 흔들림·초점 결함이 없다고 본 컷들이다
  (눈 감김 B와 표정 주의 포함, 애매 제외). 즉 **판정기가 잡으면 모두 오탐**이다.
- 합성은 같은 사진을 인위적으로 흐리게 만든 것이다. 경향을 보는 용도다.

신호 (모두 0~1, 클수록 흐리다):
  face   판정에 쓰는 얼굴 안쪽 영역의 흐림 (비슷한 크기 얼굴 중 가장 흐린 것)
  best   사진에서 가장 선명한 타일 쪽의 흐림 (타일 흐림의 하위 10% 지점). "사진 어디에도
         선명한 곳이 없다"를 볼 때 쓴다. 배경이 보케인 인물 사진도 얼굴 쪽 타일이 선명하다.
  global 사진 전체를 한 덩어리로 잰 흐림 (비교용. 보케 배경에 약하다)

사용법:  python eval/analyze_sharpness.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
GROUP_RATIO = 0.5
REAL = "real"
VARIANTS_SHAKE = ["gauss1", "gauss2", "gauss3", "gauss5", "motion8", "motion16", "motion32"]
VARIANTS_FACE = ["face2", "face4", "face8"]


def load(name: str) -> list[dict]:
    return [r for r in json.loads((HERE / name).read_text(encoding="utf-8")) if r["label"] != "UNSURE"]


def signals(variant: dict) -> dict:
    tiles = variant["tiles"]
    faces = [f for f in variant["faces"] if f["blur"] is not None]
    out = {
        "global": variant["global"],
        "best": tiles[int(0.10 * len(tiles))] if tiles else None,
        "tiles_n": variant["tiles_n"],
        "face": None, "face_main": None, "has_face": False,
    }
    if faces:
        biggest = max(f["area"] for f in faces)
        considered = [f for f in faces if f["area"] >= GROUP_RATIO * biggest]
        out["face"] = max(f["blur"] for f in considered)
        out["face_main"] = max(faces, key=lambda f: f["area"])["blur"]
        out["has_face"] = True
    return out


def q(values, qs=(0, 1, 5, 50, 95, 99, 100)):
    v = np.asarray([x for x in values if x is not None], dtype=float)
    return [float(np.percentile(v, p)) for p in qs] if len(v) else [float("nan")] * len(qs)


def fmt(values, d=3):
    return " / ".join(f"{x:.{d}f}" for x in values)


def main() -> None:
    events = {"E2 EVENT_A": load("sharpness_event_a.json"), "E1 EVENT_B": load("sharpness_event_b.json")}
    print("== 1. 실제 사진의 분포 (최소 / 1% / 5% / 중앙 / 95% / 99% / 최대, 클수록 흐림) ==")
    for name, recs in events.items():
        sig = [signals(r["variants"][REAL]) for r in recs]
        faced = [s for s in sig if s["has_face"]]
        print(f"\n[{name}] {len(sig)}장 (얼굴 {len(faced)}장, 얼굴 없음 {len(sig) - len(faced)}장), "
              f"유효 타일 수 중앙값 {np.median([s['tiles_n'] for s in sig]):.0f}")
        print(f"  가장 선명한 타일 쪽 흐림(best)  {fmt(q([s['best'] for s in sig]))}")
        print(f"  사진 전체 흐림(global)          {fmt(q([s['global'] for s in sig]))}")
        print(f"  얼굴 흐림(face, 가장 흐린 얼굴)  {fmt(q([s['face'] for s in faced]))}")
        nf = [s for s in sig if not s["has_face"]]
        if nf:
            print(f"  얼굴 없는 사진의 best           {fmt(q([s['best'] for s in nf]))}")

    print("\n== 2. 합성 흐림에 따른 신호의 중앙값과 5~95% 범위 (E2+E1 전체) ==")
    allrecs = events["E2 EVENT_A"] + events["E1 EVENT_B"]
    print(f"{'변형':10} {'best 중앙 [5%~95%]':>24} {'global 중앙':>12} {'face 중앙 [5%~95%]':>24}")
    for v in [REAL] + VARIANTS_SHAKE + VARIANTS_FACE:
        sig = [signals(r["variants"][v]) for r in allrecs if v in r["variants"]]
        b = q([s["best"] for s in sig], (5, 50, 95))
        g = q([s["global"] for s in sig], (50,))
        f = q([s["face"] for s in sig if s["has_face"]], (5, 50, 95))
        print(f"{v:10} {b[1]:>8.3f} [{b[0]:.3f}~{b[2]:.3f}] {g[0]:>12.3f} {f[1]:>8.3f} [{f[0]:.3f}~{f[2]:.3f}]")


def sweep(title, rules, variants, recs, only_face=None):
    """오탐(실제 사진에서 걸리는 수)과 변형별 재현율."""
    print(f"\n{title}")
    print(f"{'규칙':34} {'오탐 EVENT_A':>10} {'오탐 EVENT_B':>11} | " + " ".join(f"{v:>8}" for v in variants))
    for name, fn in rules:
        fp = []
        for rs in recs.values():
            sig = [signals(r["variants"][REAL]) for r in rs]
            if only_face is not None:
                sig = [s for s in sig if s["has_face"] == only_face]
            fp.append(f"{sum(1 for s in sig if fn(s))}/{len(sig)}")
        rec = []
        allr = [r for rs in recs.values() for r in rs]
        for v in variants:
            sig = [signals(r["variants"][v]) for r in allr if v in r["variants"]]
            if only_face is not None:
                sig = [s for s in sig if s["has_face"] == only_face]
            rec.append(f"{sum(1 for s in sig if fn(s)) / len(sig):>7.0%}" if sig else "   -")
        print(f"{name:34} {fp[0]:>10} {fp[1]:>11} | " + " ".join(f"{x:>8}" for x in rec))


def sweeps() -> None:
    recs = {"E2": load("sharpness_event_a.json"), "E1": load("sharpness_event_b.json")}
    ok = lambda x: x is not None  # noqa: E731
    print("\n\n######## 규칙 후보 (오탐=실제 사진에서 걸리는 수, 재현율=흐리게 만든 사진 중 걸리는 비율) ########")
    sweep("[흔들림/전체 흐림] 사진 어디에도 선명한 곳이 없다: best >= T",
          [(f"best >= {t}", lambda s, t=t: ok(s["best"]) and s["best"] >= t)
           for t in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)], VARIANTS_SHAKE, recs)
    sweep("[비교] 사진 전체 흐림: global >= T",
          [(f"global >= {t}", lambda s, t=t: ok(s["global"]) and s["global"] >= t)
           for t in (0.65, 0.70, 0.75, 0.80, 0.85)], VARIANTS_SHAKE, recs)
    sweep("[얼굴이 흐리다] face >= T (얼굴 있는 사진)",
          [(f"face >= {t}", lambda s, t=t: ok(s["face"]) and s["face"] >= t)
           for t in (0.65, 0.70, 0.75, 0.80, 0.85, 0.90)], VARIANTS_SHAKE + VARIANTS_FACE, recs, True)
    sweep("[초점 실패] 얼굴은 흐린데 어딘가는 선명하다: face >= Tf and best <= Tb",
          [(f"face>={tf} and best<={tb}",
            lambda s, tf=tf, tb=tb: ok(s["face"]) and ok(s["best"]) and s["face"] >= tf and s["best"] <= tb)
           for tf, tb in ((0.70, 0.55), (0.75, 0.55), (0.80, 0.55), (0.75, 0.60), (0.80, 0.60))],
          VARIANTS_FACE + ["gauss2", "gauss3"], recs, True)
    sweep("[얼굴 없는 사진] best >= T", [(f"best >= {t}", lambda s, t=t: ok(s["best"]) and s["best"] >= t)
                                  for t in (0.60, 0.65, 0.70, 0.75)], ["gauss2", "gauss3", "gauss5", "motion16", "motion32"],
          recs, False)


if __name__ == "__main__":
    main()
    sweeps()
