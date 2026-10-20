"""슈파베이스와 이야기하는 **유일한 파일** (ADR-0003, 0009).

- 보낼 수 있는 주소는 `https://<무엇이든>.supabase.co`와,
  시험용 `http://127.0.0.1`(이 컴퓨터 안)뿐이다.
- 공개용(publishable) 열쇠만 쓴다. 비밀·서비스 열쇠는 코드에 없다. 비밀번호는 로그인 요청에만
  실리고 어디에도 저장하지 않는다.
- 주소 바꿔치기(리다이렉트)는 따라가지 않는다. 한 번에 10초까지만 기다린다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

PROJECT_URL = "https://fsngkxbhgtmzpjoasmvn.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_8N9h_o7zZyz2BouF-mb97A_ItbSOfuP"  # 공개용이라 코드에 둬도 된다
TIMEOUT = 10.0


class CloudError(Exception):
    """kind: consent(동의 전) / auth(로그인 필요) / network(인터넷) / rejected(거절) / server."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def allowed_url(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https" and p.hostname is not None and p.hostname.endswith(".supabase.co"):
        return True
    return p.scheme == "http" and p.hostname == "127.0.0.1"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


class SupabaseClient:
    def __init__(self, base: str = PROJECT_URL, key: str = PUBLISHABLE_KEY,
                 timeout: float = TIMEOUT) -> None:
        if not allowed_url(base):
            raise CloudError("rejected", "허용되지 않은 서버 주소")
        self.base = base.rstrip("/")
        self.key = key
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _call(self, method: str, path: str, *, token: str | None = None, body=None,
              headers: dict | None = None) -> tuple[int, object]:
        url = self.base + path
        if not allowed_url(url):
            raise CloudError("rejected", "허용되지 않은 서버 주소")
        head = {"apikey": self.key, "Authorization": f"Bearer {token or self.key}",
                "Content-Type": "application/json", **(headers or {})}
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=head)
        try:
            with self._opener.open(request, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError("network", f"인터넷에 연결하지 못했다: {type(exc).__name__}") from exc
        return status, _parse(raw)

    def login(self, email: str, password: str) -> dict:
        return self._token("password", {"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._token("refresh_token", {"refresh_token": refresh_token})

    def _token(self, grant: str, body: dict) -> dict:
        status, data = self._call("POST", f"/auth/v1/token?grant_type={grant}", body=body)
        if status in (400, 401, 422):
            raise CloudError("auth", "이메일 또는 비밀번호가 맞지 않거나 로그인이 만료됐다")
        if status >= 400 or not isinstance(data, dict) or "access_token" not in data:
            raise CloudError("server", f"로그인 서버 응답 이상 ({status})")
        return {"access_token": data["access_token"], "refresh_token": data.get("refresh_token"),
                "email": (data.get("user") or {}).get("email")}

    def rest(self, method: str, table: str, *, access: str, params: dict | None = None,
             body=None, prefer: str | None = None):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        headers = {"Prefer": prefer} if prefer else None
        status, data = self._call(method, f"/rest/v1/{table}{query}", token=access, body=body,
                                  headers=headers)
        if status == 401:
            raise CloudError("auth", "로그인이 만료됐다")
        if status >= 500:
            raise CloudError("server", f"서버 오류 ({status})")
        if status >= 400:
            detail = data.get("message", "") if isinstance(data, dict) else ""
            raise CloudError("rejected", f"서버가 거절했다 ({status}) {str(detail)[:120]}")
        return data


def _parse(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
