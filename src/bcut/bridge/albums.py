"""전용 스마트 앨범 (devplan T2.6·T2.8, PRD FR-07·FR-09·FR-10).

키워드·별점 조건 스마트 앨범을 스크립트로 만든다. 규칙은 Capture One의 XML 형식이고(사람이 만든
앨범의 `rules`를 읽어 알아냈다), 키워드가 붙거나 별점이 바뀌면 앨범이 자동으로 따라간다.

규칙 XML: 맨 위 `MatchOperator`(Kind = AND 또는 OR) 안에 `MatchOperator`(AND) 묶음이 여러 개,
묶음 안에 `Condition`이 여러 개다. 조건 키와 연산자는 실기에서 개수로 확인했다:
- 키 `IB_S_CONTENT_KEYWORDS`(키워드): 연산자 0 = 일치/포함, 1 = 아님
- 키 `IB_I_BASIC_RATING`(별점): 0 = 같음, 1 = 같지 않음, 2 = 이상, 3 = 이하, 4 = 미만, 5 = 초과

**별점이 우선이다 (CUJ-03):** 사용자가 별점을 하나라도 주면(되살리면) 후보·확인·사유별·제외된 컷
앨범에서 빠지고 `정상`에 들어간다. 전용 키워드를 일일이 지우지 않아도 된다.

같은 이름의 앨범이 이미 있으면 **새로 만들지 않고 건드리지도 않는다** (규칙이 다르면 알린다).
키워드가 카탈로그에 없어도 앨범은 만들 수 있다 (규칙은 이름만 쓴다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from bcut.bridge.capture_one import (
    _GUARD,
    CaptureOneBridge,
)

KEY_KEYWORD = "IB_S_CONTENT_KEYWORDS"
KEY_RATING = "IB_I_BASIC_RATING"
OP_IS = 0  # 키워드: 일치/포함, 별점: 같음
OP_IS_NOT = 1
OP_GREATER = 5  # 별점: 초과
NAME_PREFIX = "bcut "

# 실기로 확인한 키별 연산자만 허용한다. 모르는 연산자로 앨범을 만들면 Capture One에
# **깨진 컬렉션**이 남아 이름을 읽을 수도 지울 수도 없게 된다 (T2.8 시험에서 연산자 6, 7로 겪음).
ALLOWED_OPERATORS = {
    KEY_KEYWORD: frozenset({OP_IS, OP_IS_NOT}),
    KEY_RATING: frozenset({0, 1, 2, 3, 4, OP_GREATER}),
}

# 조건 = (키, 연산자, 값). 한 묶음 안의 조건은 모두(AND) 만족해야 한다.
Condition = tuple[str, int, str]
Group = tuple[Condition, ...]


def has_keyword(k: str) -> Condition:
    return (KEY_KEYWORD, OP_IS, k)


def lacks_keyword(k: str) -> Condition:
    return (KEY_KEYWORD, OP_IS_NOT, k)


UNRATED: Condition = (KEY_RATING, OP_IS, "0")  # 별점 없음 = 아직 되살리지 않음
RATED: Condition = (KEY_RATING, OP_GREATER, "0")  # 별점을 하나라도 줌 = 되살림


def _check_condition(key: str, op: int, val: str) -> None:
    allowed = ALLOWED_OPERATORS.get(key)
    if allowed is None:
        raise ValueError(f"확인되지 않은 조건 키: {key}")
    if op not in allowed:
        raise ValueError(f"{key}에서 확인되지 않은 연산자: {op} (허용: {sorted(allowed)})")
    if key == KEY_KEYWORD and not val.strip():
        raise ValueError("키워드 조건의 값이 비어 있다")
    if key == KEY_RATING and val not in {"0", "1", "2", "3", "4", "5"}:
        raise ValueError(f"별점 조건의 값은 0~5여야 한다: {val!r}")


def rules_from_groups(groups: tuple[Group, ...], top: str = "AND") -> str:
    """묶음들을 `top`(AND/OR)으로 이은 스마트 앨범 규칙. 묶음 안은 AND."""
    if top not in ("AND", "OR"):
        raise ValueError(f"top은 AND 또는 OR여야 한다: {top}")
    if not groups or any(not g for g in groups):
        raise ValueError("조건이 없는 묶음이 있다")
    for g in groups:
        for key, op, val in g:
            _check_condition(key, op, val)
    body = "".join(
        '<MatchOperator Kind="AND">' + "".join(
            f'<Condition Enabled="YES"><Key>{key}</Key><Operator>{op}</Operator>'
            f"<Criterion>{escape(val)}</Criterion></Condition>"
            for key, op, val in g
        ) + "</MatchOperator>"
        for g in groups
    )
    return f'<?xml version="1.0"?><MatchOperator Kind="{top}">{body}</MatchOperator>'


def rules_xml(include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str:
    """포함·제외 키워드 조건을 모두 만족(AND)하는 규칙 (별점 조건 없음)."""
    if not include and not exclude:
        raise ValueError("조건이 하나도 없다")
    conds = (*(has_keyword(k) for k in include), *(lacks_keyword(k) for k in exclude))
    return rules_from_groups((conds,), "AND")


@dataclass(frozen=True)
class AlbumSpec:
    name: str
    groups: tuple[Group, ...]
    top: str = "AND"

    @property
    def rules(self) -> str:
        return rules_from_groups(self.groups, self.top)

    def describe(self) -> str:
        kind = " 또는 ".join(
            " 그리고 ".join(_describe(c) for c in g) for g in self.groups)
        return kind


def _describe(c: Condition) -> str:
    key, op, val = c
    if key == KEY_KEYWORD:
        return f"키워드 {'없음' if op == OP_IS_NOT else '있음'} {val}"
    return {(OP_IS, "0"): "별점 없음", (OP_GREATER, "0"): "별점 있음"}.get(
        (op, val), f"별점 연산자{op} {val}")


def album_specs(keyword_prefix: str = "bcut-") -> list[AlbumSpec]:
    p = keyword_prefix
    cand, review = f"{p}candidate", f"{p}review"

    def reason(label: str, kw: str) -> AlbumSpec:
        return AlbumSpec(f"{NAME_PREFIX}{label}", ((has_keyword(f"{p}{kw}"), UNRATED),))

    return [
        AlbumSpec(f"{NAME_PREFIX}후보", ((has_keyword(cand), UNRATED),)),
        AlbumSpec(f"{NAME_PREFIX}확인", ((has_keyword(review), UNRATED),)),
        # 정상 = 도구가 후보·확인으로 올리지 않은 컷, 또는 별점을 줘서 되살린 컷
        AlbumSpec(f"{NAME_PREFIX}정상",
                  ((lacks_keyword(cand), lacks_keyword(review)), (RATED,)), top="OR"),
        # 제외된 컷 다시 보기 (FR-09): 도구가 걸렀고 아직 되살리지 않은 컷 전부
        AlbumSpec(f"{NAME_PREFIX}제외된 컷",
                  ((has_keyword(cand), UNRATED), (has_keyword(review), UNRATED)), top="OR"),
        reason("눈 감김", "eyes_closed"),
        reason("노출", "exposure"),
        reason("흔들림", "blur"),
        reason("초점 실패", "out_of_focus"),
    ]


# 문서의 컬렉션 이름과 규칙을 읽는다 (읽기 전용)
LIST_ALBUMS_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set out to ""
    repeat with c in (every collection of doc whose kind is smart album)
      set out to out & (name of c) & tab & (rules of c) & linefeed
    end repeat
    return out
  end tell
end run
"""

