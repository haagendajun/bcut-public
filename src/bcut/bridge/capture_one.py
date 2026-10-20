"""Capture One 연동의 읽기 계층 (devplan T2.1, T2.2의 일부).

**이 모듈의 스크립트는 읽기만 한다.** 쓰기(키워드 부여, 앨범 만들기)는 T2.4 이후에 추가한다.
모든 스크립트는 **지정한 카탈로그가 열려 있을 때만** 동작한다 (실제 작업 카탈로그를 실수로 건드리지
않도록 카탈로그 이름을 인자로 넘기고, 다르면 스크립트가 오류로 멈춘다).

Capture One 스크립트의 함정 (docs/applescript-findings.md):
- `variants of doc`은 현재 선택된 컬렉션의 것이라, 폴더 컬렉션(`catalog folder`)에서 가져온다.
- 변형에서 `image of v`로 올라가는 것은 안 된다. 이미지(`images of c`)에서 `variant 1`로 내려간다.
- 키워드를 지운 변형의 읽기에 이름 `missing value`인 유령 항목이 남는다. 없는 것으로 취급한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bcut.bridge.osascript import DEFAULT_TIMEOUT, Runner, run_script

FIELD_SEP = "\t"
KEYWORD_SEP = "|"
GHOST = "missing value"
SOURCE_PREFIX = "bcut-"  # 도구 전용 키워드의 접두어 (config.keyword_prefix 기본값)

_GUARD = """
    set doc to current document
    set want to item 1 of argv
    set have to name of doc
    if have is not want then error "wrong catalog: " & have & " (expected " & want & ")"
"""

PING_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    return name of doc
  end tell
end run
"""

# 컬렉션 하나의 사진을 한 줄에 하나씩 모으는 공통 핸들러 (카탈로그·세션이 함께 쓴다).
# 한 줄: 경로, 파일명, 별점, 컬러 태그, 키워드들, 컬렉션 id, 변형 id
# **빠른 길**: 사진마다 따로 묻지 않고 컬렉션 하나에서 속성을 한꺼번에 받는다(세션 962장 0.6초,
# 사진마다 묻는 옛 방식은 40~60초이고 결과가 같음을 실기로 비교함). 다음 중 하나면 그 컬렉션만
# 옛 방식으로 읽는다: 이미지 수와 변형 수가 다름(복제본), 맨 앞·맨 뒤 사진의 변형 id가
# 사진 쪽에서 찾은 것과 다름(순서가 어긋남), 한꺼번에 읽다가 오류.
_READ_ROWS = f"""on readRows(c)
  set out to ""
  tell application "Capture One"
    try
      set n to count of (every image of c)
      if n is 0 then return ""
      set fast to false
      try
        if n is (count of (every variant of c)) then
          set ids to id of every variant of c
          set okFirst to ((item 1 of ids) is (id of variant 1 of image 1 of c))
          set okLast to ((item n of ids) is (id of variant 1 of image n of c))
          if okFirst and okLast then set fast to true
        end if
      end try
      if fast then set out to my readFast(c, n, ids)
    end try
  end tell
  if out is "" then set out to my readSlow(c)
  return out
end readRows

on readFast(c, n, ids)
  tell application "Capture One"
    set ps to path of every image of c
    set ns to name of every image of c
    set rs to rating of every variant of c
    set cs to color tag of every variant of c
    set kwl to name of every keyword of every variant of c
    set cid to id of c
  end tell
  set rowList to {{}}
  repeat with i from 1 to n
    set kws to ""
    repeat with k in (item i of kwl)
      if k is not missing value then set kws to kws & (k as text) & "{KEYWORD_SEP}"
    end repeat
    set row to (item i of ps) & "{FIELD_SEP}" & (item i of ns) & "{FIELD_SEP}"
    set row to row & (item i of rs) & "{FIELD_SEP}" & (item i of cs) & "{FIELD_SEP}"
    set end of rowList to row & kws & "{FIELD_SEP}" & cid & "{FIELD_SEP}" & (item i of ids)
  end repeat
  set AppleScript's text item delimiters to linefeed
  set joined to rowList as text
  set AppleScript's text item delimiters to ""
  return joined & linefeed
end readFast

on readSlow(c)
  set out to ""
  tell application "Capture One"
    set ims to images of c
    repeat with i from 1 to (count of ims)
      set im to item i of ims
      set v to variant 1 of im
      set kws to ""
      try
        set names to name of every keyword of v
        repeat with n in names
          if n is not missing value then set kws to kws & (n as text) & "{KEYWORD_SEP}"
        end repeat
      end try
      set out to out & (path of im) & "{FIELD_SEP}" & (name of im) & "{FIELD_SEP}"
      set out to out & (rating of v) & "{FIELD_SEP}" & (color tag of v) & "{FIELD_SEP}"
      set out to out & kws & "{FIELD_SEP}" & (id of c) & "{FIELD_SEP}" & (id of v) & linefeed
    end repeat
  end tell
  return out
end readSlow
"""

