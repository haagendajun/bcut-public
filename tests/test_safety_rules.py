"""제약 C1(네트워크 금지), C3(삭제 금지)를 코드 수준에서 지키는지 검사한다."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bcut"

# C1: 이 도구는 네트워크를 쓰지 않는다. 아래 모듈의 import를 금지한다.
BANNED_IMPORTS = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib", "xmlrpc",
    "requests", "httpx", "aiohttp", "urllib3", "websockets", "supabase",
}

# C3: 사진 삭제 API를 쓰지 않는다. (Phase 2에서 키워드 제거 등이 필요하면 이 목록을 검토한다)
BANNED_CALLS = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}


# 로컬 서버(Phase 3b S2)만 예외다 (사용자 승인 2026-10-20). 이 파일은 `http`만 쓸 수 있고, 그것도
# 서버 쪽(`http.server`, `HTTPStatus`)만이다. 나머지 금지 모듈(socket, urllib 등)은
# 이 파일에서도 금지다.
SERVER_FILE = SRC / "ui" / "server.py"
SERVER_ALLOWED = {"http"}


# 올리기 통신 파일(ADR-0009)만 예외다 (사용자 승인 2026-10-20 "추천대로").
# 이 파일은 `urllib`만 쓸 수 있다. 다른 파일은 네트워크 모듈을 쓰지 못하고,
# 이 파일에서도 socket·ssl·http는 금지다.
CLOUD_FILE = SRC / "ui" / "cloud.py"
CLOUD_ALLOWED = {"urllib"}


def _sources():
    return sorted(SRC.rglob("*.py"))


def test_there_is_source_to_check():
    assert _sources()


def test_no_network_imports():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            allowed = {SERVER_FILE: SERVER_ALLOWED, CLOUD_FILE: CLOUD_ALLOWED}.get(path, set())
            offenders += [f"{path.name}: {n}" for n in names
                          if n in BANNED_IMPORTS and n not in allowed]
    assert not offenders, f"네트워크 모듈 import 금지(C1): {offenders}"


def test_no_delete_calls():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in BANNED_CALLS:
                    offenders.append(f"{path.name}: {name}()")
    assert not offenders, f"삭제 호출 금지(C3): {offenders}"


def _http_imports(tree):
    """`http` 패키지에서 가져온 것들 (모듈 경로나 이름)."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "http"]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "http":
                found += [f"{node.module}:{a.name}" for a in node.names]
    return found


def test_only_the_local_server_may_use_http_and_only_its_server_side():
    users = []
    for path in _sources():
        found = _http_imports(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            users.append(path)
    assert users == [SERVER_FILE]
    found = _http_imports(ast.parse(SERVER_FILE.read_text(encoding="utf-8")))
    allowed = {"http:HTTPStatus", "http.server:BaseHTTPRequestHandler",
               "http.server:ThreadingHTTPServer"}
    extra = set(found) - allowed  # 접속하는 쪽(클라이언트) 모듈은 여기에 걸린다
    assert not extra, f"서버 쪽이 아닌 http 사용: {extra}"


def test_server_has_no_wildcard_or_external_bind_and_no_client_code():
    text = SERVER_FILE.read_text(encoding="utf-8")
    for bad in ("0.0.0.0", '"::"', "'::'", "create_connection", "urlopen", "http.client",
                "HTTPConnection", "HTTPSConnection", ".connect("):
        assert bad not in text, f"서버 파일에 금지된 표현: {bad}"


def test_only_cloud_file_uses_urllib():
    users = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(m.split(".")[0] == "urllib" for m in mods) and path != CLOUD_FILE:
                users.append(path.name)
    assert not users, f"urllib는 ui/cloud.py에서만 쓴다: {users}"


def test_cloud_file_has_no_secret_keys():
    text = CLOUD_FILE.read_text(encoding="utf-8")
    assert "sb_secret_" not in text and "service_role" not in text
    assert "sb_publishable_" in text  # 공개용 열쇠만