# 스마트 앨범 만들기 (쓰기). 같은 이름이 있으면 만들지 않고 "exists"를 돌려준다.
CREATE_ALBUM_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set albumName to item 2 of argv
    if exists collection albumName of doc then return "exists"
    set ruleText to item 3 of argv
    make new collection at doc with properties {{kind:smart album, name:albumName, rules:ruleText}}
    return "created"
  end tell
end run
"""


@dataclass
class AlbumPlan:
    to_create: list[AlbumSpec] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    rule_mismatch: list[str] = field(default_factory=list)  # 이름은 같지만 규칙이 다른 앨범


def plan_albums(existing: dict[str, str], specs: list[AlbumSpec]) -> AlbumPlan:
    plan = AlbumPlan()
    for s in specs:
        if s.name not in existing:
            plan.to_create.append(s)
            continue
        plan.existing.append(s.name)
        if _squash(existing[s.name]) != _squash(s.rules):
            plan.rule_mismatch.append(s.name)
    return plan


def _squash(xml: str) -> str:
    return "".join(xml.split())


def parse_albums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "\t" in line:
            name, rules = line.split("\t", 1)
            out[name] = rules
    return out


def list_albums(bridge: CaptureOneBridge) -> dict[str, str]:
    return parse_albums(bridge.call(LIST_ALBUMS_SCRIPT))


def create_album(bridge: CaptureOneBridge, spec: AlbumSpec) -> str:
    return bridge.call(CREATE_ALBUM_SCRIPT, spec.name, spec.rules)
