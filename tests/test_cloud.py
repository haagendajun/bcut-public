"""올리기 통신·서비스 시험. 이 컴퓨터 안의 가짜 슈파베이스 서버(127.0.0.1)를 쓴다."""

import json
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bcut.ui.cloud import CloudError, SupabaseClient, allowed_url
from bcut.ui.cloud_service import CloudService, handle
from bcut.ui.cloud_state import MemoryVault

UNIQUE = {"events": ("name",), "photos": ("event_id", "file_name", "file_size"),
          "photo_marks": ("id",), "review_sessions": ("id",)}


class Fake:
    def __init__(self):
        self.rows = {t: [] for t in UNIQUE}
        self.log = []          # (메서드, 경로)
        self.logins = 0
        self.fail_with = None  # 다음 REST 요청에 줄 상태 번호
        self.refresh_ok = True


def make_handler(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, data=None):
            raw = b"" if data is None else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n)) if n else None

        def _handle(self):
            url = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            fake.log.append((self.command, url.path))
            body = self._body()
            if url.path == "/auth/v1/token":
                return self._auth(q, body)
            if fake.fail_with:
                code, fake.fail_with = fake.fail_with, None
                return self._send(code, {"message": "boom"})
            if self.headers["Authorization"] != "Bearer tok-1":
                return self._send(401, {"message": "JWT expired"})
            table = url.path.rsplit("/", 1)[-1]
            getattr(self, "_" + self.command)(table, q, body)

        def _auth(self, q, body):
            if q["grant_type"] == "password":
                fake.logins += 1
                if body["password"] != "pw":
                    return self._send(400, {"error": "invalid_grant"})
            elif not fake.refresh_ok:
                return self._send(400, {"error": "bad refresh"})
            self._send(200, {"access_token": "tok-1", "refresh_token": "rt-2",
                             "user": {"email": "me@example.com"}})

        def _POST(self, table, q, body):
            keys = q["on_conflict"].split(",")
            for r in body:
                if any(all(x.get(k) == r.get(k) for k in keys) for x in fake.rows[table]):
                    continue
                if table == "photo_marks" and r["cancelled_at"] is None and any(
                        x["photo_id"] == r["photo_id"] and x["cancelled_at"] is None
                        for x in fake.rows[table]):
                    return self._send(409, {"message": "duplicate key one_active_per_photo"})
                row = dict(r)
                row.setdefault("id", str(uuid.uuid4()))
                fake.rows[table].append(row)
            self._send(201)

        def _GET(self, table, q, body):
            rows = fake.rows[table]
            for k, v in q.items():
                if v.startswith("eq."):
                    rows = [r for r in rows if str(r.get(k)) == v[3:]]
            self._send(200, rows)

        def _PATCH(self, table, q, body):
            for r in fake.rows[table]:
                if r["id"] == q["id"][3:]:
                    r.update(body)
            self._send(204)

        do_GET = do_POST = do_PATCH = _handle
    return H


@pytest.fixture
def fake():
    f = Fake()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(f))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    f.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield f
    srv.shutdown()


T0, T1, T5 = ("2026-10-20T10:00:00+09:00", "2026-10-20T10:01:00+09:00",
              "2026-10-20T10:05:00+09:00")
MARK = {"id": "a" * 32, "file": "A.CR3", "size": 10, "kind": "pick", "at": T0}
CANCEL = {"id": "c" * 32, "cancel": "a" * 32, "at": T1}
MAYBE = {"id": "b" * 32, "file": "A.CR3", "size": 10, "kind": "maybe", "at": T1}
REVIEW = {"id": "review-0001", "started_at": T0,
          "ended_at": T5, "photos_seen": 3, "pick_count": 1,
          "maybe_count": 0, "discard_count": 0, "tool_version": "t"}


def write_event(tmp_path, marks, reviews=()):
    folder = tmp_path / "events" / "ev"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "event.json").write_text(json.dumps({"name": "행사 A"}), encoding="utf-8")
    lines = lambda xs: "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in xs)  # noqa: E731
    (folder / "marks.jsonl").write_text(lines(marks), encoding="utf-8")
    (folder / "reviews.jsonl").write_text(lines(reviews), encoding="utf-8")


@pytest.fixture
def svc(tmp_path, fake):
    return CloudService(tmp_path, SupabaseClient(fake.url), MemoryVault())


def ready(svc):
    svc.consent()
    return svc.login("me@example.com", "pw")


def test_url_allowlist():
    assert allowed_url("https://abc.supabase.co/rest/v1/x")
    assert allowed_url("http://127.0.0.1:5/x")
    for bad in ("https://evil.example.com/", "http://abc.supabase.co/", "https://supabase.co.evil.io/",
                "ftp://abc.supabase.co/", "http://localhost/"):
        assert not allowed_url(bad)
    with pytest.raises(CloudError):
        SupabaseClient("https://evil.example.com")


