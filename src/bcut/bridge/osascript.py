"""AppleScript 호출 계층 (devplan T2.1).

Python에서 `osascript`를 실행하고 결과를 글자로 돌려준다. 안전 장치:

- **인자는 스크립트 글자에 끼워 넣지 않고** `on run argv`로 넘긴다 (파일 이름의 따옴표가 스크립트를
  깨거나 끼어드는 것을 막는다).
- 오류와 시간 초과를 `AppleScriptError`, `AppleScriptTimeout`으로 구분해 올린다.
- 이 모듈은 네트워크를 쓰지 않는다. 사진 파일에는 손대지 않고 Capture One에 명령만 보낸다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

DEFAULT_TIMEOUT = 60.0
OSASCRIPT = "osascript"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class AppleScriptError(RuntimeError):
    """스크립트 실행이 실패했다 (Capture One 오류, 권한 없음, 문법 오류 등)."""

    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


class AppleScriptTimeout(AppleScriptError):
    """정해진 시간 안에 끝나지 않았다. Capture One이 응답하지 않을 수 있다."""


def run_script(
    script: str,
    args: Sequence[str] = (),
    *,
    timeout: float = DEFAULT_TIMEOUT,
    runner: Runner = subprocess.run,
) -> str:
    """AppleScript를 실행하고 표준 출력(끝의 줄바꿈 제외)을 돌려준다.

    `script`는 `on run argv ... end run` 형태여야 `args`를 받을 수 있다.
    """
    cmd = [OSASCRIPT, "-e", script, *[str(a) for a in args]]
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AppleScriptTimeout(f"{timeout:.0f}초 안에 끝나지 않았다", None) from exc
    except FileNotFoundError as exc:
        raise AppleScriptError("osascript를 찾을 수 없다 (macOS가 아니다)") from exc
    if proc.returncode != 0:
        message = (proc.stderr or "").strip() or f"osascript 종료 코드 {proc.returncode}"
        raise AppleScriptError(message, proc.returncode)
    return (proc.stdout or "").rstrip("\n")


def explain_error(exc: BaseException) -> str:
    """사용자에게 보여 줄 한 줄 설명. 알려진 원인이면 무엇을 하면 되는지 함께 알려 준다."""
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, AppleScriptTimeout):
        return (f"Capture One이 제때 응답하지 않았다 ({msg}). Capture One이 멈췄는지 확인하고, "
                "필요하면 껐다 켠 뒤 같은 명령을 다시 실행한다 (이미 한 일은 건너뛴다)")
    if "-1743" in msg or "not authorized" in low:
        return ("이 터미널이 Capture One을 제어할 권한이 없다. 시스템 설정 > 개인정보 보호 및 "
                "보안 > 자동화에서 터미널(또는 쓰는 앱)의 Capture One을 켠다")
    if "-600" in msg or "isn't running" in low or "연결이 유효하지 않" in msg:
        return "Capture One이 실행 중이 아니다. 실행하고 카탈로그를 연 뒤 다시 한다"
    if "wrong catalog" in low:
        detail = msg.split("wrong catalog:")[-1].strip()
        return ("열려 있는 카탈로그가 지정한 것과 다르다. 아무것도 바꾸지 않았다. "
                f"Capture One에서 올바른 카탈로그를 연다 ({detail})")
    if "missing keyword" in low:
        return "카탈로그에 전용 키워드가 없다. docs/capture-one-setup.md대로 한 번 만든다"
    if "current document" in low or "document" in low and "-1728" in msg:
        return "열려 있는 카탈로그가 없다. Capture One에서 카탈로그를 연 뒤 다시 한다"
    return f"Capture One 연동 오류: {msg}"
