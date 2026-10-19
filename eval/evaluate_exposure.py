"""T1.17 평가: 노출 판정(운영 코드 classify_exposure)의 오탐과 합성 재현율.

- **오탐**: 실제 사진은 사용자가 100% 확대까지 확인해 노출 결함이 없다고 본 컷이다
  (눈 감김 B, 표정 주의, 정상, 최종 선택). 판정기가 잡으면 모두 오탐이다.
- **합성 재현율**: 같은 사진의 노출을 인위적으로 바꿔(EV -3 ~ +3) 얼마나 잡는지 본다.
  실제 노출 결함이 아니므로 **경향**이다 (합격 판정에 쓰지 않는다, recall-eval-plan.md).
- **행사 간 이동 점검**: 한 행사의 사진만으로 경계를 정했다면 다른 행사에서 어떻게 되는지.

사진은 읽기만 한다. 사람이 열어 보지 않고 숫자만 본다. 네트워크를 쓰지 않는다.

사용법:  python eval/evaluate_exposure.py
"""

from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bcut.detect.exposure import to_gray
from bcut.detect.vision_face import detect_faces
from bcut.evaluation import wilson
from bcut.imageio import read_embedded_jpeg
from bcut.score.exposure import ExposureThresholds, classify_exposure
from bcut.synth import shift_exposure

HERE = Path(__file__).parent
DATA = Path.home() / "photo-select-data" / "events"
EVENTS = {
    "E2 EVENT_A": (DATA / "260223_EVENT_A_seg400", "labels_event_a.csv"),
    "E1 EVENT_B": (DATA / "260212_EVENT_B_STRX_SJ", "labels.csv"),
}
SYNTH_EVS = (-3.0, -2.0, -1.5, -1.0, 1.0, 1.5, 2.0, 3.0)


def _analyze(job: tuple[str, str, str, str, bool]) -> dict:
    event, path, file, label, final_a = job
    t = ExposureThresholds()
    loaded = read_embedded_jpeg(Path(path))
    faces = detect_faces(loaded.image)
    v0 = classify_exposure(to_gray(loaded.image), faces, t)
    out = {"event": event, "file": file, "label": label, "final_a": final_a,
           "has_face": v0.faces_considered > 0, "real": {"flagged": v0.flagged, "kind": v0.kind,
                                                         "p99": v0.global_p99, "face_hi": v0.face_hi},
           "synth": {}}
    for ev in SYNTH_EVS:
        v = classify_exposure(to_gray(shift_exposure(loaded.image, ev)), faces, t)
        out["synth"][f"{ev:g}"] = {"flagged": v.flagged, "kind": v.kind}
    return out


def pct(k: int, n: int) -> str:
    return f"{k / n:.0%}" if n else "-"


