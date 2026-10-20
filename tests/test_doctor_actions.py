import json

import pytest

from bcut.bridge.osascript import AppleScriptError
from bcut.cli import main
from bcut.doctor import (
    FAIL,
    OK,
    SKIP,
    WARN,
    Check,
    has_failure,
    run_checks,
)
from bcut.report.action_log import FILENAME, append_action, read_actions

ALL = ["bcut-candidate", "bcut-review", "bcut-eyes_closed", "bcut-exposure", "bcut-blur",
       "bcut-out_of_focus"]


def by_name(checks):
    return {c.name: c for c in checks}


class FakeBridge:
    def __init__(self, opened="bcut-test", keywords=ALL, ping_error=None, kw_error=None):
        self.opened, self._kw = opened, keywords
        self.ping_error, self.kw_error = ping_error, kw_error

    def ping(self):
        if self.ping_error:
            raise self.ping_error
        return self.opened

    def keywords(self):
        if self.kw_error:
            raise self.kw_error
        return list(self._kw)


def run(catalog=None, **kw):
    kw.setdefault("versions", lambda lib: "1.0")
    kw.setdefault("co_version", lambda: "16.7.1.11")
    kw.setdefault("co_running", lambda: True)
    kw.setdefault("python_version", (3, 13))
    return run_checks(catalog, **kw)


# ---- doctor -----------------------------------------------------------------------------

def test_environment_only_all_ok_and_catalog_skipped():
    c = by_name(run())
    assert c["Python"].status == OK and c["bcut"].status == OK
    assert c["numpy"].detail == "1.0" and c["카탈로그 연결"].status == SKIP
    assert not has_failure(run())


def test_old_python_and_missing_library_fail_with_hints():
    checks = run(python_version=(3, 11), versions=lambda lib: None if lib == "rawpy" else "1")
    c = by_name(checks)
    assert c["Python"].status == FAIL and "3.13" in c["Python"].hint
    assert c["rawpy"].status == FAIL and "requirements-lock" in c["rawpy"].hint
    assert has_failure(checks)


def test_capture_one_missing_or_untested_version_is_only_a_warning():
    assert by_name(run(co_version=lambda: None))["Capture One 설치"].status == WARN
    c = by_name(run(co_version=lambda: "16.8.6.1"))["Capture One 버전"]
    assert c.status == WARN and "시험 7개" in c.hint
    assert by_name(run())["Capture One 버전"].status == OK


def test_not_running_does_not_try_to_connect():
    called = []
    checks = run("bcut-test", co_running=lambda: False,
                 bridge_factory=lambda n: called.append(n) or FakeBridge())
    assert by_name(checks)["Capture One 실행"].status == FAIL and called == []
    assert has_failure(checks)


def test_connection_and_keywords_ok():
    c = by_name(run("bcut-test", bridge_factory=lambda n: FakeBridge()))
    assert c["카탈로그 연결"].status == OK and "bcut-test" in c["카탈로그 연결"].detail
    assert c["전용 키워드"].status == OK


def test_missing_keywords_are_listed_as_warning():
    c = by_name(run("bcut-test", bridge_factory=lambda n: FakeBridge(keywords=ALL[:3])))
    assert c["전용 키워드"].status == WARN
    assert "bcut-exposure" in c["전용 키워드"].detail
    assert "capture-one-setup" in c["전용 키워드"].hint


def test_connection_errors_are_explained():
    err = AppleScriptError("execution error: Not authorized to send Apple events (-1743)")
    c = by_name(run("bcut-test", bridge_factory=lambda n: FakeBridge(ping_error=err)))
    assert c["카탈로그 연결"].status == FAIL and "권한" in c["카탈로그 연결"].detail
    wrong = AppleScriptError("execution error: wrong catalog: 다른 (expected bcut-test) (-2700)")
    c = by_name(run("bcut-test", bridge_factory=lambda n: FakeBridge(ping_error=wrong)))
    assert "지정한 것과 다르다" in c["카탈로그 연결"].detail


def test_custom_keyword_prefix():
    kws = [k.replace("bcut-", "x-") for k in ALL]
    c = by_name(run("c", keyword_prefix="x-", bridge_factory=lambda n: FakeBridge(keywords=kws)))
    assert c["전용 키워드"].status == OK


