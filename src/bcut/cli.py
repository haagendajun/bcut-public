"""명령줄 진입점.

scan, calibrate, apply, albums, rollback을 구현했다. 아직 구현되지 않은 명령은 아무것도 바꾸지 않고
종료 코드 2를 돌려준다.

scan은 **행사 폴더에 아무것도 쓰지 않는다** (읽기 전용). 결과는 --out 폴더에만 쓴다.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from bcut import __version__

NOT_IMPLEMENTED = 2
USAGE_ERROR = 2
DEFAULT_OUT_ROOT = Path("bcut-out")


def _folder(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"폴더를 찾을 수 없다: {value}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bcut",
        description="B컷 후보 사전 필터. 사진은 이 컴퓨터 밖으로 나가지 않고, 삭제하지 않는다.",
    )
    parser.add_argument("--version", action="version", version=f"bcut {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="명령")

    scan = sub.add_parser(
        "scan", help="행사 폴더를 분석해 CSV와 HTML 리포트를 만든다 (읽기 전용)"
    )
    scan.add_argument(
        "--folder", type=_folder, required=True, help="행사 폴더 (사진을 읽기만 한다)"
    )
    scan.add_argument("--out", type=Path,
                      help=f"결과를 쓸 폴더 (기본: {DEFAULT_OUT_ROOT}/<행사 폴더 이름>/). "
                           "행사 폴더 안은 안 된다")
    scan.add_argument(
        "--thumbs", choices=("all", "flagged"), default="all",
        help="썸네일을 넣을 컷: all=전체, flagged=후보·확인·판정 불가만 (파일이 작아진다)",
    )
    scan.add_argument("--config", type=Path,
                      help="설정 파일(TOML): 사유별 등급과 임계값. 없으면 기본값")
    scan.add_argument("--thumb-width", type=int, default=320, help="썸네일 폭(px)")
    scan.add_argument("--workers", type=int, help="동시에 처리할 개수 (기본: 최대 6)")

    calibrate = sub.add_parser("calibrate", help="라벨(A/B)로 임계값을 보정한다")
    calibrate.add_argument("--folder", type=_folder, required=True,
                           help="라벨을 붙인 사진이 있는 행사 폴더 (읽기만 한다)")
    calibrate.add_argument("--labels", type=Path, required=True,
                           help="라벨 CSV (file, label 열. label은 B, OK, OK_EXPR)")
    calibrate.add_argument("--out", type=Path,
                           help="설정 파일 경로 (기본: bcut-out/<행사 폴더 이름>/bcut-config.toml)")
    calibrate.add_argument("--review-recall", type=float, default=0.95,
                           help="확인 경계에 넣을 B의 비율 (기본 0.95)")
    calibrate.add_argument("--workers", type=int, help="동시에 처리할 개수")

    apply = sub.add_parser(
        "apply", help="후보·확인 컷에 전용 키워드를 붙인다 (기본은 dry-run: 아무것도 바꾸지 않는다)"
    )
    apply.add_argument("--folder", type=_folder, required=True, help="행사 폴더 (읽기만 한다)")
    apply.add_argument("--catalog", required=True,
                       help="열려 있어야 하는 Capture One 카탈로그 이름 (다르면 멈춘다)")
    apply.add_argument("--report", type=Path,
                       help="scan이 만든 bcut-report.csv (기본: bcut-out/<행사 폴더 이름>/)")
    apply.add_argument("--out", type=Path,
                       help="백업 등을 쓸 폴더 (기본: scan 결과 폴더). 행사 폴더 안은 안 된다")
    apply.add_argument("--config", type=Path, help="설정 파일(TOML)")
    apply.add_argument("--commit", action="store_true",
                       help="실제로 반영한다. 없으면 dry-run(미리보기)만 한다")
    apply.add_argument("--allow-partial", action="store_true",
                       help="카탈로그에서 못 찾았거나 모호한 컷은 빼고 나머지만 반영한다")
    apply.add_argument("--max-candidate-ratio", type=float, default=0.20,
                       help="후보 비율 한도 (넘으면 --commit이 멈춘다, 기본 0.20)")
    apply.add_argument("--max-raised-ratio", type=float, default=0.40,
                       help="후보+확인 비율 한도 (넘으면 --commit이 멈춘다, 기본 0.40)")
    apply.add_argument("--ignore-ratio-warning", action="store_true",
                       help="비정상 비율 경고를 확인했으니 그래도 반영한다")
    apply.add_argument("--chunk-size", type=int, default=200,
                       help="한 번에 키워드를 붙이는 컷 수 (기본 200). 진행도 이 단위")
    apply.add_argument("--catalog-backup-dir", type=Path,
                       help="반영 전에 Capture One 카탈로그 백업을 만들 폴더 (기본: 만들지 않음)")
    sort = sub.add_parser(
        "sort", help="분석 결과대로 사진을 폴더(버릴 것 같은 컷/직접 확인/이상 없음)로 복제해 나눔"
    )
    sort.add_argument("--folder", type=_folder, required=True, help="행사 폴더 (읽기만 한다)")
    sort.add_argument("--report", type=Path,
                      help="scan이 만든 bcut-report.csv (기본: bcut-out/<행사 폴더 이름>/)")
    sort.add_argument("--out", type=Path,
                      help="정리 결과를 만들 상위 폴더 (기본: scan 결과 폴더). 행사 폴더 안은 "
                           "안 된다. 같은 디스크면 복제라 공간이 거의 안 든다")
    sort.add_argument("--rescue", type=Path,
                      help="남길 컷 목록 (HTML 리포트에서 저장한 파일). 이상 없음 폴더로 간다")
    sort.add_argument("--no-by-reason", action="store_true",
                      help="문제 종류별 폴더(눈 감김 등)를 만들지 않는다")
    sort.add_argument("--commit", action="store_true",
                      help="실제로 만든다. 없으면 미리보기만 한다")

    serve = sub.add_parser(
        "serve", help="앱 화면이 쓰는 로컬 서버를 띄운다 (127.0.0.1에서만, 토큰 필수)"
    )
    serve.add_argument("--port", type=int, default=0, help="포트 (기본 0 = 빈 포트를 알아서 고름)")
    serve.add_argument("--data-dir", type=Path,
                       help="분석 결과를 두는 폴더 (기본: ~/Library/Application Support/bcut)")

    albums = sub.add_parser(
        "albums", help="전용 스마트 앨범(후보, 확인, 정상, 사유별)을 만든다 (기본은 미리보기)"
    )
    albums.add_argument("--catalog", required=True,
                        help="열려 있어야 하는 Capture One 카탈로그 이름 (다르면 멈춘다)")
    albums.add_argument("--config", type=Path, help="설정 파일(TOML)")
    albums.add_argument("--commit", action="store_true", help="실제로 만든다. 없으면 미리보기만")

    doctor = sub.add_parser(
        "doctor", help="환경과 Capture One 연결을 점검한다 (읽기만 한다)"
    )
    doctor.add_argument("--catalog", help="점검할 Capture One 카탈로그 이름 (없으면 환경만 점검)")
    doctor.add_argument("--config", type=Path, help="설정 파일(TOML), 키워드 접두어를 읽는다")

    rollback = sub.add_parser(
        "rollback", help="apply가 붙인 전용 키워드를 떼어 되돌린다 (기본은 dry-run)"
    )
    rollback.add_argument("--folder", type=_folder, required=True, help="행사 폴더 (읽기만 한다)")
    rollback.add_argument("--catalog", required=True,
                          help="열려 있어야 하는 Capture One 카탈로그 이름 (다르면 멈춘다)")
    rollback.add_argument("--out", type=Path,
                          help="apply가 백업을 쓴 폴더 (기본: scan 결과 폴더)")
    rollback.add_argument("--commit", action="store_true",
                          help="실제로 되돌린다. 없으면 dry-run(미리보기)만 한다")
    return parser


def resolve_out_dir(folder: Path, out: Path | None) -> Path:
    """결과 폴더를 정한다. 행사 폴더 안이면 읽기 전용 약속을 깨므로 거부한다."""
    target = (out if out is not None else DEFAULT_OUT_ROOT / folder.resolve().name).expanduser()
    folder_abs, target_abs = folder.resolve(), target.resolve()
    if target_abs == folder_abs or folder_abs in target_abs.parents:
        raise ValueError(
            f"결과 폴더가 행사 폴더 안이다: {target_abs}. scan은 행사 폴더에 아무것도 쓰지 않는다. "
            "--out으로 다른 폴더를 지정한다."
        )
    return target


def run_scan(args: argparse.Namespace) -> int:
    # 무거운 모듈(Vision 등)은 scan을 쓸 때만 불러온다
    from bcut.config import ConfigError, load_config
    from bcut.report.csv_report import write_csv
    from bcut.report.html_report import render_html
    from bcut.report.run_log import build_log, write_log
    from bcut.scan import (
        ALL_STATUSES,
        FLAGGED_STATUSES,
        count_by_reason,
        count_by_status,
        list_photos,
        scan_folder,
    )

    try:
        out_dir = resolve_out_dir(args.folder, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR

    try:
        config = load_config(args.config)
    except (OSError, ConfigError) as exc:
        print(f"설정 파일을 읽을 수 없다: {exc}", file=sys.stderr)
        return USAGE_ERROR

    photos = list_photos(args.folder)
    if not photos:
        print(f"사진(CR3)이 없다: {args.folder}", file=sys.stderr)
        return USAGE_ERROR

    thresholds, exposure_thresholds = config.eyes, config.exposure
    sharpness_thresholds = config.sharpness
    statuses = ALL_STATUSES if args.thumbs == "all" else FLAGGED_STATUSES
    print(f"{len(photos)}장을 분석한다 (읽기 전용). 결과 폴더: {out_dir}")
    started = time.perf_counter()
    started_at = datetime.now()

    def progress(done: int, total: int) -> None:
        if done == total or done % 50 == 0:
            print(f"  {done}/{total}", flush=True)

    results = scan_folder(
        args.folder, thresholds=thresholds, exposure_thresholds=exposure_thresholds,
        sharpness_thresholds=sharpness_thresholds, thumb_width=args.thumb_width,
        eyes_tier=config.tier_for("eyes_closed"), exposure_tier=config.tier_for("exposure"),
        sharpness_tiers={k: config.tier_for(k) for k in ("blur", "out_of_focus")},
        thumb_statuses=statuses, workers=args.workers, progress=progress,
    )
    seconds = time.perf_counter() - started
    finished_at = datetime.now()

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(results, out_dir / "bcut-report.csv", tool_version=__version__,
              config_version=config.config_version)
    write_log(build_log(results, folder_name=args.folder.resolve().name, started=started_at,
                        finished=finished_at, seconds=seconds, config=config, version=__version__),
              out_dir / "bcut-log.json")
    html = render_html(
        results, folder_name=args.folder.resolve().name,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        thresholds=thresholds, exposure_thresholds=exposure_thresholds,
        sharpness_thresholds=sharpness_thresholds, thumbs_mode=args.thumbs,
    )
    (out_dir / "bcut-report.html").write_text(html, encoding="utf-8")

    counts = count_by_status(results)
    errors = sum(1 for r in results if r.error)
    size_mb = (out_dir / "bcut-report.html").stat().st_size / 1_048_576
    print(f"완료: {seconds:.1f}초 ({seconds / len(results) * 1000:.0f} ms/장)")
    summary = (
        f"  B컷 후보 {counts['candidate']} / 사람이 확인 {counts['review']} / "
        f"정상 {counts['normal']} / 얼굴 없음 {counts['no_face']} / "
        f"판정 불가 {counts['unscorable']}"
    )
    print(summary + (f" / 읽기 실패 {errors}" if errors else ""))
    reasons = count_by_reason(results)
    print(f"  사유별: 눈 감김 {reasons['eyes_closed']}장, 노출 {reasons['exposure']}장, "
          f"흔들림 {reasons['blur']}장, 초점 실패 {reasons['out_of_focus']}장"
          f" (사유가 겹친 사진 {reasons['both']}장)")
    print(f"  {out_dir / 'bcut-report.csv'}")
    print(f"  {out_dir / 'bcut-log.json'}")
    print(f"  {out_dir / 'bcut-report.html'} ({size_mb:.1f} MB)")
    print("  HTML에는 사진 썸네일이 있다. 이 컴퓨터에서만 쓰고 다른 사람에게 보내지 않는다.")
    return 0


def _log_action(out_dir: Path, command: str, args: argparse.Namespace, started_at: str,
                started: float, config, *, extra: dict | None = None,
                error: str | None = None) -> None:
    """실행 기록 한 줄을 결과 폴더에 덧붙인다 (못 써도 본 작업은 계속한다)."""
    from bcut.report.action_log import append_action

    record = {
        "command": command, "mode": "commit" if getattr(args, "commit", False) else "dry-run",
        "started_at": started_at, "seconds": round(time.perf_counter() - started, 1),
        "catalog": args.catalog, "tool_version": __version__,
        "config_version": getattr(config, "config_version", None),
        "error": error, **(extra or {}),
    }
    append_action(out_dir, record)


def run_apply(args: argparse.Namespace) -> int:
    from bcut.apply import ApplyError, RatioLimits, read_report
    from bcut.apply import run_apply as do_apply
    from bcut.bridge.capture_one import CaptureOneBridge
    from bcut.bridge.osascript import AppleScriptError, explain_error
    from bcut.config import ConfigError, load_config

    try:
        out_dir = resolve_out_dir(args.folder, args.out)
        config = load_config(args.config)
    except (ValueError, OSError, ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR
    report = args.report or out_dir / "bcut-report.csv"
    try:
        plan, stats = read_report(report, config.keyword_prefix)
        limits = RatioLimits(args.max_candidate_ratio, args.max_raised_ratio)
    except (ApplyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR

    bridge = CaptureOneBridge(args.catalog)
    started = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        result = do_apply(
            bridge, plan, args.folder, out_dir, commit=args.commit,
            allow_partial=args.allow_partial, tool_version=__version__,
            config_version=config.config_version, backups_dir=args.catalog_backup_dir,
            now=lambda: datetime.now().isoformat(timespec="seconds"),
            stats=stats, limits=limits, ignore_ratio_warning=args.ignore_ratio_warning,
            chunk_size=args.chunk_size,
            progress=lambda kw, done, total: print(f"  {kw}: {done}/{total}", flush=True),
        )
    except AppleScriptError as exc:
        _log_action(out_dir, "apply", args, started_at, started, config,
                    error=explain_error(exc))
        print(explain_error(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR

    _log_action(out_dir, "apply", args, started_at, started, config, extra={
        "planned": result.planned, "keywords": result.keyword_counts,
        "already": result.already, "applied_files": result.applied_files,
        "warnings": result.warnings, "violations": result.violations,
        "missing_keywords": result.missing_keywords, "aborted": result.aborted,
        "unmatched": 0 if result.match is None else len(result.match.missing)
        + len(result.match.ambiguous),
    })
    label = "반영" if args.commit else "dry-run (아무것도 바꾸지 않음)"
    print(f"{label}: 카탈로그 {args.catalog}, 리포트 {stats.total}장 중 "
          f"후보 {stats.by_status.get('candidate', 0)}({stats.candidate_ratio:.0%}) / "
          f"확인 {stats.by_status.get('review', 0)} -> 반영 대상 {result.planned}장 "
          f"({stats.raised_ratio:.0%})")
    if stats.by_reason:
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(stats.by_reason.items()))
        print(f"  사유별(후보·확인): {reasons}")
    for w in result.warnings:
        print(f"  경고: {w}", file=sys.stderr)
    if result.match is not None:
        m = result.match
        print(f"  카탈로그에서 찾음 {len(m.matched)}장 / 못 찾음 {len(m.missing)} / "
              f"모호 {len(m.ambiguous)} / 파일명으로 짝지음 {len(m.by_name)}")
        for title, names in (("못 찾은 컷", m.missing), ("모호한 컷", list(m.ambiguous)),
                             ("경로가 달라 파일명으로 짝지은 컷", m.by_name)):
            if names:
                more = f" 외 {len(names) - 5}장" if len(names) > 5 else ""
                print(f"    {title}: {', '.join(names[:5])}{more}")
    if result.aborted:
        print(f"  중단: {result.aborted}", file=sys.stderr)
        return 1
    for kw, n in result.keyword_counts.items():
        print(f"  {kw}: {n}장")
    print(f"  이미 붙어 있어 건너뜀 {result.already}장")
    if args.commit:
        print(f"  키워드를 붙인 컷 {result.applied_files}장, 백업 {result.backup_path}")
        for v in result.violations:
            print(f"  검증 실패: {v}", file=sys.stderr)
        return 0 if result.ok else 1
    hint = " (비정상 비율 경고가 있어 --ignore-ratio-warning도 필요하다)" if result.warnings else ""
    print("  실제로 반영하려면 --commit을 붙인다." + hint)
    return 0


def run_rollback(args: argparse.Namespace) -> int:
    from bcut.bridge.backup import FILENAME
    from bcut.bridge.capture_one import CaptureOneBridge
    from bcut.bridge.osascript import AppleScriptError, explain_error
    from bcut.rollback import run_rollback as do_rollback

    try:
        out_dir = resolve_out_dir(args.folder, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR
    started = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        result = do_rollback(CaptureOneBridge(args.catalog), out_dir / FILENAME,
                             commit=args.commit)
    except AppleScriptError as exc:
        _log_action(out_dir, "rollback", args, started_at, started, None,
                    error=explain_error(exc))
        print(explain_error(exc), file=sys.stderr)
        return 1
    _log_action(out_dir, "rollback", args, started_at, started, None, extra={
        "entries": result.entries, "keywords": result.keyword_counts,
        "already_clean": result.already_clean, "missing": len(result.missing),
        "user_changed": len(result.user_changed), "stripped_files": result.stripped_files,
        "violations": result.violations, "aborted": result.aborted,
    })

    label = "되돌리기" if args.commit else "dry-run (아무것도 바꾸지 않음)"
    print(f"{label}: 카탈로그 {args.catalog}, 백업 컷 {result.entries}장")
    if result.aborted:
        print(f"  중단: {result.aborted}", file=sys.stderr)
        return 1
    for kw, n in result.keyword_counts.items():
        print(f"  {kw}: {n}장에서 뗀다" if not args.commit else f"  {kw}: {n}장에서 뗐다")
    print(f"  이미 키워드가 없어 그대로 둠 {result.already_clean}장")
    if result.missing:
        print(f"  카탈로그에서 못 찾은 컷 {len(result.missing)}장: {', '.join(result.missing[:5])}")
    if result.user_changed:
        names = ", ".join(result.user_changed[:5])
        print(f"  반영 후 사용자가 별점·태그를 바꾼 컷 {len(result.user_changed)}장 "
              f"(건드리지 않음): {names}")
    if result.user_keywords:
        print(f"  반영 후 사용자가 붙인 키워드가 있는 컷 {len(result.user_keywords)}장 (그대로 둠)")
    if args.commit:
        print(f"  키워드를 뗀 컷 {result.stripped_files}장")
        for v in result.violations:
            print(f"  검증 실패: {v}", file=sys.stderr)
        return 0 if result.ok else 1
    print("  실제로 되돌리려면 --commit을 붙인다.")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    from bcut.config import ConfigError, load_config
    from bcut.doctor import FAIL, OK, WARN, has_failure, run_checks

    try:
        config = load_config(args.config)
    except (OSError, ConfigError) as exc:
        print(f"설정 파일을 읽을 수 없다: {exc}", file=sys.stderr)
        return USAGE_ERROR
    checks = run_checks(args.catalog, keyword_prefix=config.keyword_prefix)
    mark = {OK: "[ok]  ", WARN: "[주의]", FAIL: "[실패]"}
    for c in checks:
        print(f"{mark.get(c.status, '[  - ]')} {c.name}: {c.detail}")
        if c.hint:
            print(f"        -> {c.hint}")
    bad = sum(1 for c in checks if c.status == FAIL)
    warn = sum(1 for c in checks if c.status == WARN)
    print(f"실패 {bad}, 주의 {warn}")
    return 1 if has_failure(checks) else 0


def run_sort(args: argparse.Namespace) -> int:
    from bcut.organize import SortError, read_rescue
    from bcut.organize import run_sort as do_sort
    from bcut.report.action_log import append_action

    try:
        out_dir = resolve_out_dir(args.folder, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR
    report = args.report or resolve_out_dir(args.folder, None) / "bcut-report.csv"
    started = time.perf_counter()
    try:
        result = do_sort(args.folder, report, out_dir, commit=args.commit,
                         rescue=read_rescue(args.rescue), by_reason=not args.no_by_reason)
    except SortError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR

    plan = result.plan
    label = "정리" if args.commit else "미리보기 (아무것도 만들지 않음)"
    print(f"{label}: 사진 {plan.files}장 -> 복제본 {plan.placements}개 (원본은 그대로)")
    for name, count in plan.counts().items():
        print(f"  {name}: {count}장")
    if plan.rescued:
        print(f"  남기기로 한 컷 {len(plan.rescued)}장은 이상 없음 폴더로 간다")
    if plan.missing:
        print(f"  주의: 리포트에는 있지만 행사 폴더에 없는 사진 {len(plan.missing)}장 (건너뜀)",
              file=sys.stderr)
    if plan.unlisted:
        print(f"  주의: 행사 폴더에는 있지만 리포트에 없는 사진 {len(plan.unlisted)}장 "
              "(분석 뒤에 추가된 사진, 건너뜀)", file=sys.stderr)
    if plan.unknown_rescue:
        n = len(plan.unknown_rescue)
        print(f"  주의: 남길 컷 목록에서 의심 컷이 아닌 파일 {n}개는 무시했다", file=sys.stderr)
    how = "APFS 복제(공간 거의 안 듦)" if result.method == "clone" else "복사"
    extra = f", 필요한 용량 약 {result.needs_space / 1e9:.1f}GB" if result.needs_space else ""
    print(f"  방식: {how}{extra}")
    append_action(out_dir, {
        "command": "sort", "mode": result.mode, "tool_version": __version__,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 1), "photos": plan.files,
        "counts": plan.counts(), "rescued": len(plan.rescued), "method": result.method,
        "aborted": result.aborted, "mismatches": len(result.mismatches),
    })
    if result.aborted:
        print(f"  중단: {result.aborted}", file=sys.stderr)
        return 1
    if args.commit:
        print(f"  결과 폴더: {result.result_dir}")
        print(f"  복제 {result.cloned}개, 복사 {result.copied}개")
        for m in result.mismatches:
            print(f"  검증 실패(크기가 다름): {m}", file=sys.stderr)
        return 0 if result.ok else 1
    print("  실제로 만들려면 --commit을 붙인다.")
    return 0


def run_serve(args: argparse.Namespace) -> int:
    import json as _json
    import os

    from bcut.ui.server import serve

    data_dir = args.data_dir or Path.home() / "Library" / "Application Support" / "bcut"
    token = os.environ.get("BCUT_TOKEN") or None  # 앱 셸이 정한 토큰을 쓸 수 있다

    def announce(url: str, tok: str) -> None:
        # 앱 셸이 읽는 한 줄. 토큰은 이 서버를 쓰는 쪽에만 알려 준다.
        print(_json.dumps({"url": url, "token": tok}), flush=True)

    try:
        serve(data_dir, port=args.port, token=token, announce=announce)
    except (OSError, ValueError) as exc:
        print(f"서버를 시작할 수 없다: {exc}", file=sys.stderr)
        return 1
    return 0


def run_albums(args: argparse.Namespace) -> int:
    from bcut.bridge.albums import album_specs, create_album, list_albums, plan_albums
    from bcut.bridge.capture_one import CaptureOneBridge
    from bcut.bridge.osascript import AppleScriptError, explain_error
    from bcut.config import ConfigError, load_config

    try:
        config = load_config(args.config)
    except (OSError, ConfigError) as exc:
        print(f"설정 파일을 읽을 수 없다: {exc}", file=sys.stderr)
        return USAGE_ERROR
    bridge = CaptureOneBridge(args.catalog)
    try:
        plan = plan_albums(list_albums(bridge), album_specs(config.keyword_prefix))
        label = "만들기" if args.commit else "미리보기 (아무것도 바꾸지 않음)"
        print(f"스마트 앨범 {label}: 카탈로그 {args.catalog}")
        for s in plan.to_create:
            print(f"  만들 앨범: {s.name}  ({s.describe()})")
        for name in plan.existing:
            note = " (규칙이 달라서 건드리지 않았다)" if name in plan.rule_mismatch else ""
            print(f"  이미 있음: {name}{note}")
        if args.commit:
            for s in plan.to_create:
                print(f"  {s.name}: {create_album(bridge, s)}")
        elif plan.to_create:
            print("  실제로 만들려면 --commit을 붙인다.")
    except AppleScriptError as exc:
        print(explain_error(exc), file=sys.stderr)
        return 1
    return 0


def run_calibrate(args: argparse.Namespace) -> int:
    from bcut.calibrate import (
        CalibrationError,
        fit_eyes,
        read_labels,
        render_config,
        samples_from_results,
    )
    from bcut.scan import list_photos, scan_folder
    from bcut.score.eyes import EyesThresholds

    default_out = DEFAULT_OUT_ROOT / args.folder.resolve().name / "bcut-config.toml"
    out = (args.out or default_out).expanduser()
    out_abs, folder_abs = out.resolve(), args.folder.resolve()
    if folder_abs in out_abs.parents:
        print(f"설정 파일 경로가 행사 폴더 안이다: {out_abs}. 행사 폴더에는 아무것도 쓰지 않는다.",
              file=sys.stderr)
        return USAGE_ERROR
    if not args.labels.is_file():
        print(f"라벨 파일을 찾을 수 없다: {args.labels}", file=sys.stderr)
        return USAGE_ERROR
    if not list_photos(args.folder):
        print(f"사진(CR3)이 없다: {args.folder}", file=sys.stderr)
        return USAGE_ERROR

    base = EyesThresholds()
    try:
        labels = read_labels(args.labels)
        print(f"사진을 분석해 눈 점수를 얻는다 (읽기 전용), 라벨 {len(labels)}장")
        results = scan_folder(args.folder, thumb_width=0, workers=args.workers)
        samples, skipped = samples_from_results(results, labels, base.min_eye_width_frac)
        cal = fit_eyes(samples, base, review_recall=args.review_recall, skipped=skipped)
    except (CalibrationError, OSError, UnicodeDecodeError) as exc:
        print(f"보정할 수 없다: {exc}", file=sys.stderr)
        return USAGE_ERROR

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_config(cal), encoding="utf-8")
    t = cal.thresholds
    print(f"B {cal.n_positive}장, 정상 {cal.n_negative}장 (점수를 못 믿어 뺀 컷 {cal.skipped}장)")
    print(f"  후보 경계 {t.candidate_max:.4f} (기본 {base.candidate_max}), "
          f"확인 경계 {t.review_max:.4f} (기본 {base.review_max})")
    print(f"  같은 라벨로 잰 값(낙관적): 후보 재현율 {cal.candidate_recall:.0%}, "
          f"후보+확인 {cal.raised_recall:.0%}, 확인 부담 정상 {cal.review_burden}장")
    print(f"  {out}")
    print("  이 값은 학습에 쓴 라벨로 잰 것이라 낙관적이다. 새 행사나 교차 검증으로 확인한다.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "scan":
        return run_scan(args)
    if args.command == "calibrate":
        return run_calibrate(args)
    if args.command == "apply":
        return run_apply(args)
    if args.command == "albums":
        return run_albums(args)
    if args.command == "sort":
        return run_sort(args)
    if args.command == "serve":
        return run_serve(args)
    if args.command == "doctor":
        return run_doctor(args)
    if args.command == "rollback":
        return run_rollback(args)
    print(f"'{args.command}' 명령은 아직 구현되지 않았다. 아무것도 바꾸지 않았다.", file=sys.stderr)
    return NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