def main() -> None:
    jobs = []
    for event, (folder, labels) in EVENTS.items():
        for r in csv.DictReader((HERE / labels).open(encoding="utf-8")):
            if r["label"] != "UNSURE":
                jobs.append((event, str(folder / r["file"]), r["file"], r["label"],
                             r.get("is_final_a") == "1"))
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=6) as pool:
        recs = list(pool.map(_analyze, jobs, chunksize=4))
    print(f"실제 사진 {len(recs)}장을 읽어 운영 코드로 판정했다 ({time.perf_counter() - t0:.0f}초)")
    t = ExposureThresholds()
    print(f"기본 경계: 얼굴 날아간 비율 >= {t.face_hi_frac:.0%} (얼굴 없으면 사진 전체 >= {t.global_hi_frac:.0%}), "
          f"사진 상위 1% 밝기 <= {t.dark_p99:.0f}")

    # ---- 1. 오탐 -------------------------------------------------------------
    print("\n== 1. 오탐: 실제 사진 중 노출 이상으로 걸린 컷 (모두 오탐) ==")
    print(f"{'행사':10} {'라벨':8} {'장수':>5} {'걸림':>5}")
    for event in EVENTS:
        for label in ("B", "OK_EXPR", "OK"):
            rs = [r for r in recs if r["event"] == event and r["label"] == label]
            print(f"{event:10} {label:8} {len(rs):>5} {sum(r['real']['flagged'] for r in rs):>5}")
    flagged = [r for r in recs if r["real"]["flagged"]]
    n = len(recs)
    lo, hi = wilson(len(flagged), n)
    print(f"\n  전체: {len(flagged)}/{n} 걸림 ({len(flagged) / n:.2%}), 95% 신뢰구간 {lo:.2%} ~ {hi:.2%}")
    finals = [r for r in recs if r["final_a"]]
    print(f"  최종 선택(별점 5) {len(finals)}장 중 걸림: {sum(r['real']['flagged'] for r in finals)}장")
    exprs = [r for r in recs if r["label"] == "OK_EXPR"]
    print(f"  표정 주의 {len(exprs)}장 중 걸림: {sum(r['real']['flagged'] for r in exprs)}장")
    faced = [r for r in recs if r["has_face"]]
    print(f"  얼굴 있는 사진 {len(faced)}장 중 걸림 {sum(r['real']['flagged'] for r in faced)}, "
          f"얼굴 없는 사진 {n - len(faced)}장 중 걸림 {sum(r['real']['flagged'] for r in recs if not r['has_face'])}")
    if flagged:
        print("  걸린 컷:", [(r["file"], r["real"]["kind"]) for r in flagged][:10])

    # 여유(마진): 정상 컷이 경계에서 얼마나 떨어져 있나
    p99s = [r["real"]["p99"] for r in recs]
    his = [r["real"]["face_hi"] for r in recs if r["real"]["face_hi"] is not None]
    print(f"\n  경계와의 여유: 실제 사진의 사진 상위 1% 밝기 최소 {min(p99s):.0f} (경계 {t.dark_p99:.0f}), "
          f"얼굴 날아간 비율 최대 {max(his):.1%} (경계 {t.face_hi_frac:.0%})")

    # ---- 2. 합성 재현율 -------------------------------------------------------
    print("\n== 2. 합성 재현율: 노출을 인위적으로 바꾼 사진 중 걸린 비율 (경향, 합격 판정 아님) ==")
    print(f"{'EV':>6} {'전체':>6} {'EVENT_A':>7} {'EVENT_B':>7} {'얼굴있음':>8} {'얼굴없음':>8}   이유")
    for ev in SYNTH_EVS:
        key = f"{ev:g}"
        rate = lambda rs, key=key: pct(sum(r["synth"][key]["flagged"] for r in rs), len(rs))  # noqa: E731
        kinds = Counter(r["synth"][key]["kind"] for r in recs if r["synth"][key]["flagged"])
        print(f"{ev:>+6.1f} {rate(recs):>6} {rate([r for r in recs if r['event'] == 'E2 EVENT_A']):>7} "
              f"{rate([r for r in recs if r['event'] == 'E1 EVENT_B']):>7} "
              f"{rate([r for r in recs if r['has_face']]):>8} {rate([r for r in recs if not r['has_face']]):>8}   "
              f"{dict(kinds)}")

    # ---- 3. 행사 간 이동 점검 --------------------------------------------------
    print("\n== 3. 행사 간 이동 점검: 한 행사의 사진만으로 경계를 정했다면? ==")
    print("   규칙: 저노출 경계 = 그 행사의 실제 사진 상위 1% 밝기 최소값 x 0.875, 과노출 경계 = 얼굴 날아간 비율 최대 x 1.77")
    print("   (현재 기본값 120과 20%는 두 행사의 합집합에서 같은 비율로 정했다: 137 x 0.875, 11.3% x 1.77)")
    by_event = defaultdict(list)
    for r in recs:
        by_event[r["event"]].append(r)
    for src, dst in (("E2 EVENT_A", "E1 EVENT_B"), ("E1 EVENT_B", "E2 EVENT_A")):
        s_p99 = min(r["real"]["p99"] for r in by_event[src])
        s_hi = max((r["real"]["face_hi"] or 0) for r in by_event[src])
        t_under, t_over = s_p99 * 0.875, s_hi * 1.77
        d = by_event[dst]
        fp_under = sum(r["real"]["p99"] <= t_under for r in d)
        fp_over = sum((r["real"]["face_hi"] or 0) >= t_over for r in d)
        print(f"   {src}만으로 정한 경계(저노출 {t_under:.0f}, 과노출 {t_over:.1%}) -> {dst} 오탐: "
              f"저노출 {fp_under}/{len(d)}, 과노출 {fp_over}/{len(d)}")

    (HERE / "exposure_results.json").write_text(json.dumps(
        {"real_flagged": len(flagged), "n": n, "wilson": [lo, hi]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
