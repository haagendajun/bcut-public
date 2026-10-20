"""`bcut doctor`: 환경과 Capture One 연결을 점검한다 (devplan T3.6).

**읽기만 하고 아무것도 바꾸지 않는다.** 문제가 생겼을 때 무엇부터 볼지 한 번에 알려 준다:
Python·라이브러리 버전, 도구 버전, Capture One 설치·버전·실행 여부,
(카탈로그를 지정하면) 열린 카탈로그 이름·자동화 권한·전용 키워드 유무.
Capture One이 꺼져 있으면 연결을 시도하지 않는다 (스크립트로 연결하면 앱이 저절로 켜지기 때문이다).
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from bcut import __version__
from bcut.bridge.capture_one import CaptureOneBridge
from bcut.bridge.osascript import AppleScriptError, explain_error

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
TESTED_CAPTURE_ONE = "16.7"  # 이 버전에서만 시험했다
CAPTURE_ONE_APP = Path("/Applications/Capture One.app")
LIBRARIES = ("numpy", "pillow", "rawpy", "pyobjc-framework-Vision", "pyobjc-framework-Quartz")
REQUIRED_KEYWORDS = ("candidate", "review", "eyes_closed", "exposure", "blur", "out_of_focus")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def _version(lib: str) -> str | None:
    try:
        return metadata.version(lib)
    except metadata.PackageNotFoundError:
        return None


def capture_one_version(app: Path = CAPTURE_ONE_APP) -> str | None:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            return str(plistlib.load(f).get("CFBundleShortVersionString"))
    except (OSError, plistlib.InvalidFileException):
        return None


def capture_one_running() -> bool:
    """실행 중인지만 본다 (켜지 않는다)."""
    try:
        r = subprocess.run(["pgrep", "-x", "Capture One"], capture_output=True, check=False)
    except OSError:
        return False
    return r.returncode == 0


def run_checks(
    catalog: str | None = None, *, keyword_prefix: str = "bcut-",
    versions: Callable[[str], str | None] = _version,
    co_version: Callable[[], str | None] = capture_one_version,
    co_running: Callable[[], bool] = capture_one_running,
    bridge_factory: Callable[[str], CaptureOneBridge] = lambda name: CaptureOneBridge(
        name, timeout=30),
    python_version: tuple[int, int] | None = None,
    has_osascript: bool = True,
) -> list[Check]:
    checks: list[Check] = []
    py = python_version or sys.version_info[:2]
    checks.append(Check(
        "Python", OK if py >= (3, 13) else FAIL, f"{py[0]}.{py[1]}",
        "" if py >= (3, 13) else "Python 3.13 이상이 필요하다 (docs/install.md)"))
    checks.append(Check("bcut", OK, __version__))
    for lib in LIBRARIES:
        v = versions(lib)
        checks.append(Check(
            lib, OK if v else FAIL, v or "설치되어 있지 않다",
            "" if v else "pip install -r requirements-lock.txt (docs/install.md)"))
    checks.append(Check(
        "osascript", OK if has_osascript else FAIL, "있음" if has_osascript else "없음",
        "" if has_osascript else "macOS가 아니면 Capture One 연동(apply 등)은 쓸 수 없다"))

    ver = co_version()
    if ver is None:
        checks.append(Check("Capture One 설치", WARN, "찾지 못함",
                            "scan은 Capture One 없이 돈다. apply·albums·rollback에는 필요하다"))
    else:
        tested = ver.startswith(TESTED_CAPTURE_ONE)
        checks.append(Check(
            "Capture One 버전", OK if tested else WARN, ver,
            "" if tested else f"{TESTED_CAPTURE_ONE}.x에서만 시험했다. 업데이트했다면 "
            "docs/applescript-findings.md의 시험 7개를 다시 돌린다"))

    if catalog is None:
        checks.append(Check("카탈로그 연결", SKIP, "--catalog를 주면 점검한다"))
        return checks
    if not co_running():
        checks.append(Check("Capture One 실행", FAIL, "실행 중이 아니다",
                            "Capture One을 실행하고 카탈로그를 연 뒤 다시 한다"))
        return checks
    checks.append(Check("Capture One 실행", OK, "실행 중"))
    try:
        bridge = bridge_factory(catalog)
        opened = bridge.ping()
    except AppleScriptError as exc:
        checks.append(Check("카탈로그 연결", FAIL, explain_error(exc)))
        return checks
    checks.append(Check("카탈로그 연결", OK, f"{opened} (자동화 권한 정상)"))
    try:
        have = set(bridge.keywords())
    except AppleScriptError as exc:
        checks.append(Check("전용 키워드", FAIL, explain_error(exc)))
        return checks
    wanted = [f"{keyword_prefix}{k}" for k in REQUIRED_KEYWORDS]
    missing = [k for k in wanted if k not in have]
    hint = "docs/capture-one-setup.md대로 만든다 (이번 행사에 안 쓰는 키워드는 없어도 된다)"
    checks.append(Check(
        "전용 키워드", OK if not missing else WARN,
        "6개 모두 있음" if not missing else f"없는 키워드: {', '.join(missing)}",
        "" if not missing else hint))
    return checks


def has_failure(checks: list[Check]) -> bool:
    return any(c.status == FAIL for c in checks)