# 카탈로그: 폴더 컬렉션(catalog folder)의 변형을 모은다
LIST_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set out to ""
    repeat with c in (every collection of doc whose kind is catalog folder)
      set out to out & my readRows(c)
    end repeat
    return out
  end tell
end run

{_READ_ROWS}"""


# 문서 종류: "catalog" 또는 "session" (지정한 문서가 열려 있을 때만 동작)
KIND_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    return (kind of doc) as text
  end tell
end run
"""

# 세션의 사진 모으기 (읽기). 세션은 컬렉션 종류가 카탈로그와 달라서(폴더가 Capture·Selects 등),
# 폴더 컬렉션을 먼저, 나머지를 그다음에 읽고 하위 컬렉션까지 내려간다. 같은 경로는 파이썬에서
# 한 번만 센다. 한 줄의 모양과 빠른 길은 LIST_SCRIPT와 같다(`_READ_ROWS`).
SESSION_LIST_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set out to ""
    repeat with pass from 1 to 2
      repeat with c in (every collection of doc)
        set isFolder to ((kind of c) is catalog folder)
        if (pass is 1 and isFolder) or (pass is 2 and not isFolder) then
          set out to out & my readTree(c)
        end if
      end repeat
    end repeat
    return out
  end tell
end run

on readTree(c)
  set out to my readRows(c)
  tell application "Capture One"
    try
      repeat with sub in (every collection of c)
        set out to out & my readTree(sub)
      end repeat
    end try
  end tell
  return out
end readTree

{_READ_ROWS}"""


# 별점·컬러 태그 쓰기 (사용자가 고른 값만, ADR-0011).
# 인자: 카탈로그, 값(정수), "컬렉션id|변형id" 목록.
# 키워드와 달리 값 하나를 변형 여러 개에 직접 정한다. 이전 값은 호출하는 쪽이 먼저 저장해 둔다.
_SET_BODY = f"""    set val to (item 2 of argv) as integer
    repeat with i from 3 to (count of argv)
      set AppleScript's text item delimiters to "{KEYWORD_SEP}"
      set parts to text items of (item i of argv)
      set AppleScript's text item delimiters to ""
      set v to (variant id (item 2 of parts) of collection id (item 1 of parts) of doc)
      set PROP of v to val
    end repeat
    return ((count of argv) - 2) as text
"""

SET_RATING_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
{_SET_BODY.replace("PROP", "rating")}  end tell
end run
"""

SET_COLOR_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
{_SET_BODY.replace("PROP", "color tag")}  end tell
end run
"""


KEYWORD_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set out to ""
    repeat with k in (every keyword of doc)
      set out to out & (name of k) & linefeed
    end repeat
    return out
  end tell
end run
"""


# 카탈로그 백업(Capture One의 `backup now`). 지정한 폴더에 카탈로그를 복사한다 (사진은 그대로)
BACKUP_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    backup now doc location (item 2 of argv)
    return "ok"
  end tell