def test_no_request_before_consent(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    svc.vault.set("rt-1")  # 토큰이 있어도 동의 전이면 보내지 않는다
    assert svc.status()["state"] == "need_consent"
    assert svc.sync()["state"] == "need_consent"
    assert handle(svc, "POST", "/api/cloud/login", {"email": "a@b.c", "password": "pw"})[0] == 403
    assert fake.log == []


def test_login_stores_only_refresh_token_not_password(tmp_path, fake, svc):
    ready(svc)
    assert svc.vault.get() == "rt-2"
    text = (tmp_path / "cloud.json").read_text(encoding="utf-8")
    assert "pw" not in json.loads(text).values() and "rt-2" not in text and '"pw"' not in text
    assert svc.status()["email"] == "me@example.com" and svc.status()["signed_in"]


def test_wrong_password_is_auth_error_and_not_signed_in(tmp_path, fake, svc):
    svc.consent()
    code, payload = handle(svc, "POST", "/api/cloud/login", {"email": "a@b.c", "password": "x"})
    assert code == 401 and payload["kind"] == "auth" and not svc.status()["signed_in"]


def test_sync_uploads_marks_photos_review_and_no_paths(tmp_path, fake, svc):
    write_event(tmp_path, [MARK, CANCEL, MAYBE], [REVIEW])
    ready(svc)
    assert svc.status()["pending"] == 3
    st = svc.sync()
    assert st["state"] == "synced" and st["pending"] == 0
    assert [e["name"] for e in fake.rows["events"]] == ["행사 A"]
    assert [(p["file_name"], p["file_size"]) for p in fake.rows["photos"]] == [("A.CR3", 10)]
    marks = {m["kind"]: m for m in fake.rows["photo_marks"]}
    assert marks["pick"]["cancelled_at"] == CANCEL["at"] and marks["maybe"]["cancelled_at"] is None
    assert len(fake.rows["review_sessions"]) == 1
    assert "folder" not in json.dumps(fake.rows) and "/" not in fake.rows["events"][0]["name"]
    assert not any(m == "DELETE" for m, _ in fake.log)


def test_second_sync_sends_nothing_and_no_duplicates(tmp_path, fake, svc):
    write_event(tmp_path, [MARK], [REVIEW])
    ready(svc)
    svc.sync()
    before = len(fake.log)
    svc.sync()
    assert len(fake.log) == before
    assert len(fake.rows["photo_marks"]) == 1 and len(fake.rows["review_sessions"]) == 1


def test_lost_state_file_is_safe_to_reupload(tmp_path, fake, svc):
    write_event(tmp_path, [MARK, CANCEL, MAYBE], [REVIEW])
    ready(svc)
    svc.sync()
    (tmp_path / "cloud.json").write_text(json.dumps({"consented_at": "x", "email": "e"}))
    again = CloudService(tmp_path, SupabaseClient(fake.url), svc.vault)
    assert again.sync()["state"] == "synced"
    assert len(fake.rows["photo_marks"]) == 2 and len(fake.rows["photos"]) == 1


def test_cancel_of_already_uploaded_mark_goes_before_new_mark(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    ready(svc)
    svc.sync()
    write_event(tmp_path, [MARK, CANCEL, MAYBE])  # 셀렉을 보류로 바꿨다
    assert svc.sync()["state"] == "synced"
    active = [m for m in fake.rows["photo_marks"] if m["cancelled_at"] is None]
    assert [m["kind"] for m in active] == ["maybe"] and len(fake.rows["photo_marks"]) == 2


def test_network_failure_keeps_pending_and_retries(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    ready(svc)
    svc.client = SupabaseClient("http://127.0.0.1:1", timeout=1)  # 아무도 듣지 않는 포트
    st = svc.sync()
    assert st["state"] == "error" and st["pending"] == 1 and "인터넷" in st["error"]
    svc.client = SupabaseClient(fake.url)
    assert svc.sync()["state"] == "synced"


def test_server_rejection_is_reported_not_raised(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    ready(svc)
    fake.fail_with = 400
    st = svc.sync()
    assert st["state"] == "error" and "400" in st["error"] and st["pending"] == 1


def test_expired_access_token_refreshes_once(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    ready(svc)
    svc._access = "stale"
    assert svc.sync()["state"] == "synced" and svc.vault.get() == "rt-2"


def test_dead_refresh_token_means_login_needed(tmp_path, fake, svc):
    write_event(tmp_path, [MARK])
    ready(svc)
    svc._access = "stale"
    fake.refresh_ok = False
    st = svc.sync()
    assert st["state"] == "need_login" and svc.vault.get() is None and st["pending"] == 1


def test_logout_forgets_token(tmp_path, fake, svc):
    ready(svc)
    st = svc.logout()
    assert st["state"] == "need_login" and svc.vault.get() is None and st["email"] is None
