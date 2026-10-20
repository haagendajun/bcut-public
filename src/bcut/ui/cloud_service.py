"""올리기 전체를 묶는 서비스: 동의 → 로그인 → 올리기 → 상태 (spec FR-29~33).

로컬이 먼저다. 어떤 실패도 예외로 번지지 않고 상태 글자("대기", "로그인 필요")로만 나타난다.
동의하기 전에는 어떤 요청도 보내지 않는다.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from bcut.ui.cloud import CloudError
from bcut.ui.cloud_plan import make_plan, read_event
from bcut.ui.cloud_state import CloudState
from bcut.ui.cloud_sync import upload_event


class CloudService:
    def __init__(self, data_dir: Path, client, vault) -> None:
        self.events_dir = data_dir / "events"
        self.state = CloudState(data_dir / "cloud.json")
        self.client = client
        self.vault = vault
        self._access: str | None = None
        self._busy = threading.Lock()
        self.error: str | None = None

    # ---- 상태 ----
    def pending(self) -> int:
        done_m, done_r = self.state.data["marks"], set(self.state.data["reviews"])
        total = 0
        for folder in self._event_dirs():
            total += make_plan(read_event(folder), done_m, done_r).pending
        return total

    def _event_dirs(self) -> list[Path]:
        if not self.events_dir.is_dir():
            return []
        return sorted(p for p in self.events_dir.iterdir() if p.is_dir())

    def status(self) -> dict:
        consented = bool(self.state.data["consented_at"])
        signed_in = consented and self.vault.get() is not None
        pending = self.pending()
        if not consented:
            label = "need_consent"
        elif not signed_in:
            label = "need_login"
        elif self.error:
            label = "error"
        else:
            label = "pending" if pending else "synced"
        return {"state": label, "consented": consented, "signed_in": signed_in,
                "email": self.state.data["email"], "pending": pending, "error": self.error,
                "syncing": self._busy.locked(), "last_sync_at": self.state.data["last_sync_at"]}

    # ---- 동의·로그인 ----
    def consent(self) -> dict:
        self.state.consent()
        return self.status()

    def login(self, email: str, password: str) -> dict:
        self._require_consent()
        tokens = self.client.login(email, password)  # 비밀번호는 여기서만 쓰고 버린다
        self._access = tokens["access_token"]
        if tokens.get("refresh_token"):
            self.vault.set(tokens["refresh_token"])
        self.state.data["email"] = tokens.get("email") or email
        self.error = None
        self.state.save()
        return self.status()

    def logout(self) -> dict:
        self._access = None
        self.vault.forget()
        self.state.data["email"] = None
        self.state.save()
        return self.status()

    def _require_consent(self) -> None:
        if not self.state.data["consented_at"]:
            raise CloudError("consent", "먼저 올리기 안내에 동의해야 한다")

    # ---- 올리기 ----
    def _ensure_access(self) -> str:
        if self._access:
            return self._access
        token = self.vault.get()
        if token is None:
            raise CloudError("auth", "로그인이 필요하다")
        fresh = self.client.refresh(token)
        self._access = fresh["access_token"]
        if fresh.get("refresh_token"):
            self.vault.set(fresh["refresh_token"])
        return self._access

    def _upload_all(self) -> None:
        access = self._ensure_access()
        for folder in self._event_dirs():
            upload_event(self.client, access, read_event(folder), self.state)

    def sync(self) -> dict:
        """지금 올린다. 동의·로그인이 없으면 요청 없이 상태만 돌려준다."""
        if not self.state.data["consented_at"] or self.vault.get() is None:
            return self.status()
        if not self._busy.acquire(blocking=False):
            return self.status()
        try:
            try:
                self._upload_all()
            except CloudError as exc:
                if exc.kind != "auth":
                    raise
                self._access = None  # 만료: 갱신 토큰으로 한 번 더
                self._upload_all()
            self.error = None
            self.state.data["last_sync_at"] = datetime.now().astimezone().isoformat(
                timespec="seconds")
            self.state.save()
        except CloudError as exc:
            self._fail(exc)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            self.error = f"올리기 중 문제가 생겼다: {type(exc).__name__}"
        finally:
            self._busy.release()
        return self.status()

    def _fail(self, exc: CloudError) -> None:
        if exc.kind == "auth":
            self._access = None
            self.vault.forget()  # 갱신 토큰도 못 쓴다 → 다시 로그인
            self.error = None
        else:
            self.error = str(exc)


def handle(service: CloudService, method: str, path: str, body: dict | None) -> tuple[int, dict]:
    """서버가 부르는 짧은 함수. (HTTP 상태 번호, 응답). http를 쓰지 않아서 숫자로 준다."""
    try:
        if method == "GET" and path == "/api/cloud/status":
            return 200, service.status()
        if method != "POST":
            return 405, {"error": "허용되지 않은 메서드"}
        if path == "/api/cloud/consent":
            return 200, service.consent()
        if path == "/api/cloud/logout":
            return 200, service.logout()
        if path == "/api/cloud/sync":
            return 200, service.sync()
        if path == "/api/cloud/login":
            email, password = (body or {}).get("email"), (body or {}).get("password")
            if not isinstance(email, str) or not isinstance(password, str) or not email:
                return 400, {"error": "이메일과 비밀번호를 입력해야 한다"}
            return 200, service.login(email.strip(), password)
    except CloudError as exc:
        code = {"consent": 403, "auth": 401, "network": 502}.get(exc.kind, 502)
        return code, {"error": str(exc), "kind": exc.kind}
    return 404, {"error": "없는 주소"}
