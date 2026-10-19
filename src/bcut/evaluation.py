"""평가 계산: 정탐률·오탐률·묶음 단위 재현율·신뢰구간 (devplan T1.13).

정답 라벨은 B(결함 확실), OK(정상), OK_EXPR(표정 주의)이고, 도구의 등급은
candidate / review / normal / no_face / unscorable 이다. 사진은 촬영 순서대로 넣는다.

용어
- 장 단위 재현율: 정답 B 중 도구가 candidate 또는 review로 올린 비율
- 묶음 단위 재현율: 연속 촬영한 B 컷 묶음(연속한 B) 중 한 장이라도 올라온 묶음의 비율
- 후보 오탐: 정상·표정 주의인데 candidate가 된 컷
- 확인 부담: 정상·표정 주의인데 review가 된 컷 (사람이 직접 봐야 하는 컷)
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

NEGATIVE_LABELS = ("OK", "OK_EXPR")
RAISED = ("candidate", "review")  # 사람 눈앞에 올라오는 등급


@dataclass(frozen=True)
class Item:
    file: str
    label: str  # "B" | "OK" | "OK_EXPR"
    status: str  # "candidate" | "review" | "normal" | "no_face" | "unscorable"
    note: str | None = None  # 예: "small_eye"
    final_a: bool = False  # 사용자가 최종 선택(A컷)으로 남긴 컷


def b_runs(labels: Sequence[str]) -> list[tuple[int, int]]:
    """연속한 B의 구간 (시작, 끝) 목록. 끝은 포함."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, lab in enumerate([*labels, ""]):
        if lab == "B" and start is None:
            start = i
        elif lab != "B" and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def block_bounds(labels: Sequence[str], folds: int) -> list[tuple[int, int]]:
    """시간순으로 folds개 블록의 [시작, 끝) 경계. B 묶음 한가운데가 잘리지 않게 경계를 뒤로 민다."""
    n = len(labels)
    runs = b_runs(labels)
    cuts = [round(n * k / folds) for k in range(1, folds)]
    adjusted: list[int] = []
    for cut in cuts:
        for a, b in runs:
            if a < cut <= b:  # 묶음 안에서 잘렸다 -> 묶음이 끝난 다음으로 민다
                cut = b + 1
                break
        adjusted.append(max(cut, adjusted[-1] if adjusted else 0))
    edges = [0, *adjusted, n]
    return [(edges[i], edges[i + 1]) for i in range(folds)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """비율 k/n의 윌슨 신뢰구간. n이 0이면 (0, 1)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def summarize(items: Sequence[Item]) -> dict:
    """한 번의 평가 결과를 숫자로 요약한다. items는 촬영 순서."""
    pos = [i for i, it in enumerate(items) if it.label == "B"]
    neg = [i for i, it in enumerate(items) if it.label in NEGATIVE_LABELS]
    expr = [i for i, it in enumerate(items) if it.label == "OK_EXPR"]

    def count(idx, *statuses):
        return sum(items[i].status in statuses for i in idx)

    clusters = b_runs([it.label for it in items])
    bursts_raised = sum(
        any(items[j].status in RAISED for j in range(a, b + 1)) for a, b in clusters
    )
    bursts_cand = sum(
        any(items[j].status == "candidate" for j in range(a, b + 1)) for a, b in clusters
    )
    final_a = [i for i, it in enumerate(items) if it.final_a]
    return {
        "n": len(items),
        "B": len(pos),
        "B_candidate": count(pos, "candidate"),
        "B_review": count(pos, "review"),
        "B_review_small_eye": sum(items[i].status == "review" and items[i].note == "small_eye"
                                  for i in pos),
        "B_missed": count(pos, "normal", "no_face", "unscorable"),
        "neg": len(neg),
        "neg_candidate": count(neg, "candidate"),
        "neg_review": count(neg, "review"),
        "neg_review_small_eye": sum(items[i].status == "review" and items[i].note == "small_eye"
                                    for i in neg),
        "neg_no_face": count(neg, "no_face"),
        "expr": len(expr),
        "expr_candidate": count(expr, "candidate"),
        "expr_review": count(expr, "review"),
        "bursts": len(clusters),
        "bursts_raised": bursts_raised,
        "bursts_candidate": bursts_cand,
        "final_a": len(final_a),
        "final_a_candidate": count(final_a, "candidate"),
        "final_a_review": count(final_a, "review"),
    }


def merge(summaries: Sequence[dict]) -> dict:
    """블록별 요약을 더한다 (합산 비율은 호출하는 쪽에서 계산)."""
    keys = [k for k in summaries[0] if isinstance(summaries[0][k], int)]
    return {k: sum(s[k] for s in summaries) for k in keys}


def recall_candidate(s: dict) -> float:
    return s["B_candidate"] / s["B"] if s["B"] else float("nan")


def recall_raised(s: dict) -> float:
    return (s["B_candidate"] + s["B_review"]) / s["B"] if s["B"] else float("nan")


def burst_recall(s: dict) -> float:
    return s["bursts_raised"] / s["bursts"] if s["bursts"] else float("nan")


def cluster_bootstrap_ci(
    items: Sequence[Item],
    stat: Callable[[Sequence[tuple[int, int, int]]], float],
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """B 연사 묶음을 단위로 다시 뽑아(부트스트랩) 통계량의 95% 구간을 구한다.

    같은 묶음의 컷은 거의 같아서 장 단위로 뽑으면 구간이 실제보다 좁게 나온다.
    stat은 [(묶음의 B 장수, 후보로 올라온 장수, 후보+확인으로 올라온 장수), ...]를 받는다.
    """
    clusters = b_runs([it.label for it in items])
    data = []
    for a, b in clusters:
        frames = items[a:b + 1]
        data.append((
            len(frames),
            sum(f.status == "candidate" for f in frames),
            sum(f.status in RAISED for f in frames),
        ))
    if not data:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    values = []
    for _ in range(n_boot):
        sample = [data[rng.randrange(len(data))] for _ in data]
        values.append(stat(sample))
    values.sort()
    return values[int(0.025 * n_boot)], values[int(0.975 * n_boot) - 1]


def frame_recall_raised(sample) -> float:
    total = sum(c[0] for c in sample)
    return sum(c[2] for c in sample) / total if total else float("nan")


def frame_recall_candidate(sample) -> float:
    total = sum(c[0] for c in sample)
    return sum(c[1] for c in sample) / total if total else float("nan")


def burst_recall_stat(sample) -> float:
    return sum(1 for c in sample if c[2] > 0) / len(sample) if sample else float("nan")
