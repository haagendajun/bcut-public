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
            offenders += [f"{path.name}: {n}" for n in names if n in BANNED_IMPORTS]
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