def test_cli_doctor_environment_only_exit_code_and_output(capsys):
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0 and "Python" in out and "실패 0" in out and "카탈로그 연결" in out


def test_check_is_a_plain_value():
    assert Check("a", OK, "x").hint == ""


# ---- 실행 기록 --------------------------------------------------------------------------

def test_append_action_appends_lines_and_reads_back(tmp_path):
    append_action(tmp_path / "o", {"command": "apply", "mode": "dry-run"})
    append_action(tmp_path / "o", {"command": "rollback", "mode": "commit", "한글": "ok"})
    rows = read_actions(tmp_path / "o")
    assert [r["command"] for r in rows] == ["apply", "rollback"] and rows[1]["한글"] == "ok"
    assert len((tmp_path / "o" / FILENAME).read_text(encoding="utf-8").splitlines()) == 2


def test_append_action_never_raises_when_unwritable(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    assert append_action(blocker / "sub", {"a": 1}) is None


def test_read_actions_tolerates_garbage_and_missing(tmp_path):
    assert read_actions(tmp_path / "none") == []
    (tmp_path / FILENAME).write_text('{"a":1}\nnot json\n\n', encoding="utf-8")
    rows = read_actions(tmp_path)
    assert rows[0] == {"a": 1} and "unreadable" in rows[1]


@pytest.fixture
def cli_world(tmp_path, monkeypatch):
    ev = tmp_path / "ev"
    ev.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "bcut-report.csv").write_text(
        "file,status,reason\nA.CR3,review,eyes_closed\nB.CR3,normal,\n", encoding="utf-8")
    from dataclasses import replace

    from bcut.bridge.capture_one import VariantInfo

    class Fake:
        catalog_name = "bcut-test"

        def __init__(self):
            self.v = {"A": VariantInfo(str(ev / "A.CR3"), "A.CR3", 0, 0, (), "1", "A"),
                      "B": VariantInfo(str(ev / "B.CR3"), "B.CR3", 0, 0, (), "1", "B")}

        def list_variants(self):
            return list(self.v.values())

        def keywords(self):
            return ["bcut-review", "bcut-eyes_closed"]

        def backup_catalog(self, loc):
            pass

        def apply_keyword(self, kw, refs):
            for _, vid in refs:
                x = self.v[vid]
                self.v[vid] = replace(x, keywords=(*x.keywords, kw))
            return len(refs)

        def strip_keyword(self, kw, refs):
            for _, vid in refs:
                x = self.v[vid]
                self.v[vid] = replace(x, keywords=tuple(k for k in x.keywords if k != kw))
            return len(refs)

    import bcut.bridge.capture_one as co
    fake = Fake()
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    return ev, out


def test_apply_and_rollback_leave_one_log_line_each(cli_world):
    ev, out = cli_world
    base = ["--folder", str(ev), "--catalog", "bcut-test", "--out", str(out)]
    assert main(["apply", *base, "--max-candidate-ratio", "1", "--max-raised-ratio", "1"]) == 0
    assert main(["apply", *base, "--commit", "--ignore-ratio-warning"]) == 0
    assert main(["rollback", *base, "--commit"]) == 0
    rows = read_actions(out)
    assert [(r["command"], r["mode"]) for r in rows] == [
        ("apply", "dry-run"), ("apply", "commit"), ("rollback", "commit")]
    a = rows[1]
    assert a["catalog"] == "bcut-test" and a["applied_files"] == 1 and a["tool_version"]
    assert a["keywords"] == {"bcut-eyes_closed": 1, "bcut-review": 1} and a["aborted"] is None
    assert rows[2]["stripped_files"] == 1 and rows[2]["violations"] == []
    text = json.dumps(rows, ensure_ascii=False)
    assert "A.CR3" not in text  # 파일 이름은 기록하지 않는다


def test_failed_apply_is_logged_with_the_explained_error(cli_world, monkeypatch):
    ev, out = cli_world
    import bcut.bridge.capture_one as co

    class Down:
        catalog_name = "bcut-test"

        def list_variants(self):
            raise AppleScriptError("Application isn't running. (-600)")

    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: Down())
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--max-candidate-ratio", "1", "--max-raised-ratio", "1"])
    assert code == 1
    [row] = read_actions(out)
    assert row["command"] == "apply" and "실행 중이 아니다" in row["error"]
