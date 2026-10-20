"""올리기 상태(`cloud.json`)와 로그인 토큰 보관 (ADR-0009).

- `cloud.json`에는 동의 시각, 로그인 이메일, 이미 올린 줄 번호만 둔다. 비밀번호·토큰은 없다.
- 로그인 토큰(갱신용)은 macOS 키체인에 둔다. 시험에서는 메모리 보관함으로 바꿔 끼운다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

SERVICE = "bcut-cloud-refresh"
ACCOUNT = "bcut"


class MemoryVault:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get(self) -> str | None:
        return self.token

    def set(self, token: str) -> None:
        self.token = token

    def forget(self) -> None:
        self.token = None


class MacKeychain:
    """`security` 명령으로 키체인의 한 항목만 읽고 쓴다."""

    def get(self) -> str | None:
        r = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT, "-s", SERVICE,
                            "-w"], capture_output=True, text=True, timeout=10, check=False)
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, token: str) -> None:
        subprocess.run(["security", "add-generic-password", "-U", "-a", ACCOUNT, "-s", SERVICE,
                        "-w", token], capture_output=True, timeout=10, check=True)

    def forget(self) -> None:
        subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
                       capture_output=True, timeout=10, check=False)


class CloudState:
    """올린 것의 기록. 파일이 없거나 깨져도 빈 상태로 시작하고, 다시 올려도 중복은 DB가 막는다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.setdefault("consented_at", None)
        data.setdefault("email", None)
        data.setdefault("marks", {})      # {표시 id: "a"(올림) | "c"(취소까지 올림)}
        data.setdefault("reviews", [])    # 올린 훑기 기록 id
        data.setdefault("last_sync_at", None)
        return data

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    def consent(self, now: datetime | None = None) -> None:
        when = now or datetime.now().astimezone()
        self.data["consented_at"] = when.isoformat(timespec="seconds")
        self.save()
