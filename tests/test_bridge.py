import subprocess

import pytest

from bcut.bridge import capture_one
from bcut.bridge.capture_one import (
    CaptureOneBridge,
    CatalogError,
    VariantInfo,
    parse_variants,
)
from bcut.bridge.osascript import AppleScriptError, AppleScriptTimeout, run_script


def cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ---- run_script ----------------------------------------------------------------------

def test_run_script_passes_args_as_argv_not_in_source():
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return cp(stdout="ok\n")

    tricky = 'a"b\\c; do shell script "x"'
    assert run_script("on run argv\nreturn 1\nend run", [tricky, 2], runner=runner) == "ok"
    assert seen["cmd"][:2] == ["osascript", "-e"]
    assert seen["cmd"][3:] == [tricky, "2"]  # 인자는 따로 넘어가고 스크립트 글자는 그대로
    assert tricky not in seen["cmd"][2]
    assert seen["kw"]["timeout"] == 60.0 and seen["kw"]["capture_output"] is True


def test_run_script_error_includes_message_and_code():
    runner = lambda cmd, **kw: cp(1, stderr="execution error: boom (-1728)\n")  # noqa: E731
    with pytest.raises(AppleScriptError, match="boom") as exc:
        run_script("x", runner=runner)
    assert exc.value.returncode == 1 and not isinstance(exc.value, AppleScriptTimeout)


def test_run_script_timeout_is_its_own_error():
    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    with pytest.raises(AppleScriptTimeout):
        run_script("x", timeout=3, runner=runner)


def test_run_script_without_osascript():
    def runner(cmd, **kw):
        raise FileNotFoundError

    with pytest.raises(AppleScriptError, match="osascript"):
        run_script("x", runner=runner)


def test_run_script_error_without_stderr_still_explains():
    with pytest.raises(AppleScriptError, match="종료 코드 5"):
        run_script("x", runner=lambda cmd, **kw: cp(5))


# ---- parse_variants ------------------------------------------------------------------

LINE = "/data/ev/PHA_7983.CR3\tPHA_7983\t3\t1\tbcut-eyes_closed|other|\n"


def test_parse_variants_fields_and_tool_keywords():
    [v] = parse_variants(LINE)
    kws = ("bcut-eyes_closed", "other")
    assert v == VariantInfo("/data/ev/PHA_7983.CR3", "PHA_7983", 3, 1, kws)
    assert v.tool_keywords == ("bcut-eyes_closed",)


def test_parse_variants_ignores_ghost_empty_and_duplicates():
    text = ("/a.CR3\ta\t0\t0\tmissing value|\n"
            "/a.CR3\ta\t5\t5\t\n"            # 같은 경로가 다른 컬렉션에 또 나옴 -> 첫 값만
            "\n"
            "/b.CR3\tb\t0\t0\t\n")
    out = parse_variants(text)
    assert [v.path for v in out] == ["/a.CR3", "/b.CR3"]
    assert out[0].keywords == () and out[0].rating == 0


@pytest.mark.parametrize("bad", ["only\ttwo\n", "/a\ta\tx\t0\t\n"])
def test_parse_variants_rejects_garbage(bad):
    with pytest.raises(CatalogError):
        parse_variants(bad)


# ---- CaptureOneBridge ----------------------------------------------------------------

def test_bridge_sends_catalog_name_as_first_argument():
    calls = []

    def run(script, args, **kw):
        calls.append((script, list(args)))
        return "bcut-test"

    b = CaptureOneBridge("bcut-test", run=run)
    assert b.ping() == "bcut-test"
    assert calls == [(capture_one.PING_SCRIPT, ["bcut-test"])]


def test_bridge_list_and_keywords_parse_results():
    outputs = iter([LINE, "bcut-eyes_closed\nmissing value\nother\n"])
    b = CaptureOneBridge("c", run=lambda s, a, **k: next(outputs))
    assert b.list_variants()[0].name == "PHA_7983"
    assert b.keywords() == ["bcut-eyes_closed", "other"]


