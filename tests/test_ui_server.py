import http.client
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from bcut.scan import PhotoResult
from bcut.ui import server as srv
from bcut.ui.server import ServerConfig, make_server, split_target, unquote

TOKEN = "t" * 32


def jpeg(color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "JPEG")
    return buf.getvalue()


def result(name, status="normal", reasons_kind=None, thumb=True):
    return PhotoResult(
        file=name, status=status, score=0.3, note=None, face_count=1, faces_considered=1,
        eye_width_frac=0.01, thumbnail=jpeg() if thumb else None,
        eyes_status="candidate" if status == "candidate" else "normal",
        exposure_kind=reasons_kind, confidence=0.9 if status == "candidate" else None)


@pytest.fixture
def world(tmp_path):
    ev = tmp_path / "행사"
    ev.mkdir()
    for n in ("A.CR3", "B.CR3", "C.CR3"):
        (ev / n).write_bytes(n.encode() * 50)
    calls = {"scan": 0}

    def fake_scan(folder, progress=None, **kw):
        calls["scan"] += 1
        out = [result("A.CR3", "candidate"), result("B.CR3", "review", "under"),
               result("C.CR3", "normal")]
        for i in range(1, len(out) + 1):
            if progress:
                progress(i, len(out))
        return out

    cfg = ServerConfig(token=TOKEN, data_dir=tmp_path / "data", scan=fake_scan,
                       read_photo=lambda p, size: jpeg((1, 2, 3)) if size == "view" else b"FULL")
    server = make_server(cfg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, ev, tmp_path, calls
    server.shutdown()
    server.server_close()


def call(server, method, path, body=None, headers=None, host=None, token=True):
    port = server.server_address[1]
    h = {"Host": host or f"127.0.0.1:{port}"}
    if token:
        h["X-Token"] = TOKEN
    h.update(headers or {})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    if data is not None:
        h.setdefault("Content-Length", str(len(data)))
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, dict(r.getheaders()), raw


def jbody(raw):
    return json.loads(raw.decode("utf-8"))


def wait_done(server, job):
    for _ in range(200):
        st, _, raw = call(server, "GET", f"/api/jobs/{job}")
        if jbody(raw)["state"] in ("done", "error"):
            return jbody(raw)
        time.sleep(0.02)
    raise AssertionError("분석이 끝나지 않았다")


# ---- 보안: 127.0.0.1, 토큰, Host/Origin ---------------------------------------------------

def test_binds_only_to_loopback(world):
    server, *_ = world
    assert server.server_address[0] == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.0.5", "localhost", "example.com"])
def test_refuses_to_bind_anywhere_else(tmp_path, host):
    with pytest.raises(ValueError, match="127.0.0.1"):
        make_server(ServerConfig(token=TOKEN, data_dir=tmp_path), host=host)


def test_short_token_is_refused(tmp_path):
    with pytest.raises(ValueError, match="토큰"):
        make_server(ServerConfig(token="abc", data_dir=tmp_path))


def test_every_request_needs_the_token(world):
    server, *_ = world
    for method, path in (("GET", "/"), ("GET", "/api/health"), ("POST", "/api/scan"),
                         ("GET", "/api/jobs/abcdefabcdef"), ("GET", "/nope")):
        status, _, raw = call(server, method, path, body=b"{}" if method == "POST" else None,
                              token=False)
        assert status == 401, (method, path)
    status, _, _ = call(server, "GET", "/api/health", headers={"X-Token": "wrong" * 8}, token=False)
    assert status == 401
    status, _, raw = call(server, "GET", "/api/health")
    assert status == 200 and jbody(raw)["ok"] is True


def test_token_in_query_works_for_get_and_wrong_one_does_not(world):
    server, *_ = world
    status, _, _ = call(server, "GET", f"/api/health?t={TOKEN}", token=False)
    assert status == 200
    status, _, _ = call(server, "GET", "/api/health?t=bad", token=False)
    assert status == 401


def test_token_is_compared_in_constant_time():
    assert "compare_digest" in Path(srv.__file__).read_text(encoding="utf-8")


def test_foreign_host_header_is_rejected(world):
    server, *_ = world
    for host in ("evil.example.com", "127.0.0.1:1", "localhost", "127.0.0.1"):
        status, _, _ = call(server, "GET", "/api/health", host=host)
        assert status == 403, host
    port = server.server_address[1]
    assert call(server, "GET", "/api/health", host=f"localhost:{port}")[0] == 200


def test_cross_site_origin_is_rejected_and_no_cors_headers(world):
    server, *_ = world
    port = server.server_address[1]
    status, _, _ = call(server, "POST", "/api/scan", body={"folder": "/x"},
                        headers={"Origin": "https://evil.example.com"})
    assert status == 403
    status, headers, _ = call(server, "GET", "/api/health",
                              headers={"Origin": f"http://127.0.0.1:{port}"})
    assert status == 200
    assert not any(k.lower().startswith("access-control") for k in headers)
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"


def test_other_methods_not_allowed(world):
    server, *_ = world
    for m in ("PUT", "DELETE", "PATCH"):
        assert call(server, m, "/api/health")[0] == 405


def test_access_log_is_silent(world, capsys):
    server, *_ = world
    call(server, "GET", "/api/health")
    assert capsys.readouterr().err == ""  # 접속 기록(파일 이름 포함)이 남지 않는다


# ---- 분석 작업 ----------------------------------------------------------------------------

def start_job(server, ev):
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    wait_done(server, job)
    return job


# ---- 표시: 셀렉·보류·버릴 컷 (훑기 모드) ----------------------------------------------------

def test_results_include_the_file_size(world):
    server, ev, *_ = world
    job = start_job(server, ev)
    rows = {r["file"]: r for r in jbody(call(server, "GET", f"/api/jobs/{job}/results")[2])["rows"]}
    assert rows["A.CR3"]["size"] == (ev / "A.CR3").stat().st_size == 250


def test_marks_start_empty_and_need_the_token(world):
    server, ev, *_ = world
    job = start_job(server, ev)
    assert jbody(call(server, "GET", f"/api/jobs/{job}/marks")[2]) == {"marks": [], "broken": 0}
    assert call(server, "GET", f"/api/jobs/{job}/marks", token=False)[0] == 401
    assert call(server, "POST", f"/api/jobs/{job}/marks", {"file": "A.CR3", "kind": "pick"},
                token=False)[0] == 401


def test_set_replace_and_clear_a_mark(world):
    server, ev, *_ = world
    job = start_job(server, ev)

    def post(file, kind):
        return call(server, "POST", f"/api/jobs/{job}/marks", {"file": file, "kind": kind})

    def current():
        return {m["file"]: m["kind"] for m in jbody(call(server, "GET", f"/api/jobs/{job}/marks")[2])["marks"]}

    status, _, raw = post("A.CR3", "pick")
    assert status == 200 and jbody(raw) == {"file": "A.CR3", "size": 250, "kind": "pick"}
    post("B.CR3", "maybe")
    assert current() == {"A.CR3": "pick", "B.CR3": "maybe"}
    post("A.CR3", "discard")  # 새 표시가 앞 표시를 바꾼다 (한 장에 하나)
    assert current() == {"A.CR3": "discard", "B.CR3": "maybe"}
    assert jbody(post("A.CR3", None)[2])["kind"] is None  # 해제
    assert current() == {"B.CR3": "maybe"}


def test_marks_stay_when_the_same_event_is_scanned_again(world):
    server, ev, *_ = world
    first = start_job(server, ev)
    call(server, "POST", f"/api/jobs/{first}/marks", {"file": "C.CR3", "kind": "pick"})
    second = start_job(server, ev)  # 다시 검사하면 작업 번호가 바뀐다
    assert second != first
    marks = jbody(call(server, "GET", f"/api/jobs/{second}/marks")[2])["marks"]
    assert marks == [{"file": "C.CR3", "size": 250, "kind": "pick"}]


def test_marks_reject_bad_input(world):
    server, ev, *_ = world
    job = start_job(server, ev)
    url = f"/api/jobs/{job}/marks"
    assert call(server, "POST", url, {"file": "../A.CR3", "kind": "pick"})[0] == 404  # 경로 조작
    assert call(server, "POST", url, {"file": "없는.CR3", "kind": "pick"})[0] == 404
    assert call(server, "POST", url, {"file": "A.CR3", "kind": "like"})[0] == 400
    assert call(server, "POST", url, {"kind": "pick"})[0] == 404
    assert call(server, "POST", url, b"not json")[0] == 400
    assert call(server, "PUT", url, {"file": "A.CR3", "kind": "pick"})[0] == 405
    assert jbody(call(server, "GET", url)[2])["marks"] == []


def test_sort_uses_the_stored_marks_for_pick_maybe_discard_folders(world):
    server, ev, tmp, _ = world
    job = start_job(server, ev)
    for name, kind in (("A.CR3", "pick"), ("B.CR3", "maybe"), ("C.CR3", "discard")):
        call(server, "POST", f"/api/jobs/{job}/marks", {"file": name, "kind": kind})
    before = sorted(p.read_bytes() for p in ev.iterdir())
    out = tmp / "담기"
    status, _, raw = call(server, "POST", f"/api/jobs/{job}/sort", {"commit": False, "out": str(out)})
    plan = jbody(raw)
    assert status == 200
    assert plan["counts"]["셀렉"] == 1 and plan["counts"]["보류"] == 1 and plan["counts"]["버릴 것 같은 컷"] == 1
    assert list(plan["counts"])[0] == "셀렉" and plan["marked"] == {"pick": 1, "maybe": 1, "discard": 1}
    assert not out.exists()  # 미리보기는 아무것도 만들지 않는다
    done = jbody(call(server, "POST", f"/api/jobs/{job}/sort", {"commit": True, "out": str(out)})[2])
    d = Path(done["result_dir"])
    assert (d / "셀렉" / "A.CR3").exists() and (d / "보류" / "B.CR3").exists()
    assert (d / "버릴 것 같은 컷" / "C.CR3").exists()
    assert sorted(p.read_bytes() for p in ev.iterdir()) == before  # 원본은 그대로


def test_sort_ignores_marks_sent_by_the_screen_and_other_events(world):
    server, ev, tmp, _ = world
    job = start_job(server, ev)
    body = {"commit": False, "marks": {"A.CR3": "pick"}, "out": str(tmp / "o")}
    plan = jbody(call(server, "POST", f"/api/jobs/{job}/sort", body)[2])
    assert plan["marked"] == {"pick": 0, "maybe": 0, "discard": 0}  # 저장된 표시만 쓴다


def test_marks_are_not_written_into_the_event_folder(world):
    server, ev, tmp, _ = world
    job = start_job(server, ev)
    before = sorted(p.name for p in ev.iterdir())
    call(server, "POST", f"/api/jobs/{job}/marks", {"file": "A.CR3", "kind": "pick"})
    assert sorted(p.name for p in ev.iterdir()) == before  # 원본 폴더에는 아무것도 쓰지 않는다
    assert (tmp / "data" / "events" / "행사" / "marks.jsonl").exists()

def test_scan_job_flow_results_and_thumbnails(world):
    server, ev, tmp, calls = world
    status, _, raw = call(server, "POST", "/api/scan", {"folder": str(ev)})
    assert status == 202
    job = jbody(raw)["job"]
    info = wait_done(server, job)
    assert info["state"] == "done" and info["total"] == 3 and info["done"] == 3
    assert info["counts"]["candidate"] == 1 and info["counts"]["review"] == 1
    status, _, raw = call(server, "GET", f"/api/jobs/{job}/results")
    rows = {r["file"]: r for r in jbody(raw)["rows"]}
    assert rows["A.CR3"]["status"] == "candidate" and rows["B.CR3"]["exposure"] == "under"
    assert (tmp / "data" / "jobs" / job / "bcut-report.csv").exists()
    status, headers, raw = call(server, "GET", f"/api/jobs/{job}/thumb/A.CR3")
    assert status == 200 and headers["Content-Type"] == "image/jpeg" and raw[:2] == b"\xff\xd8"
    # 큰 사진: view와 full, 잘못된 size
    assert call(server, "GET", f"/api/jobs/{job}/photo/A.CR3?size=view")[2][:2] == b"\xff\xd8"
    assert call(server, "GET", f"/api/jobs/{job}/photo/A.CR3?size=full")[2] == b"FULL"
    assert call(server, "GET", f"/api/jobs/{job}/photo/A.CR3?size=huge")[0] == 400


def test_results_wait_until_done_and_unknown_job(world):
    server, ev, *_ = world
    assert call(server, "GET", "/api/jobs/aaaaaaaaaaaa")[0] == 404
    assert call(server, "GET", "/api/jobs/not-a-job")[0] == 404


def test_scan_input_validation(world, tmp_path, monkeypatch):
    server, ev, *_ = world
    empty = tmp_path / "empty"
    empty.mkdir()
    for body, code in (({"folder": "상대/경로"}, 400), ({"folder": str(tmp_path / "없음")}, 400),
                       ({"folder": str(empty)}, 400), ({"folder": 5}, 400), ({}, 400)):
        assert call(server, "POST", "/api/scan", body)[0] == code, body
    assert call(server, "POST", "/api/scan", body=b"not json")[0] == 400
    assert call(server, "POST", "/api/scan", body=b"[1]")[0] == 400
    monkeypatch.setattr(srv, "MAX_BODY", 100)  # 작은 상한으로 시험 (큰 본문을 실제로 보내지 않는다)
    assert call(server, "POST", "/api/scan", body=b"{" + b" " * 200 + b"}")[0] == 413


def test_scan_failure_is_reported_as_job_error(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "A.CR3").write_bytes(b"x")

    def boom(folder, **kw):
        raise RuntimeError("분석 실패")

    server = make_server(ServerConfig(token=TOKEN, data_dir=tmp_path / "d", scan=boom))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
        info = wait_done(server, job)
        assert info["state"] == "error" and "분석 실패" in info["error"]
        assert call(server, "GET", f"/api/jobs/{job}/results")[0] == 409
    finally:
        server.shutdown()
        server.server_close()


def test_file_names_must_be_in_the_scan_results(world):
    server, ev, *_ = world
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    wait_done(server, job)
    bad_names = ("..%2F..%2Fetc%2Fpasswd", "..%2Fsecret.CR3", "%2Fetc%2Fhosts", "ZZZ.CR3",
                 "A.CR3%00")
    for name in bad_names:
        for kind in ("thumb", "photo"):
            status, *_ = call(server, "GET", f"/api/jobs/{job}/{kind}/{name}")
            assert status == 404, (kind, name)


# ---- 정리 ---------------------------------------------------------------------------------

def test_sort_preview_then_commit_via_api_and_original_untouched(world):
    server, ev, tmp, _ = world
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    wait_done(server, job)
    before = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in ev.iterdir())
    out = tmp / "정리결과"
    status, _, raw = call(server, "POST", f"/api/jobs/{job}/sort",
                          {"out": str(out), "rescue": ["A.CR3", "ZZZ.CR3"]})
    body = jbody(raw)
    assert status == 200 and body["mode"] == "dry-run" and body["result_dir"] is None
    assert body["rescued"] == ["A.CR3"] and body["counts"]["이상 없음"] == 2  # A(살림) + C
    assert not out.exists()
    status, _, raw = call(server, "POST", f"/api/jobs/{job}/sort",
                          {"out": str(out), "rescue": ["A.CR3"], "commit": True})
    body = jbody(raw)
    d = Path(body["result_dir"])
    assert status == 200 and body["mode"] == "commit" and (d / "이상 없음" / "A.CR3").exists()
    assert (d / "직접 확인" / "B.CR3").exists() and not (d / "버릴 것 같은 컷").exists()
    assert sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in ev.iterdir()) == before


