import csv
from dataclasses import replace
from pathlib import Path

import pytest

from bcut.apply import (
    ApplyError,
    RatioLimits,
    ReportStats,
    keywords_to_add,
    needed_keywords,
    ratio_warnings,
    read_plan,
    read_report,
    run_apply,
    verify,
)
from bcut.bridge.backup import FILENAME, load_backup
from bcut.bridge.capture_one import VariantInfo
from bcut.cli import main


def vi(folder, name, rating=0, tag=0, kws=(), cid="1", vid=None):
    return VariantInfo(path=str(folder / name), name=name, rating=rating, color_tag=tag,
                       keywords=tuple(kws), collection_id=cid, variant_id=vid or name)


class FakeBridge:
    """Capture One 대역. 키워드를 붙이면 변형의 키워드가 바뀐다. 별점·태그는 건드리지 않는다."""

    catalog_name = "bcut-test"

    def __init__(self, variants, catalog_keywords, tamper_rating=False):
        self.variants = {v.variant_id: v for v in variants}
        self.catalog_keywords = list(catalog_keywords)
        self.calls = []
        self.tamper_rating = tamper_rating

    def list_variants(self):
        return list(self.variants.values())

    def keywords(self):
        return list(self.catalog_keywords)

    def backup_catalog(self, location):
        self.calls.append(("backup_catalog", str(location)))

    def apply_keyword(self, keyword, refs):
        self.calls.append(("apply_keyword", keyword, [v for _, v in refs]))
        for _, vid in refs:
            v = self.variants[vid]
            if keyword not in v.keywords:
                self.variants[vid] = replace(
                    v, keywords=(*v.keywords, keyword),
                    rating=v.rating + 1 if self.tamper_rating else v.rating)
        return len(refs)

    def strip_keyword(self, keyword, refs):
        n = 0
        for _, vid in refs:
            v = self.variants[vid]
            if keyword in v.keywords:
                self.variants[vid] = replace(
                    v, keywords=tuple(k for k in v.keywords if k != keyword))
                n += 1
        return n


def write_report(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "status", "reason"])
        w.writerows(rows)


ALL_KW = ["bcut-candidate", "bcut-review", "bcut-eyes_closed", "bcut-exposure"]


