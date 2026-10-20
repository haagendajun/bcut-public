"""T1.6 실험: 얼굴 영역의 선명도를 풀 해상도에서 재면 가벼운 흔들림도 구분되는가.

입력: eval/facefull_*.json (tools/extract_face_sharpness_fullres.py 결과)
- real: 실제 사진 (사용자가 100% 확대까지 확인해 흔들림·초점 결함이 없다고 본 컷). 잡으면 오탐.
- gauss2/4/8, motion8/16/32: 같은 얼굴 영역을 풀 해상도 기준으로 인위적으로 흐리게 한 것.
  (풀 해상도에서 sigma 2~8, 번짐 8~32픽셀은 100% 확대에서 분명히 보이는 흐림이다.)

사용법:  python eval/analyze_face_fullres.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
GROUP_RATIO = 0.5
VARIANTS = ["gauss2", "gauss4", "gauss8", "motion8", "motion16", "motion32"]


def load(name: str) -> list[dict]:
    return [r for r in json.loads((HERE / name).read_text(encoding="utf-8"))
            if r["label"] != "UNSURE" and r["faces"]]


def worst(rec: dict, variant: str, key: str = "blur") -> float | None:
    """판정에 쓰는(비슷한 크기의) 얼굴 중 가장 흐린 값."""
    faces = rec["faces"]
    biggest = max(f["area"] for f in faces)
    vals = [f["variants"][variant][key] for f in faces
            if f["area"] >= GROUP_RATIO * biggest and f["variants"][variant][key] is not None]
    return max(vals) if vals else None


def q(vals, qs=(0, 1, 5, 50, 95, 99, 100)):
    v = np.asarray([x for x in vals if x is not None], dtype=float)
    return " / ".join(f"{np.percentile(v, p):.3f}" for p in qs)


def main() -> None:
    events = {"E2 EVENT_A": load("facefull_event_a.json"), "E1 EVENT_B": load("facefull_event_b.json")}
    allr = [r for rs in events.values() for r in rs]
    print("== 1. 실제 사진의 얼굴 흐림 분포, 풀 해상도 (최소 / 1% / 5% / 중앙 / 95% / 99% / 최대) ==")
    for name, rs in events.items():
        print(f"[{name}] 얼굴 있는 사진 {len(rs)}장")
        print(f"  가로·세로 (2방향): {q([worst(r, 'real') for r in rs])}")
        print(f"  대각선 포함 (4방향): {q([worst(r, 'real', 'blur4') for r in rs])}")
        px = [max(f['variants']['real']['px'] for f in r['faces']) for r in rs]
        print(f"  측정한 얼굴 안쪽 영역 폭(px): 중앙 {np.median(px):.0f}, 최소 {min(px)}")

    print("\n== 2. 합성 흐림의 분포 (E2+E1, 2방향, 중앙 [5%~95%]) ==")
    for v in ["real"] + VARIANTS:
        vals = [worst(r, v) for r in allr]
        arr = np.asarray([x for x in vals if x is not None])
        print(f"  {v:9} {np.median(arr):.3f} [{np.percentile(arr, 5):.3f} ~ {np.percentile(arr, 95):.3f}]")
    print("   (대각선 포함 4방향)")
    for v in ["real"] + VARIANTS:
        vals = [worst(r, v, "blur4") for r in allr]
        arr = np.asarray([x for x in vals if x is not None])
        print(f"  {v:9} {np.median(arr):.3f} [{np.percentile(arr, 5):.3f} ~ {np.percentile(arr, 95):.3f}]")

    print("\n== 3. 규칙 후보: 얼굴 흐림 >= T (오탐=실제 사진에서 걸리는 수, 재현율=흐리게 만든 얼굴 중 걸리는 비율) ==")
    for key, title in (("blur", "가로·세로 (2방향)"), ("blur4", "대각선 포함 (4방향)")):
        print(f"\n[{title}]")
        print(f"{'T':>6} {'오탐 EVENT_A':>11} {'오탐 EVENT_B':>12} | " + " ".join(f"{v:>8}" for v in VARIANTS))
        reals = {n: [worst(r, "real", key) for r in rs] for n, rs in events.items()}
        top = max(x for v in reals.values() for x in v if x is not None)
        ts = sorted(set(round(t, 2) for t in np.arange(0.5, 1.0, 0.05)))
        for t in ts:
            fp = [f"{sum(1 for x in reals[n] if x is not None and x >= t)}/{len(reals[n])}" for n in events]
            rec = []
            for v in VARIANTS:
                vals = [worst(r, v, key) for r in allr]
                vals = [x for x in vals if x is not None]
                rec.append(f"{sum(1 for x in vals if x >= t) / len(vals):>7.0%}")
            print(f"{t:>6.2f} {fp[0]:>11} {fp[1]:>12} | " + " ".join(f"{x:>8}" for x in rec))
        print(f"  (실제 사진의 최댓값 {top:.3f})")


if __name__ == "__main__":
    main()
