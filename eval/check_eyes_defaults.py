"""기본 설정(src/bcut/score/eyes.py)이 라벨된 두 행사에서 어떻게 분류하는지 확인한다.

운영 코드(classify_eyes)를 그대로 쓴다: 점수 경계(T1.4), 눈이 좁은 얼굴 규칙(T1.5),
단체 사진 정책(비슷한 크기 얼굴을 모두 보고, 후보는 확인으로).
E2(EVENT_A)는 경계를 정하는 데 쓴 데이터라 **낙관적인 값**이다.
E1(EVENT_B)은 경계를 정할 때 쓰지 않았으므로 새 행사에서의 모습을 가늠하는 참고치다.

사용법:  python eval/check_eyes_defaults.py
"""

from __future__ import annotations

from collections import Counter

from features_io import load_event

from bcut.score.eyes import EyesThresholds, classify_eyes

SETTINGS = {
    "주 얼굴만 (옛 정책)": dict(group_face_ratio=1.0, group_downgrades_candidate=False),
    "단체 사진 정책 (확정)": dict(),
}


def run(name: str, recs: list[dict], tuned_on_this: bool, label: str, t: EyesThresholds) -> None:
    table: dict[str, Counter] = {"B": Counter(), "OK_EXPR": Counter(), "OK": Counter()}
    notes: dict[str, Counter] = {"B": Counter(), "OK_EXPR": Counter(), "OK": Counter()}
    for r in recs:
        v = classify_eyes(r["faces"], t)
        table[r["label"]][v.status] += 1
        if v.note:
            notes[r["label"]][v.note] += 1
    tag = "경계를 정한 데이터: 낙관적" if tuned_on_this else "경계에 쓰지 않은 데이터"
    print(f"\n== {name} ({tag}) / {label} ==")
    print(f"{'라벨':8} {'장수':>5} {'candidate':>10} {'review':>7} {'(좁은 눈)':>9} {'(단체)':>6} "
          f"{'normal':>7} {'no_face':>8}")
    for lab in ("B", "OK_EXPR", "OK"):
        c, n = table[lab], notes[lab]
        print(f"{lab:8} {sum(c.values()):>5} {c['candidate']:>10} {c['review']:>7} "
              f"{n['small_eye']:>9} {n['group']:>6} {c['normal']:>7} {c['no_face']:>8}")


if __name__ == "__main__":
    base = EyesThresholds()
    print(f"기본 설정: candidate <= {base.candidate_max}, review <= {base.review_max}, "
          f"눈 폭 비율 < {base.min_eye_width_frac}이면 review, "
          f"비슷한 크기 얼굴 = 가장 큰 얼굴 면적의 {base.group_face_ratio}배 이상")
    e2 = load_event("features_event_a.json", "labels_event_a.csv")
    e1 = load_event("features_event_b.json", "labels.csv")
    for label, kwargs in SETTINGS.items():
        t = EyesThresholds(**kwargs)
        run("E2 EVENT_A 구간", e2, True, label, t)
        run("E1 EVENT_B", e1, False, label, t)