@pytest.fixture
def world(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    report = out / "bcut-report.csv"
    write_report(report, [
        ["A.CR3", "candidate", "eyes_closed"],
        ["B.CR3", "review", "exposure;eyes_closed"],
        ["C.CR3", "normal", ""],
        ["D.CR3", "review", ""],
    ])
    variants = [vi(ev, "A.CR3", 3, 1, ["mine"]), vi(ev, "B.CR3"), vi(ev, "C.CR3", 5),
                vi(ev, "D.CR3")]
    return ev, out, report, variants


# ---- 계획 -----------------------------------------------------------------------------

def test_read_plan_only_candidate_and_review_with_tier_and_reason_keywords(world):
    _, _, report, _ = world
    plan = read_plan(report)
    assert plan == {
        "A.CR3": ["bcut-candidate", "bcut-eyes_closed"],
        "B.CR3": ["bcut-review", "bcut-exposure", "bcut-eyes_closed"],
        "D.CR3": ["bcut-review"],
    }
    assert needed_keywords(plan) == ["bcut-candidate", "bcut-exposure", "bcut-eyes_closed",
                                     "bcut-review"]
    assert read_plan(report, "x-")["D.CR3"] == ["x-review"]


def test_read_plan_rejects_bad_report(tmp_path):
    bad = tmp_path / "r.csv"
    bad.write_text("name,tag\na,b\n", encoding="utf-8")
    with pytest.raises(ApplyError):
        read_plan(bad)
    with pytest.raises(ApplyError):
        read_plan(tmp_path / "nope.csv")


def test_keywords_to_add_skips_already_present():
    m = {"A.CR3": vi(Path("/e"), "A.CR3", kws=["bcut-review"])}
    plan = {"A.CR3": ["bcut-review", "bcut-blur"], "Z.CR3": ["bcut-review"]}
    assert keywords_to_add(plan, m) == {"A.CR3": ["bcut-blur"]}


# ---- T2.4a 키워드 준비 확인 ------------------------------------------------------------

def test_missing_keywords_abort_and_change_nothing(world):
    ev, out, report, variants = world
    b = FakeBridge(variants, ["bcut-candidate", "bcut-review"])  # 사유 키워드가 없다
    res = run_apply(b, read_plan(report), ev, out, commit=True)
    assert res.aborted and "bcut-eyes_closed" in res.aborted and "capture-one-setup" in res.aborted
    assert res.missing_keywords == ["bcut-exposure", "bcut-eyes_closed"]
    assert b.calls == [] and not (out / FILENAME).exists()  # 카탈로그도 파일도 그대로


# ---- dry-run 기본값 --------------------------------------------------------------------

def test_dry_run_reports_but_writes_nothing(world):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    res = run_apply(b, read_plan(report), ev, out)  # commit 기본값 False
    assert res.mode == "dry-run" and res.ok and res.applied_files == 0
    assert res.keyword_counts == {"bcut-candidate": 1, "bcut-exposure": 1,
                                  "bcut-eyes_closed": 2, "bcut-review": 2}
    assert b.calls == [] and not (out / FILENAME).exists()
    assert all(v.keywords == () or v.keywords == ("mine",) for v in b.variants.values())


# ---- commit ----------------------------------------------------------------------------

def test_commit_applies_keywords_only_and_saves_before_and_after(world, tmp_path):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    res = run_apply(b, read_plan(report), ev, out, commit=True, backups_dir=tmp_path / "cb",
                    now=lambda: "T", tool_version="9", config_version="c")
    assert res.ok and res.applied_files == 3 and res.backup_path == out / FILENAME
    assert b.calls[0] == ("backup_catalog", str(tmp_path / "cb"))  # 카탈로그 백업이 먼저
    a = b.variants["A.CR3"]
    assert a.keywords == ("mine", "bcut-candidate", "bcut-eyes_closed")  # 기존 키워드 보존
    assert (a.rating, a.color_tag) == (3, 1)  # 별점·태그 그대로
    assert b.variants["C.CR3"].keywords == () and b.variants["C.CR3"].rating == 5  # normal 불변
    bk = load_backup(out / FILENAME)
    e = bk.entry("A.CR3")
    assert (e.before.rating, e.before.color_tag, e.before.keywords) == (3, 1, ["mine"])
    assert e.after.keywords == ["mine", "bcut-candidate", "bcut-eyes_closed"]
    assert bk.entry("C.CR3") is None


def test_apply_twice_is_idempotent_and_keeps_original_before(world):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    plan = read_plan(report)
    run_apply(b, plan, ev, out, commit=True)
    calls_after_first = len(b.calls)
    res = run_apply(b, plan, ev, out, commit=True)
    assert res.ok and res.applied_files == 0 and res.already == 3 and res.keyword_counts == {}
    assert len(b.calls) == calls_after_first  # 두 번째는 붙이는 호출이 없다
    e = load_backup(out / FILENAME).entry("A.CR3")
    assert e.before.keywords == ["mine"]  # 처음의 직전 값이 유지된다 (도구 키워드가 섞이지 않음)


def test_second_run_with_new_cut_keeps_old_before_and_adds_new(world):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    run_apply(b, {"A.CR3": ["bcut-candidate", "bcut-eyes_closed"]}, ev, out, commit=True)
    run_apply(b, read_plan(report), ev, out, commit=True)
    bk = load_backup(out / FILENAME)
    assert bk.entry("A.CR3").before.keywords == ["mine"]
    assert bk.entry("B.CR3").before.keywords == [] and bk.entry("D.CR3") is not None


def test_backup_failure_aborts_before_any_change(world, monkeypatch):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    import bcut.apply as ap

    def boom(*a, **k):
        raise ap.BackupError("disk full")

    monkeypatch.setattr(ap, "save_backup", boom)
    res = run_apply(b, read_plan(report), ev, out, commit=True)
    assert res.aborted and "백업" in res.aborted
    assert not any(c[0] == "apply_keyword" for c in b.calls)


def test_catalog_backup_failure_aborts_before_any_change(world, tmp_path):
    ev, out, report, variants = world

    class Failing(FakeBridge):
        def backup_catalog(self, location):
            raise RuntimeError("Capture One 응답 없음")

    b = Failing(variants, ALL_KW)
    res = run_apply(b, read_plan(report), ev, out, commit=True, backups_dir=tmp_path / "cb")
    assert res.aborted and not b.calls


def test_unmatched_cuts_abort_unless_allow_partial(world):
    ev, out, report, variants = world
    b = FakeBridge([v for v in variants if v.name != "D.CR3"], ALL_KW)
    res = run_apply(b, read_plan(report), ev, out, commit=True)
    assert res.aborted and "못 찾은 컷 1장" in res.aborted and b.calls == []
    res = run_apply(b, read_plan(report), ev, out, commit=True, allow_partial=True)
    assert res.ok and res.applied_files == 2 and res.match.missing == ["D.CR3"]


def test_ambiguous_names_are_never_applied(world):
    ev, out, report, variants = world
    other = vi(Path("/elsewhere"), "B.CR3", vid="B2")
    # 행사 폴더에 B가 없고 다른 폴더에 둘이 있는 경우 -> 모호
    vs = [v for v in variants if v.name != "B.CR3"] + [vi(Path("/x"), "B.CR3", vid="B1"), other]
    b = FakeBridge(vs, ALL_KW)
    res = run_apply(b, read_plan(report), ev, out, commit=True, allow_partial=True)
    assert "B.CR3" in res.match.ambiguous
    assert all("B1" not in c[2] and "B2" not in c[2] for c in b.calls if c[0] == "apply_keyword")


def test_verification_flags_changed_rating(world):
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW, tamper_rating=True)  # 대역이 별점을 몰래 바꾼다
    res = run_apply(b, read_plan(report), ev, out, commit=True)
    assert not res.ok and any("별점·컬러 태그가 바뀌었다" in v for v in res.violations)


