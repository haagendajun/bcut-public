"""임계값 보정 (`bcut calibrate`, PRD FR-05, devplan T1.12).

내 라벨(B/OK/OK_EXPR)과 `scan`이 낸 눈 점수로 눈 감김 경계 두 개를 정한다.
**목적함수: 오탐 우선 최소화, 그 다음 정탐 최대화.**

- `candidate_max`: 라벨이 정상(OK, OK_EXPR)인 컷의 **가장 낮은 점수보다 낮게**. 같은 라벨 안에서
  정상 컷이 하나도 후보로 올라가지 않는 가장 큰 값이라, 오탐 0을 지키면서 정탐이 최대가 된다.
- `review_max`: B 컷 점수의 `review_recall` 비율(기본 95%)이 들어가는 값. 후보보다 작지 않다.
- 눈이 좁아 점수를 못 믿는 컷(`small_eye`)과 읽기 실패는 학습에서 뺀다 (판정 불가 규칙이 따로 처리).

같은 입력이면 같은 출력이다 (난수·시각을 쓰지 않는다). 흔들림·초점·노출은 실제 결함 라벨이
없어서 보정하지 않고 기본값을 그대로 둔다.
**경고:** 정한 값을 같은 라벨로 평가하면 낙관적이다. 평가는 교차 검증이나 새 행사로 한다.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from bcut.scan import READ_ERROR, PhotoResult
from bcut.score.eyes import EyesThresholds

NEGATIVE = ("OK", "OK_EXPR")
POSITIVE = "B"
DEFAULT_REVIEW_RECALL = 0.95
DEFAULT_MIN_B = 10
DEFAULT_MIN_NEGATIVE = 30


class CalibrationError(ValueError):
    """보정할 수 없다 (라벨이 부족하거나 형식이 틀림)."""


@dataclass(frozen=True)
class Sample:
    score: float
    label: str  # "B" | "OK" | "OK_EXPR"


@dataclass(frozen=True)
class Calibration:
    thresholds: EyesThresholds
    n_positive: int
    n_negative: int
    candidate_recall: float  # 학습 B 중 candidate가 되는 비율 (같은 데이터라 낙관적)
    raised_recall: float  # 학습 B 중 candidate 또는 review가 되는 비율
    review_burden: int  # 학습 정상 중 review가 되는 장수
    skipped: int  # 점수를 못 믿거나 없어서 뺀 라벨 컷
    version: str  # 입력으로 정한 식별자 (같은 입력이면 같다)


def read_labels(path: Path) -> dict[str, str]:
    """라벨 CSV(file, label 열)를 읽는다. 애매(UNSURE)와 빈 라벨은 뺀다."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"file", "label"} <= set(reader.fieldnames):
            raise CalibrationError("라벨 CSV에 file, label 열이 있어야 한다")
        out: dict[str, str] = {}
        for row in reader:
            label = (row["label"] or "").strip()
            if label in (POSITIVE, *NEGATIVE):
                out[row["file"].strip()] = label
    return out


def samples_from_results(
    results: Sequence[PhotoResult], labels: dict[str, str], min_eye_width_frac: float
) -> tuple[list[Sample], int]:
    """스캔 결과와 라벨을 맞춘다. (학습 샘플, 점수를 못 믿어 뺀 라벨 컷 수)"""
    samples, skipped = [], 0
    for r in results:
        label = labels.get(r.file)
        if label is None:
            continue
        untrusted = (r.score is None or r.note == READ_ERROR
                     or (r.eye_width_frac is not None and r.eye_width_frac < min_eye_width_frac))
        if untrusted:
            skipped += 1
            continue
        samples.append(Sample(score=float(r.score), label=label))
    return samples, skipped


def fit_eyes(
    samples: Sequence[Sample], base: EyesThresholds | None = None, *,
    review_recall: float = DEFAULT_REVIEW_RECALL, min_b: int = DEFAULT_MIN_B,
    min_negative: int = DEFAULT_MIN_NEGATIVE, skipped: int = 0,
) -> Calibration:
    if not 0 < review_recall <= 1:
        raise CalibrationError("review_recall은 0보다 크고 1 이하여야 한다")
    base = base or EyesThresholds()
    pos = sorted(s.score for s in samples if s.label == POSITIVE)
    neg = sorted(s.score for s in samples if s.label in NEGATIVE)
    if len(pos) < min_b:
        raise CalibrationError(f"B 라벨이 {len(pos)}장뿐이다 (최소 {min_b}장). 라벨을 더 만든다")
    if len(neg) < min_negative:
        raise CalibrationError(f"정상 라벨이 {len(neg)}장뿐이다 (최소 {min_negative}장)")

    t_cand = neg[0] - 1e-9
    if t_cand <= 0:
        raise CalibrationError("정상 컷의 점수가 0 이하다. 라벨이나 스캔 결과를 확인한다")
    t_rev = max(float(np.quantile(pos, review_recall)), t_cand)
    thresholds = replace(base, candidate_max=t_cand, review_max=t_rev)
    digest = hashlib.sha1(
        repr(sorted((s.score, s.label) for s in samples)).encode()).hexdigest()[:8]
    return Calibration(
        thresholds=thresholds, n_positive=len(pos), n_negative=len(neg),
        candidate_recall=sum(s <= t_cand for s in pos) / len(pos),
        raised_recall=sum(s <= t_rev for s in pos) / len(pos),
        review_burden=sum(t_cand < s <= t_rev for s in neg),
        skipped=skipped, version=f"calibrated-{digest}",
    )


def render_config(cal: Calibration) -> str:
    """보정 결과를 설정 파일(TOML) 글자로 만든다. 눈 감김 경계만 적고 나머지는 기본값."""
    t = cal.thresholds
    return (
        "# bcut calibrate가 만든 설정 (눈 감김 경계만 보정, 나머지는 기본값).\n"
        f"# 라벨: B {cal.n_positive}장, 정상 {cal.n_negative}장, "
        f"점수를 못 믿어 뺀 컷 {cal.skipped}장.\n"
        f"# 같은 라벨로 잰 값(낙관적): 후보 재현율 {cal.candidate_recall:.0%}, "
        f"후보+확인 재현율 {cal.raised_recall:.0%}, 확인 부담 정상 {cal.review_burden}장.\n"
        f'config_version = "{cal.version}"\n\n'
        "[eyes]\n"
        f"candidate_max = {t.candidate_max:.6f}\n"
        f"review_max = {t.review_max:.6f}\n"
    )
