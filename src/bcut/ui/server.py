"""로컬 서버 (devplan Phase 3b S2).

**이 프로젝트에서 네트워크 모듈(`http`)을 쓰는 유일한 파일이다.**

앱 화면(Electron 창)이 분석·썸네일·정리를 부르는 API를 제공한다. 사진이 컴퓨터 밖으로 나가지 않게
아래 규칙을 **코드와 테스트(`tests/test_ui_server.py`, `tests/test_safety_rules.py`)로 고정**한다.

1. **`127.0.0.1`에만 연다.** 다른 주소로는 열 수 없다 (`make_server`가 거부한다).
2. **모든 요청에 토큰이 필요하다.** 실행할 때마다 새 무작위 토큰을 만들고(헤더 `X-Token` 또는 주소의
   `t=`), 비교는 `secrets.compare_digest`로 한다. 토큰이 없거나 틀리면 401.
3. **다른 웹페이지가 이 서버를 부르지 못하게 한다.** `Host`가 `127.0.0.1:<포트>`(또는 `localhost`)가
   아니면 403 (DNS 리바인딩 방지), `Origin`이 있으면 같은 곳이어야 한다. CORS 헤더는 주지 않는다.
4. **밖으로 나가는 접속을 하지 않는다.** 접속하는 쪽(클라이언트) 코드를 쓰지 않고, 이 파일은
   서버 쪽 모듈만 가져온다.
5. 파일 이름은 분석 결과에 있는 것만 받는다 (경로 조작 방지). 행사 폴더에는 아무것도 쓰지 않는다.

API (모두 JSON, 토큰 필요):
  GET  /api/health                      -> {ok, version}
  GET  /  /app.js  /logic.js  /review_logic.js  /review.js  /sort_view.js  /migrate.js  /style.css
                                        -> 화면 파일 (토큰 주입)
  POST /api/choose-folder               -> {folder|null}  (맥의 폴더 선택 창)
  POST /api/reveal {path}               -> Finder에서 열기 (이 서버가 만든 정리 결과 폴더만)
  POST /api/scan   {folder}             -> {job}  (백그라운드 분석 시작)
  GET  /api/jobs/<job>                  -> {state, done, total, counts, error}
  GET  /api/jobs/<job>/results          -> {rows: [...]}
  GET  /api/jobs/<job>/thumb/<파일>      -> JPEG 썸네일
  GET  /api/jobs/<job>/photo/<파일>?size=view|full -> 사진 (내장 JPEG)
  POST /api/jobs/<job>/sort {rescue, commit, out, by_reason} -> 미리보기 또는 정리 결과
  GET  /api/jobs/<job>/marks            -> {marks: [{file, size, kind}], broken}  (셀렉·보류·버릴컷)
  POST /api/jobs/<job>/marks {file, kind|null} -> {file, size, kind}  (표시, 앞 표시는 취소)
  GET  /api/jobs/<job>/faces/<파일>      -> {w, h, faces: [{box, area, eyes}]}  (얼굴·눈 위치)
  GET  /api/cloud/status · POST /api/cloud/consent|login|logout|sync -> 올리기 (cloud_service)
  POST /api/jobs/<job>/review {id, started_at, ended_at, seen, pick, maybe, discard} -> 훑기 기록
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bcut import __version__
from bcut.organize import SortError, run_sort
from bcut.report.csv_report import write_csv
from bcut.scan import PhotoResult, count_by_status, list_photos, scan_folder
from bcut.ui.cloud import SupabaseClient
from bcut.ui.cloud_service import CloudService
from bcut.ui.cloud_service import handle as handle_cloud
from bcut.ui.cloud_state import MacKeychain
from bcut.ui.faces import face_info
from bcut.ui.marks import MarkStore, file_size, list_marks, post_mark
from bcut.ui.photos import (  # noqa: F401  rotate_*는 기존 이름으로도 쓰이도록 다시 내보낸다
    default_orientation,
    default_read_photo,
    rotate_image,
    rotate_jpeg,
)
from bcut.ui.reviews import ReviewStore, post_review

LOOPBACK = "127.0.0.1"
MAX_BODY = 1_000_000  # 요청 본문 상한 (바이트)
TOKEN_BYTES = 16

_PCT = re.compile(rb"%([0-9A-Fa-f]{2})")


def unquote(s: str) -> str:
    """주소의 %XX를 풀어 글자로 되돌린다 (urllib을 쓰지 않으려고 직접 구현)."""
    raw = s.encode("utf-8", errors="surrogateescape")
    return _PCT.sub(lambda m: bytes([int(m.group(1), 16)]), raw).decode("utf-8", errors="replace")


def split_target(target: str) -> tuple[str, dict[str, str]]:
    path, _, query = target.partition("?")
    params: dict[str, str] = {}
    for part in query.split("&") if query else []:
        k, _, v = part.partition("=")
        params[unquote(k)] = unquote(v)
    return unquote(path), params


# ---- 분석 작업 ---------------------------------------------------------------------------

@dataclass
class ScanJob:
    id: str
    folder: Path
    out_dir: Path
    state: str = "pending"  # pending | running | done | error
    done: int = 0
    total: int = 0
    results: list[PhotoResult] = field(default_factory=list)
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    thumbs: dict[str, bytes] = field(default_factory=dict)  # 회전을 바로잡은 썸네일 모음
    faces: dict[str, dict] = field(default_factory=dict)  # 불러온 얼굴 정보 (한 번만 계산)

    def by_name(self) -> dict[str, PhotoResult]:
        return {r.file: r for r in self.results}

    @property
    def report(self) -> Path:
        return self.out_dir / "bcut-report.csv"


@dataclass
class ServerConfig:
    token: str
    data_dir: Path
    scan: Callable[..., list[PhotoResult]] = scan_folder
    read_photo: Callable[[Path, str], bytes] | None = None  # (경로, "view"|"full") -> JPEG 바이트
    choose_folder: Callable[[], str | None] | None = None  # 폴더 선택 창 (없으면 맥 기본 창)
    # 사진의 회전 정보 (rawpy flip 값). 없으면 파일에서 읽는다
    orientation: Callable[[Path], int] | None = None
    faces: Callable[[Path, int], dict] | None = None  # (경로, 회전) -> 얼굴 정보. 없으면 인식
    reveal: Callable[[Path], None] | None = None  # Finder에서 열기 (없으면 `open`)
    workers: int | None = None
    cloud: CloudService | None = None  # 올리기 서비스 (없으면 실제 슈파베이스용을 만든다)


def _row(r: PhotoResult) -> dict:
    return {
        "file": r.file, "status": r.status, "reasons": list(r.reasons), "score": r.score,
        "confidence": r.confidence, "note": r.note, "faces": r.face_count,
        "exposure": r.exposure_kind, "sharpness": r.sharpness_kind,
        "sharp_best": r.sharpness_best, "sharp_face": r.sharpness_face, "error": r.error,
    }


def default_choose_folder() -> str | None:
    """맥의 폴더 선택 창을 띄운다. 취소하면 None."""
    from bcut.bridge.osascript import AppleScriptError, run_script

    prompt = "사진 폴더를 고르세요"
    script = f'on run argv\n return POSIX path of (choose folder with prompt "{prompt}")\nend run'
    try:
        out = run_script(script, timeout=600)
    except AppleScriptError as exc:
        if "-128" in str(exc):  # 사용자가 취소
            return None
        raise
    return out.rstrip("/") or None


def default_reveal(path: Path) -> None:
    import subprocess

    subprocess.run(["open", str(path)], check=False)


WEB_DIR = Path(__file__).parent / "web"
STATIC = {"/app.js": ("app.js", "text/javascript"), "/logic.js": ("logic.js", "text/javascript"),
          "/review_logic.js": ("review_logic.js", "text/javascript"),
          "/review.js": ("review.js", "text/javascript"),
          "/sort_view.js": ("sort_view.js", "text/javascript"),
          "/migrate.js": ("migrate.js", "text/javascript"),
          "/cloud_view.js": ("cloud_view.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}


class AppState:
    """서버가 들고 있는 상태: 분석 작업들."""

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg
        self.jobs: dict[str, ScanJob] = {}
        self.revealable: set[str] = set()  # 이 서버가 만든 정리 결과 폴더만 Finder에서 열 수 있다
        self.lock = threading.Lock()
        self.marks = MarkStore(cfg.data_dir / "events")  # 셀렉·보류·버릴 컷 표시 (행사 단위)
        self.faces_lock = threading.Lock()  # 얼굴 인식은 한 번에 하나씩
        self.reviews = ReviewStore(cfg.data_dir / "events")  # 훑기 기록 (행사 단위)
        self.cloud = cfg.cloud or CloudService(cfg.data_dir, SupabaseClient(), MacKeychain())

    def start_scan(self, folder: Path) -> ScanJob:
        job_id = secrets.token_hex(6)
        job = ScanJob(id=job_id, folder=folder, out_dir=self.cfg.data_dir / "jobs" / job_id)
        with self.lock:
            self.jobs[job_id] = job
        threading.Thread(target=self._run_scan, args=(job,), daemon=True).start()
        return job

    def _run_scan(self, job: ScanJob) -> None:
        job.state = "running"
        try:
            job.total = len(list_photos(job.folder))

            def progress(done: int, total: int) -> None:
                job.done, job.total = done, total

            kwargs = {"progress": progress}
            if self.cfg.workers is not None:
                kwargs["workers"] = self.cfg.workers
            job.results = self.cfg.scan(job.folder, **kwargs)
            job.out_dir.mkdir(parents=True, exist_ok=True)
            write_csv(job.results, job.report, tool_version=__version__)
            job.done = job.total = len(job.results)
            job.state = "done"
        except Exception as exc:  # noqa: BLE001  분석 실패는 작업 상태로 알린다
            job.error = f"{type(exc).__name__}: {exc}"
            job.state = "error"

    def thumbnail(self, job: ScanJob, name: str, data: bytes) -> bytes:
        """회전 정보대로 똑바로 세운 썸네일 (한 번 만들면 기억해 둔다)."""
        with self.lock:
            cached = job.thumbs.get(name)
        if cached is not None:
            return cached
        flip = (self.cfg.orientation or default_orientation)(job.folder / name)
        out = rotate_jpeg(data, flip)
        with self.lock:
            job.thumbs[name] = out
        return out

    def job(self, job_id: str) -> ScanJob | None:
        with self.lock:
            return self.jobs.get(job_id)


# ---- HTTP -------------------------------------------------------------------------------

def index_html(token: str) -> bytes:
    """화면의 첫 페이지. 토큰을 넣어 줘서 화면이 API와 파일을 부를 수 있게 한다."""
    return (WEB_DIR / "index.html").read_text(encoding="utf-8").replace(
        "__TOKEN__", token).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    state: AppState  # make_server가 하위 클래스로 지정한다
    server_version = "bcut"
    sys_version = ""

    # 기본 로그(접속 기록)를 끈다: 사진 파일 이름이 로그에 남지 않게 한다
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    # ---- 공통 보호 ----
    def _port(self) -> int:
        return self.server.server_address[1]

    def _guard(self, path: str, params: dict[str, str]) -> bool:
        """Host·Origin·토큰을 확인한다. 통과하지 못하면 응답을 보내고 False."""
        port = self._port()
        host = self.headers.get("Host", "")
        if host not in (f"{LOOPBACK}:{port}", f"localhost:{port}"):
            self._send(HTTPStatus.FORBIDDEN, {"error": "허용되지 않은 Host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in (f"http://{LOOPBACK}:{port}",
                                                 f"http://localhost:{port}"):
            self._send(HTTPStatus.FORBIDDEN, {"error": "허용되지 않은 Origin"})
            return False
        given = self.headers.get("X-Token") or params.get("t", "")
        if not secrets.compare_digest(given.encode(), self.state.cfg.token.encode()):
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "토큰이 필요하다"})
            return False
        return True

    def _send(self, status: HTTPStatus, body: dict | bytes,
              ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(
            body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        charset = "" if ctype == "image/jpeg" else "; charset=utf-8"
        self.send_header("Content-Type", ctype + charset)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: blob:; object-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "Content-Length가 올바르지 않다"})
            return None
        if length > MAX_BODY:
            self.close_connection = True  # 큰 본문을 끝까지 읽지 않는다
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "요청이 너무 크다"})
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "JSON이 아니다"})
            return None
        if not isinstance(body, dict):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "JSON 객체여야 한다"})
            return None
        return body

    # ---- 메서드 ----
    def do_GET(self) -> None:  # noqa: N802
        path, params = split_target(self.path)
        if not self._guard(path, params):
            return
        self._route("GET", path, params)

    def do_POST(self) -> None:  # noqa: N802
        path, params = split_target(self.path)
        if not self._guard(path, params):
            return
        self._route("POST", path, params)

    def _other(self) -> None:
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "허용되지 않은 메서드"})

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _other  # noqa: N815

    # ---- 라우팅 ----
    def _route(self, method: str, path: str, params: dict[str, str]) -> None:
        if method == "GET" and path == "/":
            return self._send(HTTPStatus.OK, index_html(self.state.cfg.token), "text/html")
        if method == "GET" and path in STATIC:
            name, ctype = STATIC[path]
            return self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), ctype)
        if method == "POST" and path == "/api/choose-folder":
            return self._choose_folder()
        if method == "POST" and path == "/api/reveal":
            return self._reveal()
        if method == "GET" and path == "/api/health":
            return self._send(HTTPStatus.OK, {"ok": True, "version": __version__})
        if method == "POST" and path == "/api/scan":
            return self._scan()
        if path.startswith("/api/cloud/"):
            return self._cloud(method, path)
        m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})(/.*)?", path)
        if m:
            job = self.state.job(m.group(1))
            if job is None:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "없는 작업"})
            return self._job_route(method, job, m.group(2) or "", params)
        self._send(HTTPStatus.NOT_FOUND, {"error": "없는 주소"})

    def _choose_folder(self) -> None:
        chooser = self.state.cfg.choose_folder or default_choose_folder
        try:
            folder = chooser()
        except Exception as exc:  # noqa: BLE001
            return self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                              {"error": f"폴더 선택 창을 열 수 없다: {type(exc).__name__}"})
        self._send(HTTPStatus.OK, {"folder": folder})

    def _reveal(self) -> None:
        body = self._json_body()
        if body is None:
            return
        path = body.get("path")
        if not isinstance(path, str) or path not in self.state.revealable:
            msg = "이 서버가 만든 정리 결과 폴더만 열 수 있다"
            return self._send(HTTPStatus.FORBIDDEN, {"error": msg})
        (self.state.cfg.reveal or default_reveal)(Path(path))
        self._send(HTTPStatus.OK, {"ok": True})

    def _scan(self) -> None:
        body = self._json_body()
        if body is None:
            return
        folder = body.get("folder")
        if not isinstance(folder, str) or not Path(folder).is_absolute():
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "folder는 절대 경로 글자여야 한다"})
        p = Path(folder)
        if p.is_file():  # 사진 파일을 끌어다 놓았으면 그 파일이 있는 폴더를 쓴다
            p = p.parent
        if not p.is_dir():
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "폴더가 없다"})
        if not list_photos(p):
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "사진(CR3)이 없다"})
        job = self.state.start_scan(p)
        self._send(HTTPStatus.ACCEPTED, {"job": job.id})

    def _job_route(self, method: str, job: ScanJob, rest: str, params: dict[str, str]) -> None:
        if method == "GET" and rest == "":
            counts = count_by_status(job.results) if job.state == "done" else {}
            return self._send(HTTPStatus.OK, {
                "state": job.state, "done": job.done, "total": job.total,
                "counts": counts, "error": job.error, "folder": str(job.folder)})
        if job.state != "done":
            return self._send(HTTPStatus.CONFLICT, {"error": "분석이 아직 끝나지 않았다",
                                                    "state": job.state})
        if method == "GET" and rest == "/results":
            return self._send(HTTPStatus.OK, {"rows": [
                {**_row(r), "size": file_size(job.folder / r.file)} for r in job.results]})
        if rest == "/marks" and method in ("GET", "POST"):
            return self._marks(job, method)
        m = re.fullmatch(r"/(thumb|photo)/(.+)", rest)
        if method == "GET" and m:
            return self._image(job, m.group(1), m.group(2), params)
        m = re.fullmatch(r"/faces/(.+)", rest)
        if method == "GET" and m:
            return self._faces(job, m.group(1))
        if method == "POST" and rest == "/review":
            return self._review(job)
        if method == "POST" and rest == "/sort":
            return self._sort(job)
        self._send(HTTPStatus.NOT_FOUND, {"error": "없는 주소"})

    def _cloud(self, method: str, path: str) -> None:
        body = self._json_body() if method == "POST" else None
        if method == "POST" and body is None:
            return
        status, payload = handle_cloud(self.state.cloud, method, path, body)
        self._send(HTTPStatus(status), payload)

    def _marks(self, job: ScanJob, method: str) -> None:
        names = set(job.by_name())
        if method == "GET":
            return self._send(HTTPStatus.OK, list_marks(self.state.marks, job.folder, names))
        body = self._json_body()
        if body is not None:
            status, payload = post_mark(self.state.marks, job.folder, names, body)
            self._send(HTTPStatus(status), payload)

    def _review(self, job: ScanJob) -> None:
        body = self._json_body()
        if body is not None:
            status, payload = post_review(self.state.reviews, job.folder, job.id, body, __version__)
            self._send(HTTPStatus(status), payload)

    def _faces(self, job: ScanJob, name: str) -> None:
        if name not in job.by_name():  # 분석 결과에 있는 파일 이름만 (경로 조작 방지)
            return self._send(HTTPStatus.NOT_FOUND, {"error": "없는 사진"})
        with self.state.faces_lock:
            info = job.faces.get(name)
            if info is None:
                path = job.folder / name
                flip = (self.state.cfg.orientation or default_orientation)(path)
                finder = self.state.cfg.faces or face_info
                try:
                    info = job.faces[name] = finder(path, flip)
                except Exception as exc:  # noqa: BLE001  얼굴 정보가 없어도 훑기는 계속된다
                    return self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                                      {"error": f"얼굴 정보를 읽을 수 없다: {type(exc).__name__}"})
        self._send(HTTPStatus.OK, info)

    def _image(self, job: ScanJob, kind: str, name: str, params: dict[str, str]) -> None:
        result = job.by_name().get(name)  # 분석 결과에 있는 파일 이름만 (경로 조작 방지)
        if result is None:
            return self._send(HTTPStatus.NOT_FOUND, {"error": "없는 사진"})
        if kind == "thumb":
            if not result.thumbnail:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "썸네일이 없다"})
            return self._send(HTTPStatus.OK, self.state.thumbnail(job, name, result.thumbnail),
                              "image/jpeg")
        size = params.get("size", "view")
        if size not in ("view", "full"):
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "size는 view 또는 full"})
        reader = self.state.cfg.read_photo or default_read_photo
        try:
            data = reader(job.folder / name, size)
        except Exception as exc:  # noqa: BLE001
            return self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                              {"error": f"사진을 읽을 수 없다: {type(exc).__name__}"})
        self._send(HTTPStatus.OK, data, "image/jpeg")

    def _sort(self, job: ScanJob) -> None:
        body = self._json_body()
        if body is None:
            return
        rescue = body.get("rescue", [])
        if not isinstance(rescue, list) or not all(isinstance(x, str) for x in rescue):
            return self._send(HTTPStatus.BAD_REQUEST,
                              {"error": "rescue는 파일 이름 목록이어야 한다"})
        out = body.get("out")
        if out is not None and (not isinstance(out, str) or not Path(out).is_absolute()):
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "out은 절대 경로여야 한다"})
        out_root = Path(out) if out else job.out_dir / "정리"
        folder = job.folder.resolve()
        target = out_root.resolve()
        if target == folder or folder in target.parents:
            msg = "정리 결과 폴더가 행사 폴더 안이다. 행사 폴더에는 쓰지 않는다"
            return self._send(HTTPStatus.BAD_REQUEST, {"error": msg})
        names = set(job.by_name())
        known = {n for n in rescue if n in names}
        # 셀렉·보류·버릴 컷 표시는 화면이 보낸 것이 아니라 서버에 저장된 것을 쓴다
        stored = list_marks(self.state.marks, job.folder, names)["marks"]
        marks = {m["file"]: m["kind"] for m in stored}
        try:
            result = run_sort(
                job.folder, job.report, out_root, commit=bool(body.get("commit", False)),
                rescue=known, marks=marks, by_reason=bool(body.get("by_reason", True)))
        except SortError as exc:
            return self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        plan = result.plan
        if result.result_dir:
            with self.state.lock:
                self.state.revealable.add(str(result.result_dir))
        self._send(HTTPStatus.OK, {
            "out_root": str(out_root),
            "mode": result.mode, "counts": plan.counts(), "photos": plan.files,
            "placements": plan.placements, "rescued": plan.rescued, "missing": plan.missing,
            "unlisted": plan.unlisted, "method": result.method, "needs_space": result.needs_space,
            "result_dir": str(result.result_dir) if result.result_dir else None,
            "cloned": result.cloned, "copied": result.copied, "aborted": result.aborted,
            "mismatches": result.mismatches, "marked": plan.mark_counts(),
        })


def make_server(cfg: ServerConfig, host: str = LOOPBACK, port: int = 0) -> ThreadingHTTPServer:
    """서버를 만든다 (아직 요청을 받지 않는다). **127.0.0.1이 아닌 주소는 거부한다.**"""
    if host != LOOPBACK:
        raise ValueError(f"이 서버는 {LOOPBACK}에만 열 수 있다: {host!r}")
    if len(cfg.token) < 16:
        raise ValueError("토큰이 너무 짧다")
    state = AppState(cfg)
    handler = type("Handler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer((LOOPBACK, port), handler)
    server.daemon_threads = True
    server.app_state = state  # type: ignore[attr-defined]
    return server


def new_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def serve(data_dir: Path, port: int = 0, token: str | None = None,
          announce: Callable[[str, str], None] | None = None) -> None:
    """서버를 띄우고 멈출 때까지 기다린다. `announce(주소, 토큰)`으로 화면 쪽에 알린다."""
    token = token or new_token()
    server = make_server(ServerConfig(token=token, data_dir=data_dir), port=port)
    url = f"http://{LOOPBACK}:{server.server_address[1]}"
    if announce:
        announce(url, token)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