def test_verify_detects_lost_and_missing_keywords():
    pre = {"A.CR3": vi(Path("/e"), "A.CR3", 3, 1, ["mine"])}
    expected = {"A.CR3": ["bcut-candidate"]}
    good = {"A.CR3": vi(Path("/e"), "A.CR3", 3, 1, ["mine", "bcut-candidate"])}
    assert verify(pre, expected, good) == []
    broken = {"A.CR3": vi(Path("/e"), "A.CR3", 3, 1, [])}
    bad = verify(pre, expected, broken)
    assert any("기존 키워드가 사라졌다" in x for x in bad)
    assert any("붙이려던 키워드가 없다" in x for x in bad)
    assert any("읽지 못했다" in x for x in verify(pre, expected, {}))


def test_verify_compares_with_this_runs_state_not_the_first_backup(world):
    # 두 번째 실행 사이에 사용자가 별점을 바꿨다: 도구 탓으로 오해하면 안 된다
    ev, out, report, variants = world
    b = FakeBridge(variants, ALL_KW)
    plan = read_plan(report)
    run_apply(b, {"A.CR3": plan["A.CR3"]}, ev, out, commit=True)
    b.variants["B.CR3"] = replace(b.variants["B.CR3"], rating=4)  # 사용자가 바꿈
    res = run_apply(b, plan, ev, out, commit=True)
    assert res.ok and res.violations == []
    assert b.variants["B.CR3"].rating == 4


def test_empty_plan_aborts(world):
    ev, out, _, variants = world
    res = run_apply(FakeBridge(variants, ALL_KW), {}, ev, out, commit=True)
    assert res.aborted


# ---- CLI -------------------------------------------------------------------------------

def test_cli_apply_rejects_out_inside_event_folder(world, capsys):
    ev, out, report, _ = world
    assert main(["apply", "--folder", str(ev), "--catalog", "bcut-test",
                 "--out", str(ev / "o")]) == 2
    assert "행사 폴더 안" in capsys.readouterr().err


def test_cli_apply_missing_report_fails(world, capsys):
    ev, out, report, _ = world
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--report", str(out / "nope.csv")])
    assert code == 2 and "리포트" in capsys.readouterr().err


def test_cli_apply_dry_run_with_fake_bridge(world, monkeypatch, capsys):
    ev, out, report, variants = world
    import bcut.bridge.capture_one as co
    fake = FakeBridge(variants, ALL_KW)
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and "dry-run" in text and "--commit" in text and fake.calls == []
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--commit", "--ignore-ratio-warning"])
    assert code == 0 and (out / FILENAME).exists() and "백업" in capsys.readouterr().out


# ---- T2.5 비정상 비율 경고 ---------------------------------------------------------------

def test_read_report_stats(world):
    _, _, report, _ = world
    plan, stats = read_report(report)
    assert stats.total == 4 and stats.by_status == {"candidate": 1, "review": 2, "normal": 1}
    assert stats.by_reason == {"eyes_closed": 2, "exposure": 1}
    assert stats.candidate_ratio == 0.25 and stats.raised_ratio == 0.75 and len(plan) == 3


