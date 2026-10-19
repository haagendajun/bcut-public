"""평가 스크립트 공통: 저장된 눈 특징(JSON)과 라벨(CSV)을 읽어 실제 분류 코드에 넣을 수 있게 만든다.

features_*.json 의 얼굴 정보로 `bcut.detect.types.Face`를 다시 만들어, 평가가 운영 코드
(`bcut.score.eyes.classify_eyes`)를 그대로 쓰게 한다.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from bcut.detect.eyes import EyeOpenness
from bcut.detect.types import Eye, Face

HERE = Path(__file__).parent
FULL_WIDTH = 8192  # 내장 JPEG 폭
INPUT_WIDTH = 2048  # 분석 입력 폭
SCALE = FULL_WIDTH / INPUT_WIDTH


def _eye(ratio: float | None, width_px: float | None) -> Eye:
    if ratio is None:
        return Eye(openness=None, pupil=None, points=())
    return Eye(openness=EyeOpenness(ratio=ratio, width_px=width_px or 0.0), pupil=None, points=())


def to_face(f: dict) -> Face:
    """저장된 얼굴 특징 한 건을 Face로 되살린다 (눈 폭은 두 눈 평균을 양쪽에 같게 둔다)."""
    width_in = f["eye_w_full"] / SCALE if f.get("eye_w_full") else None
    return Face(
        face_width_px=f["face_w_full"] / SCALE,
        face_area=f["face_area"],
        yaw_deg=f.get("yaw"),
        roll_deg=f.get("roll"),
        confidence=f.get("conf") or 0.0,
        left=_eye(f.get("left"), width_in),
        right=_eye(f.get("right"), width_in),
        image_width_px=INPUT_WIDTH,
    )


def load_event(features: str, labels: str) -> list[dict]:
    """촬영 순서대로 라벨(애매 제외)과 얼굴을 담은 목록을 돌려준다.

    각 항목: file, label, final_a, faces(Face 목록, 큰 순서), score·frac(주 얼굴의 점수와 눈 폭 비율,
    임계값 학습용. 얼굴이나 눈이 없으면 None)
    """
    final_a = {r["file"]: r.get("is_final_a") == "1"
               for r in csv.DictReader((HERE / labels).open(encoding="utf-8"))}
    recs = json.loads((HERE / features).read_text(encoding="utf-8"))
    out = []
    for r in sorted(recs, key=lambda r: r["file"]):
        if r["label"] == "UNSURE":
            continue
        faces = [to_face(f) for f in r["faces"]]
        main = r["faces"][0] if r["faces"] else None
        has_eyes = bool(main) and main["rmax"] is not None
        out.append({
            "file": r["file"], "label": r["label"], "final_a": final_a.get(r["file"], False),
            "faces": faces,
            "score": main["rmax"] if has_eyes else None,
            "frac": (main["eye_w_full"] / FULL_WIDTH) if has_eyes and main["eye_w_full"] else None,
        })
    return out