def test_sort_refuses_output_inside_the_event_folder(world):
    server, ev, *_ = world
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    wait_done(server, job)
    status, _, raw = call(server, "POST", f"/api/jobs/{job}/sort",
                          {"out": str(ev / "정리"), "commit": True})
    assert status == 400 and "행사 폴더 안" in jbody(raw)["error"] and not (ev / "정리").exists()
    assert call(server, "POST", f"/api/jobs/{job}/sort", {"out": "상대"})[0] == 400
    assert call(server, "POST", f"/api/jobs/{job}/sort", {"rescue": "A.CR3"})[0] == 400


# ---- 작은 함수들, CLI ----------------------------------------------------------------------

def test_unquote_and_split_target():
    assert unquote("%ED%96%89%EC%82%AC.CR3") == "행사.CR3" and unquote("a%2Fb") == "a/b"
    assert unquote("%zz") == "%zz"
    path, params = split_target("/api/x/%EC%82%AC%EC%A7%84?size=full&t=ab%20c&flag")
    assert path == "/api/x/사진" and params == {"size": "full", "t": "ab c", "flag": ""}


def test_cli_serve_announces_url_and_token(monkeypatch, capsys, tmp_path):
    from bcut.cli import main
    seen = {}

    def fake_serve(data_dir, port=0, token=None, announce=None):
        seen.update(data_dir=data_dir, port=port, token=token)
        announce("http://127.0.0.1:5555", token or "generated")

    monkeypatch.setattr(srv, "serve", fake_serve)
    monkeypatch.setenv("BCUT_TOKEN", "x" * 20)
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    line = json.loads(capsys.readouterr().out.strip())
    assert line == {"url": "http://127.0.0.1:5555", "token": "x" * 20}
    assert seen["port"] == 0 and seen["data_dir"] == tmp_path