def test_ratio_warnings_thresholds():
    ok = ReportStats(100, {"candidate": 8, "review": 7, "normal": 85}, {})
    assert ratio_warnings(ok, RatioLimits()) == []  # 실제 EVENT_A 정도의 비율은 경고 없음
    high_c = ReportStats(100, {"candidate": 21, "review": 0, "normal": 79}, {})
    assert len(ratio_warnings(high_c, RatioLimits())) == 1
    high_both = ReportStats(100, {"candidate": 30, "review": 20, "normal": 50}, {})
    assert len(ratio_warnings(high_both, RatioLimits())) == 2
    assert ratio_warnings(ReportStats(0, {}, {}), RatioLimits()) == []
    with pytest.raises(ValueError):
        RatioLimits(0, 0.4)


def test_abnormal_ratio_blocks_commit_but_not_dry_run(world):
    ev, out, report, variants = world
    plan, stats = read_report(report)
    b = FakeBridge(variants, ALL_KW)
    dry = run_apply(b, plan, ev, out, stats=stats)
    assert dry.ok and dry.warnings and b.calls == []  # dry-run은 경고만
    res = run_apply(b, plan, ev, out, commit=True, stats=stats)
    assert res.aborted and "비정상 비율" in res.aborted and "--ignore-ratio-warning" in res.aborted
    assert b.calls == [] and not (out / FILENAME).exists()  # 아무것도 바뀌지 않는다


def test_ignore_ratio_warning_allows_commit(world):
    ev, out, report, variants = world
    plan, stats = read_report(report)
    b = FakeBridge(variants, ALL_KW)
    res = run_apply(b, plan, ev, out, commit=True, stats=stats, ignore_ratio_warning=True)
    assert res.ok and res.applied_files == 3 and res.warnings


def test_custom_limits_can_loosen_check(world):
    ev, out, report, variants = world
    plan, stats = read_report(report)
    res = run_apply(FakeBridge(variants, ALL_KW), plan, ev, out, commit=True, stats=stats,
                    limits=RatioLimits(0.5, 0.9))
    assert res.ok and not res.warnings


