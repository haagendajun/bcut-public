"""명령줄 진입점.

scan은 구현했다 (눈 감김 판정, CSV와 HTML 리포트). calibrate는 Phase 1 후반에,
apply와 rollback은 Phase 2에서 구현한다. 아직 구현되지 않은 명령은 아무것도 바꾸지 않고
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
    scan.add_argument("--thumb-width", type=int, default=320, help="썸네일 폭(px)")
    scan.add_argument("--workers", type=int, help="동시에 처리할 개수 (기본: 최대 6)")

    calibrate = sub.add_parser("calibrate", help="라벨(A/B)로 임계값을 보정한다")
    calibrate.add_argument("--labels", type=Path, required=True, help="라벨 CSV")
    calibrate.add_argument("--out", type=Path, help="설정 파일 출력 경로")

    sub.add_parser("apply", help="[Phase 2] 후보를 Capture One에 반영한다")
    sub.add_parser("rollback", help="[Phase 2] 반영 이전 상태로 되돌린다")
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
    from bcut.report.csv_report import write_csv
    from bcut.report.html_report import render_html
    from bcut.scan import (
        ALL_STATUSES,
        FLAGGED_STATUSES,
        count_by_reason,
        count_by_status,
        list_photos,
        scan_folder,
    )
    from bcut.score.exposure import ExposureThresholds
    from bcut.score.eyes import EyesThresholds

    try:
        out_dir = resolve_out_dir(args.folder, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE_ERROR

    photos = list_photos(args.folder)
    if not photos:
        print(f"사진(CR3)이 없다: {args.folder}", file=sys.stderr)
        return USAGE_ERROR

    thresholds = EyesThresholds()
    exposure_thresholds = ExposureThresholds()
    statuses = ALL_STATUSES if args.thumbs == "all" else FLAGGED_STATUSES
    print(f"{len(photos)}장을 분석한다 (읽기 전용). 결과 폴더: {out_dir}")
    started = time.perf_counter()

    def progress(done: int, total: int) -> None:
        if done == total or done % 50 == 0:
            print(f"  {done}/{total}", flush=True)

    results = scan_folder(
        args.folder, thresholds=thresholds, exposure_thresholds=exposure_thresholds,
        thumb_width=args.thumb_width,
        thumb_statuses=statuses, workers=args.workers, progress=progress,
    )
    seconds = time.perf_counter() - started

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(results, out_dir / "bcut-report.csv")
    html = render_html(
        results, folder_name=args.folder.resolve().name,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        thresholds=thresholds, exposure_thresholds=exposure_thresholds, thumbs_mode=args.thumbs,
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
    print(f"  사유별: 눈 감김 {reasons['eyes_closed']}장, 노출 {reasons['exposure']}장"
          f" (둘 다 걸린 사진 {reasons['both']}장)")
    print(f"  {out_dir / 'bcut-report.csv'}")
    print(f"  {out_dir / 'bcut-report.html'} ({size_mb:.1f} MB)")
    print("  HTML에는 사진 썸네일이 있다. 이 컴퓨터에서만 쓰고 다른 사람에게 보내지 않는다.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "scan":
        return run_scan(args)
    print(f"'{args.command}' 명령은 아직 구현되지 않았다. 아무것도 바꾸지 않았다.", file=sys.stderr)
    return NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