def test_cli_serve_reports_start_failure(monkeypatch, capsys, tmp_path):
    from bcut.cli import main

    def boom(*a, **k):
        raise OSError("포트 사용 중")

    monkeypatch.setattr(srv, "serve", boom)
    assert main(["serve", "--data-dir", str(tmp_path)]) == 1
    assert "서버를 시작할 수 없다" in capsys.readouterr().err


# ---- 화면 파일, 폴더 선택, Finder 열기 (S3) -----------------------------------------------

def test_index_gets_the_token_and_static_files_need_it(world):
    server, *_ = world
    status, headers, raw = call(server, "GET", "/")
    html = raw.decode("utf-8")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert TOKEN in html and "__TOKEN__" not in html
    for path, ctype in (("/app.js", "javascript"), ("/logic.js", "javascript"), ("/review_logic.js", "javascript"),
                        ("/review.js", "javascript"), ("/sort_view.js", "javascript"),
                        ("/migrate.js", "javascript"), ("/style.css", "css")):
        assert call(server, "GET", path, token=False)[0] == 401  # 화면 파일도 토큰이 필요하다
        status, headers, raw = call(server, "GET", f"{path}?t={TOKEN}", token=False)
        assert status == 200 and ctype in headers["Content-Type"] and len(raw) > 100
    assert call(server, "GET", "/../server.py")[0] == 404 and call(server, "GET", "/web/app.js")[0] == 404