def test_cli_ratio_flags_and_summary(world, monkeypatch, capsys):
    ev, out, report, variants = world
    import bcut.bridge.capture_one as co
    fake = FakeBridge(variants, ALL_KW)
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    base = ["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out)]
    assert main([*base, "--commit"]) == 1  # 경고 때문에 중단
    cap = capsys.readouterr()
    assert "경고" in cap.err and "중단" in cap.err and fake.calls == []
    assert main([*base, "--max-candidate-ratio", "0.5", "--max-raised-ratio", "0.9"]) == 0
    text = capsys.readouterr().out
    assert "사유별(후보·확인)" in text and "eyes_closed 2" in text and "반영 대상 3장" in text
    assert main([*base, "--max-candidate-ratio", "0"]) == 2  # 잘못된 한도


# ---- T2.9 대량 처리와 재개, T2.10 오류 --------------------------------------------------

from bcut.bridge.osascript import AppleScriptError, AppleScriptTimeout, explain_error  # noqa: E402


class FlakyBridge(FakeBridge):
    """n번째 apply_keyword 호출에서 한 번 실패한다 (Capture One이 멈춘 상황)."""

    def __init__(self, *a, fail_on_call=2, error=None, **k):
        super().__init__(*a, **k)
        self.fail_on_call = fail_on_call
        self.error = error or AppleScriptTimeout("60초 안에 끝나지 않았다")
        self.apply_calls = 0
        self.broken = True

    def apply_keyword(self, keyword, refs):
        self.apply_calls += 1
        if self.broken and self.apply_calls == self.fail_on_call:
            self.broken = False
            raise self.error
        return super().apply_keyword(keyword, refs)


def many(ev, n):
    vs = [vi(ev, f"P{i:04d}.CR3") for i in range(n)]
    plan = {v.name: ["bcut-review", "bcut-eyes_closed"] for v in vs}
    return vs, plan


def test_apply_is_split_into_chunks_and_reports_progress(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    vs, plan = many(ev, 25)
    b = FakeBridge(vs, ALL_KW)
    seen = []
    res = run_apply(b, plan, ev, tmp_path / "out", commit=True, chunk_size=10,
                    progress=lambda k, d, t: seen.append((k, d, t)))
    assert res.ok and res.applied_files == 25
    sizes = [len(c[2]) for c in b.calls if c[0] == "apply_keyword"]
    assert sizes == [10, 10, 5, 10, 10, 5]  # 키워드 2개 x 청크 3개
    assert seen[:3] == [("bcut-eyes_closed", 10, 25), ("bcut-eyes_closed", 20, 25),
                        ("bcut-eyes_closed", 25, 25)]


def test_invalid_chunk_size_is_refused(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    vs, plan = many(ev, 3)
    with pytest.raises(ValueError):
        run_apply(FakeBridge(vs, ALL_KW), plan, ev, tmp_path / "out", commit=True, chunk_size=0)


def test_interrupted_apply_reports_partial_state_and_rerun_resumes(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    out = tmp_path / "out"
    vs, plan = many(ev, 25)
    b = FlakyBridge(vs, ALL_KW, fail_on_call=2)  # 두 번째 청크에서 멈춘다
    res = run_apply(b, plan, ev, out, commit=True, chunk_size=10)
    assert res.aborted and "다시 실행" in res.aborted and "응답하지 않았다" in res.aborted
    done = sum("bcut-eyes_closed" in v.keywords for v in b.variants.values())
    assert done == 10  # 첫 청크까지는 붙었다
    # 백업은 멈춘 뒤에도 남고, 직후 값이 기록되어 있다
    bk = load_backup(out / FILENAME)
    assert len(bk.entries) == 25 and bk.entry("P0000.CR3").after is not None
    # 같은 명령을 다시 실행하면 이어서 한다: 이미 붙은 것은 건너뛴다
    res2 = run_apply(b, plan, ev, out, commit=True, chunk_size=10)
    assert res2.ok and res2.applied_files == 25  # 반만 붙은 상태에서 이어서 마저 붙인다
    assert all("bcut-eyes_closed" in v.keywords and "bcut-review" in v.keywords
               for v in b.variants.values())
    assert all(v.keywords.count("bcut-eyes_closed") == 1 for v in b.variants.values())  # 중복 없음
    e = load_backup(out / FILENAME).entry("P0000.CR3")
    assert e.before.keywords == []  # 처음의 직전 값이 유지된다


def test_interrupted_apply_then_rollback_restores_everything(tmp_path):
    from bcut.rollback import run_rollback
    ev = tmp_path / "ev"
    ev.mkdir()
    out = tmp_path / "out"
    vs, plan = many(ev, 12)
    b = FlakyBridge(vs, ALL_KW, fail_on_call=3)
    run_apply(b, plan, ev, out, commit=True, chunk_size=5)
    assert any(v.keywords for v in b.variants.values())  # 일부만 반영된 상태
    res = run_rollback(b, out / FILENAME, commit=True)
    assert res.ok and all(v.keywords == () for v in b.variants.values())


def test_non_timeout_error_during_apply_is_also_handled(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    vs, plan = many(ev, 5)
    b = FlakyBridge(vs, ALL_KW, fail_on_call=1, error=AppleScriptError("x (-600)", 1))
    res = run_apply(b, plan, ev, tmp_path / "out", commit=True)
    assert res.aborted and "실행 중이 아니다" in res.aborted


@pytest.mark.parametrize("exc,needle", [
    (AppleScriptTimeout("60초 안에 끝나지 않았다"), "제때 응답"),
    (AppleScriptError("execution error: Not authorized to send Apple events (-1743)"), "권한"),
    (AppleScriptError("Application isn't running. (-600)"), "실행 중이 아니다"),
    (AppleScriptError("execution error: wrong catalog: 실제 (expected bcut-test) (-2700)"),
     "지정한 것과 다르다"),
    (AppleScriptError("missing keyword: bcut-review"), "전용 키워드가 없다"),
    (AppleScriptError("낯선 오류"), "낯선 오류"),
])
def test_explain_error_gives_actionable_message(exc, needle):
    assert needle in explain_error(exc)


def test_cli_apply_explains_capture_one_errors(world, monkeypatch, capsys):
    ev, out, report, variants = world
    import bcut.bridge.capture_one as co

    class Down:
        catalog_name = "bcut-test"

        def list_variants(self):
            raise AppleScriptError("Application isn't running. (-600)")

    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: Down())
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--max-candidate-ratio", "1", "--max-raised-ratio", "1"])
    assert code == 1 and "Capture One이 실행 중이 아니다" in capsys.readouterr().err


def test_cli_apply_chunk_size_and_progress(world, monkeypatch, capsys):
    ev, out, report, variants = world
    import bcut.bridge.capture_one as co
    fake = FakeBridge(variants, ALL_KW)
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    code = main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--commit", "--ignore-ratio-warning", "--chunk-size", "1"])
    text = capsys.readouterr().out
    assert code == 0 and "bcut-eyes_closed: 1/2" in text and "bcut-eyes_closed: 2/2" in text
    assert main(["apply", "--folder", str(ev), "--catalog", "bcut-test", "--out", str(out),
                 "--chunk-size", "0", "--commit", "--ignore-ratio-warning"]) == 2
