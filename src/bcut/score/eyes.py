"""눈 감김 판정: 눈 열림 비율을 두 경계로 나눠 candidate / review / normal로 분류한다.

규칙은 T1.4(경계), T1.5(판정 불가), 단체 사진 정책 결정으로 정했다
(docs/eyes-closed-experiment.md, docs/unscorable-experiment.md, docs/group-photo-policy.md).

- 점수 = 얼굴 하나에서 두 눈 중 **덜 감긴 쪽** 눈의 열림 비율 (rmax).
  두 눈이 모두 감겨야 낮아지므로 윙크·한쪽 찡그림에 덜 민감하다.
- 점수가 낮을수록 눈 감김. 점수 <= candidate 경계 이면 candidate,
  <= review 경계 이면 review, 그 위는 normal.
- **눈이 너무 좁으면(고개가 옆으로 돌아간 얼굴) 점수를 믿을 수 없다.** 이 경우 점수와 관계없이
  review로 보내고 note에 small_eye를 남긴다 (PRD FR-03: 판정 불가는 사람이 확인).
- **여러 명이 찍힌 사진 (단체 사진 정책, 2026-10-19 확정):** 가장 큰 얼굴의
  group_face_ratio(기본 0.5) 배 이상 크기인 얼굴을 모두 본다. 그중 가장 심하게 감긴 얼굴로
  사진의 등급을 정한다. 단, 비슷한 크기의 얼굴이 둘 이상이면 누가 중요한 사람인지 도구가
  모르므로 candidate로 확정하지 않고 **review**로 보낸다 (note에 group).
  작게 찍힌 뒷사람은 보지 않는다.
- 얼굴이 없거나 눈 랜드마크가 없으면 판정하지 않는다 (no_face / unscorable).

임계값은 입력 경로(CR3 내장 JPEG draft 2048)와 macOS Vision 버전에 묶여 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bcut.detect.types import Face

Status = Literal["candidate", "review", "normal", "no_face", "unscorable"]

# EVENT_A 구간(397장) 전체로 정한 기본값 (T1.5 이후 재산정, G1a 평가).
# candidate 경계는 오탐 0 기준(학습 음성보다 낮은 값), review 경계는 학습 B의 95%가 들어가는 값.
# 눈이 좁은 컷은 아래 별도 규칙이 처리하므로 경계를 정할 때 뺐다. (T1.4에서 눈이 좁은 컷까지
# 넣고 정했던 0.187은 필요 이상으로 넓었다. 교차 검증에서 95%는 확인 부담이 90%와 같으면서
# 눈 감김을 2장 더 올렸다.)
# candidate 경계는 Q7에 따라 "A 엄격"(학습 음성 중 가장 낮은 값 아래)으로 확정했다 (2026-10-19).
# 처음 3개 행사를 쓴 뒤 다시 정한다 (devplan D11). 느슨하게 하려면 이 값을 올린다.
DEFAULT_CANDIDATE_MAX = 0.134
DEFAULT_REVIEW_MAX = 0.162

# 눈 폭 / 입력 이미지 폭. 8192px 원본 기준 약 60px (분석 입력 2048px에서 약 15px).
# 놓친 눈 감김 5장은 모두 눈 폭 49px 이하였고, 52~73px 구간에는 거의 컷이 없어 경계가 안정적이다.
DEFAULT_MIN_EYE_WIDTH_FRAC = 0.0073

# 가장 큰 얼굴 면적의 몇 배 이상이면 "비슷한 크기"로 보고 함께 판정할지 (제안값, 표본이 얇다).
DEFAULT_GROUP_FACE_RATIO = 0.5

SMALL_EYE = "small_eye"
GROUP = "group"

_RANK = {"candidate": 3, "review": 2, "normal": 1}


@dataclass(frozen=True)
class EyesThresholds:
    candidate_max: float = DEFAULT_CANDIDATE_MAX
    review_max: float = DEFAULT_REVIEW_MAX
    min_eye_width_frac: float = DEFAULT_MIN_EYE_WIDTH_FRAC
    group_face_ratio: float = DEFAULT_GROUP_FACE_RATIO
    # 단체 사진에서 candidate를 review로 낮출지. 정책 3번(확정)은 True, 2번은 False.
    group_downgrades_candidate: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.candidate_max <= self.review_max:
            raise ValueError("0 < candidate_max <= review_max 이어야 한다")
        if self.min_eye_width_frac < 0:
            raise ValueError("min_eye_width_frac는 0 이상이어야 한다")
        if not 0 < self.group_face_ratio <= 1:
            raise ValueError("group_face_ratio는 0보다 크고 1 이하여야 한다")


@dataclass(frozen=True)
class EyesVerdict:
    status: Status
    score: float | None  # 등급을 정한 얼굴의 눈 열림 비율 (낮을수록 감김). 판정 못 하면 None
    face_count: int  # 검출된 얼굴 수
    note: str | None = None  # 예: "small_eye", "group"
    eye_width_frac: float | None = None
    faces_considered: int = 0  # 판정에 함께 쓴(비슷한 크기의) 얼굴 수
    # 입력 얼굴 목록에서의 위치. 리포트에 "어떤 얼굴을 보고 판정했는지" 표시하는 데 쓴다.
    considered_indices: tuple[int, ...] = ()
    deciding_index: int | None = None  # 등급을 정한 얼굴


def status_for_score(score: float, thresholds: EyesThresholds) -> Status:
    if score <= thresholds.candidate_max:
        return "candidate"
    if score <= thresholds.review_max:
        return "review"
    return "normal"


def status_for_measurements(
    score: float, eye_width_frac: float | None, thresholds: EyesThresholds
) -> tuple[Status, str | None]:
    """점수와 눈 폭 비율로 등급을 정한다. 눈이 너무 좁으면 점수와 관계없이 review."""
    if eye_width_frac is not None and eye_width_frac < thresholds.min_eye_width_frac:
        return "review", SMALL_EYE
    return status_for_score(score, thresholds), None


def eyes_score(face: Face) -> float | None:
    """덜 감긴 쪽 눈의 열림 비율. 눈 랜드마크가 하나도 없으면 None."""
    ratios = face.ratios
    return max(ratios) if ratios else None


def eye_width_fraction(face: Face) -> float | None:
    """두 눈 폭의 평균을 입력 이미지 폭으로 나눈 값. 입력 폭을 모르면 None."""
    if face.image_width_px <= 0:
        return None
    widths = [e.openness.width_px for e in (face.left, face.right) if e.openness]
    if not widths:
        return None
    return (sum(widths) / len(widths)) / face.image_width_px


def classify_eyes(faces: list[Face], thresholds: EyesThresholds | None = None) -> EyesVerdict:
    """얼굴 목록에서 비슷한 크기의 얼굴을 모두 보고 사진의 눈 감김 등급을 정한다."""
    thresholds = thresholds or EyesThresholds()
    if not faces:
        return EyesVerdict("no_face", None, 0)

    largest = max(f.face_area for f in faces)
    considered_idx = tuple(
        i for i, f in enumerate(faces) if f.face_area >= thresholds.group_face_ratio * largest
    )

    results = []  # (등급, 점수, note, 눈 폭 비율, 얼굴 위치)
    for i in considered_idx:
        score = eyes_score(faces[i])
        if score is None:
            continue
        frac = eye_width_fraction(faces[i])
        status, note = status_for_measurements(score, frac, thresholds)
        results.append((status, score, note, frac, i))

    if not results:
        return EyesVerdict("unscorable", None, len(faces), faces_considered=len(considered_idx),
                           considered_indices=considered_idx)

    # 가장 높은 등급, 같으면 더 감긴(점수가 낮은) 얼굴
    status, score, note, frac, idx = max(results, key=lambda r: (_RANK[r[0]], -r[1]))
    if status == "candidate" and len(considered_idx) > 1 and thresholds.group_downgrades_candidate:
        status, note = "review", GROUP
    return EyesVerdict(status, score, len(faces), note=note, eye_width_frac=frac,
                       faces_considered=len(considered_idx), considered_indices=considered_idx,
                       deciding_index=idx)
