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

# 폴더 컬렉션(catalog folder)의 변형을 모아 한 줄에 하나씩:
# 경로, 파일명, 별점, 컬러 태그, 키워드들, 컬렉션 id, 변형 id
LIST_SCRIPT = f"""on run argv
  tell application "Capture One"
{_GUARD}
    set out to ""
    repeat with c in (every collection of doc whose kind is catalog folder)
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
    end repeat
    return out
  end tell
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

    def list_variants(self) -> list[VariantInfo]:
        return parse_variants(self._call(LIST_SCRIPT))

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