end run
"""


# 키워드 부여 (쓰기). 인자: 카탈로그, 키워드 이름, 그리고 "컬렉션id|변형id" 목록.
# 별점·컬러 태그는 건드리지 않고 `apply keyword`만 호출한다. 키워드가 없으면 오류로 멈춘다.
APPLY_KEYWORD_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set kwName to item 2 of argv
    if not (exists keyword kwName of doc) then error "missing keyword: " & kwName
    set kw to keyword kwName of doc
    set vs to {{}}
    repeat with i from 3 to (count of argv)
      set AppleScript's text item delimiters to "{KEYWORD_SEP}"
      set parts to text items of (item i of argv)
      set AppleScript's text item delimiters to ""
      set end of vs to (variant id (item 2 of parts) of collection id (item 1 of parts) of doc)
    end repeat
    apply keyword kw to vs
    return (count of vs) as text
  end tell
end run
"""


# 키워드 떼기 (쓰기). 인자: 카탈로그, 키워드 이름, "컬렉션id|변형id" 목록.
# 별점·컬러 태그는 건드리지 않는다. 이미 없는 키워드는 오류가 나므로 세지 않고 넘어간다.
# 카탈로그의 키워드 목록에서 키워드 자체를 지우지는 않는다.
STRIP_KEYWORD_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set kwName to item 2 of argv
    set done to 0
    repeat with i from 3 to (count of argv)
      set AppleScript's text item delimiters to "{KEYWORD_SEP}"
      set parts to text items of (item i of argv)
      set AppleScript's text item delimiters to ""
      set v to (variant id (item 2 of parts) of collection id (item 1 of parts) of doc)
      try
        delete (keyword kwName of v)
        set done to done + 1
      end try
    end repeat
    return done as text
  end tell