def test_web_files_follow_the_security_rules():
    web = Path(srv.__file__).parent / "web"
    index = (web / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in index and "onclick" not in index  # 인라인 스크립트 없음 (CSP)
    for f in ("index.html", "app.js", "logic.js", "review_logic.js", "review.js", "sort_view.js", "migrate.js",
              "style.css"):
        text = (web / f).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f  # 외부 주소 없음
        assert "innerHTML" not in text and "eval(" not in text and "document.write" not in text, f
    assert "fetch(" in (web / "app.js").read_text(encoding="utf-8")


def test_screen_files_avoid_retired_and_hard_words():
    web = Path(srv.__file__).parent / "web"
    for f in ("index.html", "app.js", "review.js", "review_logic.js", "sort_view.js", "migrate.js"):
        text = (web / f).read_text(encoding="utf-8")
        for word in ("남기기", "삭제", "B컷 후보"):  # 옛 용어와 어려운 말 (IA 용어 규칙, spec SC-08)
            assert word not in text, (f, word)


def test_pyproject_packages_the_web_files():
    toml = (Path(srv.__file__).resolve().parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"bcut.ui" = ["web/*"]' in toml


def test_choose_folder_uses_the_injected_chooser_and_handles_cancel(tmp_path):
    answers = iter(["/Users/x/행사", None])
    cfg = ServerConfig(token=TOKEN, data_dir=tmp_path, choose_folder=lambda: next(answers))
    server = make_server(cfg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert jbody(call(server, "POST", "/api/choose-folder", {})[2]) == {"folder": "/Users/x/행사"}
        assert jbody(call(server, "POST", "/api/choose-folder", {})[2]) == {"folder": None}
        assert call(server, "POST", "/api/choose-folder", {}, token=False)[0] == 401
    finally:
        server.shutdown()
        server.server_close()


def test_choose_folder_failure_is_reported(tmp_path):
    def boom():
        raise RuntimeError("x")

    server = make_server(ServerConfig(token=TOKEN, data_dir=tmp_path, choose_folder=boom))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert call(server, "POST", "/api/choose-folder", {})[0] == 500
    finally:
        server.shutdown()
        server.server_close()


def test_reveal_only_opens_result_folders_made_by_this_server(world, tmp_path):
    server, ev, tmp, _ = world
    opened = []
    server.app_state.cfg.reveal = lambda p: opened.append(str(p))
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    wait_done(server, job)
    assert call(server, "POST", "/api/reveal", {"path": "/etc"})[0] == 403
    assert call(server, "POST", "/api/reveal", {"path": str(ev)})[0] == 403
    assert call(server, "POST", "/api/reveal", {"path": 5})[0] == 403
    body = jbody(call(server, "POST", f"/api/jobs/{job}/sort",
                      {"out": str(tmp / "r"), "commit": True})[2])
    assert call(server, "POST", "/api/reveal", {"path": body["result_dir"]})[0] == 200
    assert opened == [body["result_dir"]]
    # 미리보기만 한 폴더는 열 수 없다
    prev = jbody(call(server, "POST", f"/api/jobs/{job}/sort", {"out": str(tmp / "r2")})[2])
    assert prev["result_dir"] is None and prev["out_root"] == str(tmp / "r2")


def test_job_info_has_folder_and_sort_without_out_reports_default(world):
    server, ev, tmp, _ = world
    job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
    info = wait_done(server, job)
    assert info["folder"] == str(ev)
    body = jbody(call(server, "POST", f"/api/jobs/{job}/sort", {})[2])
    assert body["out_root"] == str(tmp / "data" / "jobs" / job / "정리") and body["mode"] == "dry-run"


def test_scan_accepts_a_file_path_and_uses_its_folder(world):
    server, ev, *_ = world
    status, _, raw = call(server, "POST", "/api/scan", {"folder": str(ev / "A.CR3")})
    assert status == 202
    job = jbody(raw)["job"]
    assert wait_done(server, job)["folder"] == str(ev)


# ---- 세로 사진 회전 --------------------------------------------------------------------------

def test_rotate_functions_stand_portrait_photos_upright():
    from PIL import Image
    wide = Image.new("RGB", (8, 4), (1, 2, 3))
    assert srv.rotate_image(wide, 6).size == (4, 8) and srv.rotate_image(wide, 5).size == (4, 8)
    assert srv.rotate_image(wide, 3).size == (8, 4) and srv.rotate_image(wide, 0).size == (8, 4)
    buf = io.BytesIO()
    wide.save(buf, "JPEG")
    data = buf.getvalue()
    assert srv.rotate_jpeg(data, 0) is data  # 돌릴 필요가 없으면 그대로
    with Image.open(io.BytesIO(srv.rotate_jpeg(data, 6))) as im:
        assert im.size == (4, 8)


def test_thumbnail_is_rotated_by_orientation_and_cached(tmp_path):
    from PIL import Image
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "A.CR3").write_bytes(b"x" * 100)
    asked = []

    def fake_scan(folder, progress=None, **kw):
        buf = io.BytesIO()
        Image.new("RGB", (30, 20), (9, 9, 9)).save(buf, "JPEG")
        return [PhotoResult(file="A.CR3", status="candidate", score=0.1, note=None, face_count=1,
                            faces_considered=1, eye_width_frac=0.01, thumbnail=buf.getvalue())]

    def orient(p):
        asked.append(p.name)
        return 6

    server = make_server(ServerConfig(token=TOKEN, data_dir=tmp_path / "d", scan=fake_scan,
                                      orientation=orient))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        job = jbody(call(server, "POST", "/api/scan", {"folder": str(ev)})[2])["job"]
        wait_done(server, job)
        for _ in range(2):
            status, _, raw = call(server, "GET", f"/api/jobs/{job}/thumb/A.CR3")
            with Image.open(io.BytesIO(raw)) as im:
                assert status == 200 and im.size == (20, 30)  # 가로 30x20이 세로 20x30으로
        assert asked == ["A.CR3"]  # 회전 정보는 한 번만 읽는다
    finally:
        server.shutdown()
        server.server_close()
