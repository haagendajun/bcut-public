"""T1.6·T1.7 평가: 운영 코드(classify_sharpness)로 오탐과 합성 재현율을 잰다.

- 오탐: 실제 사진(100% 확대로 흔들림·초점 결함 없음 확인) 중 걸리는 수. 0이어야 한다.
- 재현율: 합성으로 흐리게 만든 사진 중 걸리는 비율. **경향만** 본다 (실제 결함이 아니다).
  전체 흐림(gauss/motion, 분석 입력 기준 픽셀)은 best 규칙, 얼굴 흐림(풀 해상도 기준)은 얼굴 규칙.
입력: eval/sharpness2_*.json (2방향 지표, extract_sharpness_features) + eval/facefull_*.json

사용법:  python eval/evaluate_sharpness.py
"""

from __future__ import annotations

import json
from pathlib import Path

from bcut.score.sharpness import FaceBlur, SharpnessThresholds, classify_sharpness

HERE = Path(__file__).parent
T = SharpnessThresholds()
GLOBAL_VARIANTS = ["gauss1", "gauss2", "gauss3", "gauss5", "motion8", "motion16", "motion32"]
FACE_VARIANTS = ["gauss2", "gauss4", "gauss8", "motion8", "motion16", "motion32"]


def load(name: str) -> dict[str, dict]:
    return {r["file"]: r for r in json.loads((HERE / name).read_text(encoding="utf-8"))
            if r["label"] != "UNSURE"}


def best_of(variant: dict) -> float | None:
    tiles = variant["tiles"]
    return tiles[int(0.10 * len(tiles))] if tiles else None


def face_blurs(rec: dict, variant: str) -> list[FaceBlur]:
    return [FaceBlur(area=f["area"], blur=f["variants"][variant]["blur"], px=f["variants"][variant]["px"])
            for f in rec["faces"]]


def main() -> None:
    events = {"EVENT_A": ("sharpness2_event_a.json", "facefull_event_a.json"),
              "EVENT_B": ("sharpness2_event_b.json", "facefull_event_b.json")}
    print(f"임계값: {T}\n")
    tot = 0
    for name, (sh, ff) in events.items():
        sdata, fdata = load(sh), load(ff)
        fp_kinds = {"blur": 0, "out_of_focus": 0}
        flagged_files = []
        for f, srec in sdata.items():
            frec = fdata.get(f)
            faces = face_blurs(frec, "real") if frec else []
            v = classify_sharpness(best_of(srec["variants"]["real"]), faces, T)
            if v.flagged:
                fp_kinds[v.kind] += 1
                flagged_files.append((f, v.kind, v.best, v.face_blur, v.face_px))
        tot += sum(fp_kinds.values())
        print(f"[{name}] 실제 {len(sdata)}장 오탐 {fp_kinds} {flagged_files}")
    print(f"오탐 합계 {tot}\n")

    allS = {**load("sharpness2_event_a.json"), **load("sharpness2_event_b.json")}
    allF = {**load("facefull_event_a.json"), **load("facefull_event_b.json")}
    print("합성 전체 흐림 재현율 (best 규칙, 얼굴 규칙 없이):")
    for v in GLOBAL_VARIANTS:
        n = hit = 0
        for rec in allS.values():
            if v not in rec["variants"]:
                continue
            n += 1
            hit += classify_sharpness(best_of(rec["variants"][v]), [], T).flagged
        print(f"  {v:9} {hit}/{n} = {hit / n:.0%}")
    print("\n합성 얼굴 흐림 재현율 (얼굴 규칙, 대상=얼굴 폭 충분한 사진만, 얼굴 있는 사진 대비 적용 비율도 표시):")
    for v in FACE_VARIANTS:
        n = hit = applicable = 0
        for rec in allF.values():
            n += 1
            fb = face_blurs(rec, v)
            res = classify_sharpness(None, fb, T)
            applicable += res.faces_considered > 0
            hit += res.flagged
        print(f"  {v:9} 전체 대비 {hit}/{n} = {hit / n:.0%}, 규칙 적용 가능 {applicable}장 중 {hit / applicable:.0%}")


if __name__ == "__main__":
    main()