def test_document_kind_and_session_reading_use_their_own_scripts():
    calls = []

    def run(script, args, **kw):
        calls.append(script)
        return "session" if script == capture_one.KIND_SCRIPT else LINE

    b = CaptureOneBridge("세션이름", run=run)
    assert b.document_kind() == "session"
    b.list_variants()  # 기본은 카탈로그 방식
    b.session = True
    b.list_variants()
    assert calls == [capture_one.KIND_SCRIPT, capture_one.LIST_SCRIPT,
                     capture_one.SESSION_LIST_SCRIPT]


def test_style_scripts_check_the_catalog_and_set_only_their_own_property():
    for script, prop, other in ((capture_one.SET_RATING_SCRIPT, "rating", "color tag"),
                                (capture_one.SET_COLOR_SCRIPT, "color tag", "rating")):
        assert "wrong catalog" in script and f"set {prop} of v to val" in script
        assert f"set {other}" not in script and "apply keyword" not in script


def test_set_rating_and_color_pass_value_then_refs():
    calls = []
    b = CaptureOneBridge("c", run=lambda s, a, **k: calls.append((s, a)) or "2")
    assert b.set_rating(4, [("1", "a"), ("1", "b")]) == 2
    assert b.set_color_tag(1, [("2", "c")]) == 2
    assert calls[0] == (capture_one.SET_RATING_SCRIPT, ["c", "4", "1|a", "1|b"])
    assert calls[1] == (capture_one.SET_COLOR_SCRIPT, ["c", "1", "2|c"])
    assert b.set_rating(3, []) == 0 and len(calls) == 2  # 비어 있으면 호출하지 않는다


def test_read_scripts_use_the_fast_path_with_safe_fallback():
    for script in (capture_one.LIST_SCRIPT, capture_one.SESSION_LIST_SCRIPT):
        assert "on readFast" in script and "on readSlow" in script
        assert "path of every image of c" in script       # 한꺼번에 읽는 빠른 길
        assert "okFirst" in script and "okLast" in script  # 순서가 어긋났는지 확인
        assert "my readSlow(c)" in script                  # 어긋나면 옛 방식
        assert "set fast to true" in script


def test_bridge_wrong_catalog_error_propagates():
    def run(script, args, **kw):
        raise AppleScriptError("wrong catalog: 실제작업 (expected bcut-test)")

    with pytest.raises(AppleScriptError, match="wrong catalog"):
        CaptureOneBridge("bcut-test", run=run).list_variants()


def test_bridge_rejects_blank_catalog_name():
    with pytest.raises(ValueError):
        CaptureOneBridge("  ")


def test_every_script_checks_the_catalog_name_and_writes_nothing():
    for script in (capture_one.PING_SCRIPT, capture_one.LIST_SCRIPT, capture_one.KEYWORD_SCRIPT,
                   capture_one.KIND_SCRIPT, capture_one.SESSION_LIST_SCRIPT):
        assert "wrong catalog" in script and "item 1 of argv" in script
        for forbidden in ("set rating", "set color tag", "apply keyword", "delete ", "make new"):
            assert forbidden not in script


# ---- 실제 Capture One (시험용 카탈로그만) -----------------------------------------------
# 환경 변수 BCUT_LIVE_CATALOG에 시험용 카탈로그 이름(예: bcut-test)을 주면 실제로 읽는다.

@pytest.mark.skipif(not __import__("os").environ.get("BCUT_LIVE_CATALOG"),
                    reason="BCUT_LIVE_CATALOG 없음 (Capture One 실기 시험)")
def test_live_read_only_against_test_catalog():
    import os
    name = os.environ["BCUT_LIVE_CATALOG"]
    b = CaptureOneBridge(name)
    assert b.ping() == name
    variants = b.list_variants()
    assert variants and all(v.path.endswith(".CR3") for v in variants)
    with pytest.raises(AppleScriptError, match="wrong catalog"):
        CaptureOneBridge(name + "-x").ping()
