"""사용자가 고른 별점·컬러 태그를 표시한 사진에 주고, 되돌린다 (spec FR-28g, ADR-0011).

- 기본은 아무것도 안 준다. 사용자가 표시 종류(셀렉·보류·버릴 컷)마다 고른 값만 준다.
- 이미 별점·컬러 태그가 있는 사진은 건너뛴다. "덮어쓰기"를 켠 때만 바꾼다.
- 주기 전에 **이전 값을 파일에 먼저 저장**하고(저장 못 하면 아무것도 안 바꾼다),
  준 뒤에 다시 읽어 확인한다.
- 되돌리기는 **별점과 컬러 태그를 따로 보고**, 현재 값이 우리가 준 값 그대로인 것만 이전 값으로
  돌린다. 이미 이전 값이면 건너뛰고, 그 사이 사용자가 바꾼 것은 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from bcut.bridge.capture_one import VariantInfo

FILENAME = "bcut-style-backup.json"
KINDS = ("pick", "maybe", "discard")
RATINGS = (1, 2, 3, 4, 5)
COLORS = (1, 2, 3, 4, 5, 6, 7)  # 빨강, 주황, 노랑, 초록, 파랑, 분홍, 보라 (Capture One 순서)
CHUNK = 200


class StyleError(ValueError):
    """요청의 별점·컬러 태그 값이 올바르지 않다."""


@dataclass
class Style:
    """표시 종류 -> (별점 또는 None, 컬러 태그 또는 None)."""

    by_kind: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    overwrite: bool = False

    @property
    def active(self) -> bool:
        return any(r or c for r, c in self.by_kind.values())


def parse_style(body: dict) -> Style:
    raw = body.get("style")
    if raw is None:
        return Style()
    if not isinstance(raw, dict):
        raise StyleError("style 모양이 올바르지 않다")
    out: dict[str, tuple[int | None, int | None]] = {}
    for kind, v in raw.items():
        if kind not in KINDS or not isinstance(v, dict):
            raise StyleError(f"알 수 없는 표시 종류: {kind}")
        rating, color = v.get("rating"), v.get("color")
        if rating is not None and (isinstance(rating, bool) or rating not in RATINGS):
            raise StyleError("별점은 1~5 중에서 골라야 한다")
        if color is not None and (isinstance(color, bool) or color not in COLORS):
            raise StyleError("컬러 태그는 1~7 중에서 골라야 한다")
        out[kind] = (rating, color)
    return Style(out, overwrite=body.get("overwrite") is True)


@dataclass
class StylePlan:
    rating: dict[str, int] = field(default_factory=dict)  # 파일 -> 줄 별점
    color: dict[str, int] = field(default_factory=dict)  # 파일 -> 줄 컬러 태그
    skipped_rating: int = 0  # 이미 별점이 있어 건너뜀
    skipped_color: int = 0


def plan_style(style: Style, kinds: dict[str, str], matched: dict[str, VariantInfo]) -> StylePlan:
    """kinds: 파일 -> 표시 종류. matched: 파일 -> 카탈로그의 변형(지금 값)."""
    plan = StylePlan()
    for name, v in matched.items():
        rating, color = style.by_kind.get(kinds.get(name, ""), (None, None))
        if rating is not None:
            if v.rating == 0 or style.overwrite:
                if v.rating != rating:
                    plan.rating[name] = rating
            else:
                plan.skipped_rating += 1
        if color is not None:
            if v.color_tag == 0 or style.overwrite:
                if v.color_tag != color:
                    plan.color[name] = color
            else:
                plan.skipped_color += 1
    return plan


def _counts(values: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values.values():
        out[str(v)] += 1
    return dict(sorted(out.items()))


def preview_payload(plan: StylePlan) -> dict:
    return {"rating_counts": _counts(plan.rating), "color_counts": _counts(plan.color),
            "skipped_rating": plan.skipped_rating, "skipped_color": plan.skipped_color,
            "applied": False, "violations": []}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, entries: dict, catalog: str, now: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"catalog": catalog, "created_at": now, "entries": entries},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _record(entries: dict, plan: StylePlan, matched: dict[str, VariantInfo]) -> None:
    """이전 값은 처음 한 번만 저장한다 (두 번째 반영이 처음의 값을 덮어쓰지 않게)."""
    for name in sorted(set(plan.rating) | set(plan.color)):
        v = matched[name]
        old = entries.get(v.path)
        entries[v.path] = {
            "file": name, "collection": v.collection_id, "variant": v.variant_id,
            "before_rating": old["before_rating"] if old else v.rating,
            "before_color": old["before_color"] if old else v.color_tag,
            "rating": plan.rating.get(name, old["rating"] if old else None),
            "color": plan.color.get(name, old["color"] if old else None)}


def _write(bridge, plan: StylePlan, matched: dict[str, VariantInfo]) -> None:
    for values, setter in ((plan.rating, bridge.set_rating), (plan.color, bridge.set_color_tag)):
        refs: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for name, val in values.items():
            refs[val].append((matched[name].collection_id, matched[name].variant_id))
        for val, items in sorted(refs.items()):
            for i in range(0, len(items), CHUNK):
                setter(val, items[i:i + CHUNK])


def apply_style(bridge, plan: StylePlan, matched: dict[str, VariantInfo], out_dir: Path,
                now: str) -> dict:
    """이전 값 저장 -> 쓰기 -> 다시 읽어 확인. 저장하지 못하면 아무것도 쓰지 않는다."""
    payload = preview_payload(plan)
    if not plan.rating and not plan.color:
        return payload
    path = out_dir / FILENAME
    entries = _load(path).get("entries", {})
    _record(entries, plan, matched)
    try:
        _save(path, entries, bridge.catalog_name, now)
    except OSError as exc:
        payload["violations"] = [f"되돌리기용 기록을 못 저장해 별점·컬러 태그는 주지 않았다: {exc}"]
        return payload
    _write(bridge, plan, matched)
    after = {v.path: v for v in bridge.list_variants()}
    bad = []
    for name in sorted(set(plan.rating) | set(plan.color)):
        now_v = after.get(matched[name].path)
        want_r, want_c = plan.rating.get(name), plan.color.get(name)
        if now_v is None or (want_r is not None and now_v.rating != want_r) or (
                want_c is not None and now_v.color_tag != want_c):
            bad.append(f"{name}: 준 값이 그대로 읽히지 않는다")
    payload.update(applied=True, violations=bad[:20])
    return payload


def _decide(cur: int, applied: int | None, before: int) -> str:
    """한 값(별점 또는 컬러 태그)을 어떻게 할지.
    restore: 우리가 준 값 그대로라 되돌림, done: 이미 이전 값이라 할 일 없음,
    kept: 그 사이 사용자가 바꿔서 그대로 둠, skip: 주지 않은 값."""
    if applied is None:
        return "skip"
    if cur == applied:
        return "restore"
    return "done" if cur == before else "kept"


def rollback_style(bridge, out_dir: Path, *, commit: bool) -> dict:
    """우리가 준 값을 이전 값으로 돌린다. **별점과 컬러 태그를 따로** 본다. 우리가 준 값 그대로인
    것만 돌리고, 이미 이전 값이면 건너뛰고, 그 사이 사용자가 바꾼 것은 그대로 둔다."""
    entries = _load(out_dir / FILENAME).get("entries", {})
    now_by_path = {v.path: v for v in bridge.list_variants()} if entries else {}
    back_r: dict[int, list] = defaultdict(list)
    back_c: dict[int, list] = defaultdict(list)
    photos = already = kept = 0
    for path, e in entries.items():
        v = now_by_path.get(path)
        if v is None:
            kept += 1
            continue
        ref = (v.collection_id, v.variant_id)
        dr = _decide(v.rating, e["rating"], e["before_rating"])
        dc = _decide(v.color_tag, e["color"], e["before_color"])
        if dr == "restore":
            back_r[e["before_rating"]].append(ref)
        if dc == "restore":
            back_c[e["before_color"]].append(ref)
        if "restore" in (dr, dc):
            photos += 1
        elif "kept" in (dr, dc):
            kept += 1
        else:
            already += 1
    done = False
    if commit and photos:
        for groups, setter in ((back_r, bridge.set_rating), (back_c, bridge.set_color_tag)):
            for val, items in sorted(groups.items()):
                for i in range(0, len(items), CHUNK):
                    setter(val, items[i:i + CHUNK])
        done = True
    return {"restore": photos, "already_restored": already, "kept_user_changed": kept,
            "restored": done, "has_record": bool(entries)}