end run
"""


class CatalogError(RuntimeError):
    """응답을 해석할 수 없다."""


@dataclass(frozen=True)
class VariantInfo:
    path: str
    name: str
    rating: int
    color_tag: int
    keywords: tuple[str, ...] = field(default_factory=tuple)
    collection_id: str = ""  # 쓰기 스크립트가 이 변형을 가리킬 때 쓴다
    variant_id: str = ""

    @property
    def tool_keywords(self) -> tuple[str, ...]:
        """도구가 붙인 전용 키워드(`bcut-` 접두어)."""
        return tuple(k for k in self.keywords if k.startswith(SOURCE_PREFIX))


def parse_variants(text: str) -> list[VariantInfo]:
    """LIST_SCRIPT의 출력을 해석한다. 같은 경로가 여러 컬렉션에 있어도 한 번만 센다."""
    seen: dict[str, VariantInfo] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP)
        if len(parts) < 5:
            raise CatalogError(f"해석할 수 없는 줄: {line!r}")
        path, name, rating, tag, kws = parts[0], parts[1], parts[2], parts[3], parts[4]
        cid, vid = (parts[5], parts[6]) if len(parts) >= 7 else ("", "")
        try:
            info = VariantInfo(
                path=path, name=name, rating=int(rating), color_tag=int(tag),
                keywords=tuple(k for k in kws.split(KEYWORD_SEP) if k and k != GHOST),
                collection_id=cid, variant_id=vid,
            )
        except ValueError as exc:
            raise CatalogError(f"숫자를 해석할 수 없는 줄: {line!r}") from exc
        seen.setdefault(path, info)
    return list(seen.values())


class CaptureOneBridge:
    """지정한 카탈로그에 대해서만 동작하는 Capture One 읽기 창구."""

    def __init__(
        self, catalog_name: str, *, runner: Runner | None = None,
        run: Callable[..., str] = run_script, timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not catalog_name.strip():
            raise ValueError("카탈로그 이름이 비어 있다")
        self.catalog_name = catalog_name
        self.session = False  # 세션이면 True: 사진 읽기 방식이 달라진다 (document_kind로 확인)
        self._run = run
        self._runner = runner
        self._timeout = timeout

    def _kwargs(self) -> dict:
        kwargs: dict = {"timeout": self._timeout}
        if self._runner is not None:
            kwargs["runner"] = self._runner
        return kwargs

    def call(self, script: str, *extra: str) -> str:
        """카탈로그 이름(첫 인자)과 추가 인자로 스크립트를 실행한다."""
        return self._run(script, [self.catalog_name, *extra], **self._kwargs())

    def _call(self, script: str) -> str:
        return self.call(script)

    def ping(self) -> str:
        """열려 있는 카탈로그 이름을 돌려준다. 지정한 카탈로그가 아니면 AppleScriptError."""
        return self._call(PING_SCRIPT)

    def document_kind(self) -> str:
        """열려 있는 문서가 "catalog"인지 "session"인지. 지정한 문서가 아니면 AppleScriptError."""
        return self._call(KIND_SCRIPT).strip().lower()

    def list_variants(self) -> list[VariantInfo]:
        return parse_variants(self._call(SESSION_LIST_SCRIPT if self.session else LIST_SCRIPT))

    def backup_catalog(self, location: str | Path) -> None:
        """Capture One의 카탈로그 백업을 `location` 폴더에 만든다. 사진 파일은 건드리지 않는다."""
        Path(location).mkdir(parents=True, exist_ok=True)
        self._run(BACKUP_SCRIPT, [self.catalog_name, str(location)], **self._kwargs())

    def apply_keyword(self, keyword: str, refs: list[tuple[str, str]]) -> int:
        """키워드 하나를 변형 여러 개에 붙인다. refs는 (컬렉션 id, 변형 id).

        별점과 컬러 태그는 건드리지 않는다. 카탈로그에 그 키워드가 없으면 AppleScriptError
        (`missing keyword`)로 멈춘다 — 키워드를 스크립트로 만들 수 없기 때문이다.
        """
        if not refs:
            return 0
        args = [self.catalog_name, keyword, *[f"{c}{KEYWORD_SEP}{v}" for c, v in refs]]
        return int(self._run(APPLY_KEYWORD_SCRIPT, args, **self._kwargs()))

    def set_rating(self, value: int, refs: list[tuple[str, str]]) -> int:
        """별점을 변형 여러 개에 정한다 (사용자가 고른 값만). refs는 (컬렉션 id, 변형 id)."""
        return self._set(SET_RATING_SCRIPT, value, refs)

    def set_color_tag(self, value: int, refs: list[tuple[str, str]]) -> int:
        """컬러 태그를 변형 여러 개에 정한다 (사용자가 고른 값만)."""
        return self._set(SET_COLOR_SCRIPT, value, refs)

    def _set(self, script: str, value: int, refs: list[tuple[str, str]]) -> int:
        if not refs:
            return 0
        args = [self.catalog_name, str(int(value)), *[f"{c}{KEYWORD_SEP}{v}" for c, v in refs]]
        return int(self._run(script, args, **self._kwargs()))

    def strip_keyword(self, keyword: str, refs: list[tuple[str, str]]) -> int:
        """키워드 하나를 변형들에서 뗀다 (이미 없는 것은 세지 않는다). 별점·태그는 그대로.

        카탈로그의 키워드 목록에서 키워드를 지우지는 않는다.
        """
        if not refs:
            return 0
        args = [self.catalog_name, keyword, *[f"{c}{KEYWORD_SEP}{v}" for c, v in refs]]
        return int(self._run(STRIP_KEYWORD_SCRIPT, args, **self._kwargs()))

    def keywords(self) -> list[str]:
        """카탈로그에 있는 키워드 이름 (전용 키워드가 만들어져 있는지 확인할 때 쓴다)."""
        return [k for k in self._call(KEYWORD_SCRIPT).splitlines() if k and k != GHOST]
