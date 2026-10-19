"""노출 판정이 리포트에서 어떻게 보이는지 확인하는 **데모** 리포트를 만든다.

실제 사진에는 노출 이상이 없어서(두 행사 모두 0장) 리포트의 노출 화면을 볼 수 없다. 그래서 실제
사진 일부의 노출을 **인위적으로 바꾼 상태**로 판정해(얼굴 검출부터 새로 한다) 노출로 걸린 컷이 화면에
어떻게 나오는지 보여 준다. 제목에 "데모"라고 분명히 적는다. 원본 사진은 바꾸지 않는다 (읽기만 한다).

사용법:
    python eval/make_exposure_demo.py [행사 폴더] [결과 폴더]
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from bcut import scan as scan_module
from bcut.imageio import read_embedded_jpeg
from bcut.imageio.embedded import LoadedImage
from bcut.report.csv_report import write_csv
from bcut.report.html_report import render_html
from bcut.scan import analyze_photo, count_by_reason, list_photos
from bcut.synth import shift_exposure

DEFAULT_EVENT = Path.home() / "photo-select-data" / "events" / "260223_EVENT_A_seg400"
DEFAULT_OUT = Path.home() / "photo-select-data" / "reports" / "exposure-demo"
EV_CYCLE = (2.0, 3.0, -3.0, 0.0, -2.0, 1.0)  # 사진마다 번갈아 적용. 0은 바꾸지 않은 원본
STEP = 12  # 폴더의 사진을 이 간격으로 고른다


def main() -> None:
    event = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_EVENT
    out_dir = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else DEFAULT_OUT
    if event.resolve() in out_dir.resolve().parents or event.resolve() == out_dir.resolve():
        raise SystemExit("결과 폴더가 행사 폴더 안이다")

    photos = list_photos(event)[::STEP]
    plan = {p.name: EV_CYCLE[i % len(EV_CYCLE)] for i, p in enumerate(photos)}
    original_read = read_embedded_jpeg

    def shifted_read(path: Path) -> LoadedImage:
        loaded = original_read(path)
        ev = plan[Path(path).name]
        if ev == 0:
            return loaded
        return LoadedImage(image=shift_exposure(loaded.image, ev),
                           full_width=loaded.full_width, full_height=loaded.full_height)

    scan_module.read_embedded_jpeg = shifted_read  # 이 프로세스 안에서만 바꾼다
    results = [analyze_photo(p) for p in photos]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(results, out_dir / "bcut-report.csv")
    html = render_html(
        results, folder_name=event.name, generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=f"[데모] 노출을 인위적으로 바꾼 사진 · {event.name}",
        scope="데모: 사진 일부의 노출을 인위적으로 바꿈 (실제 노출 결함이 아님)",
    )
    (out_dir / "bcut-report.html").write_text(html, encoding="utf-8")

    print(f"데모 리포트: {len(results)}장 -> {out_dir / 'bcut-report.html'}")
    print(f"{'파일':14} {'노출 변화':>8} {'등급':12} {'노출 이유':14} 눈")
    for r in results:
        ev = plan[r.file]
        print(f"{r.file:14} {ev:>+7.1f}단 {r.status:12} {r.exposure_kind or '-':14} {r.eyes_status}")
    reasons = count_by_reason(results)
    flagged = sum(1 for r in results if r.exposure_kind)
    shifted = sum(1 for v in plan.values() if v != 0)
    print(f"\n노출을 바꾼 사진 {shifted}장 중 노출로 걸린 사진 {flagged}장 (바꾸지 않은 원본 중 걸린 것: "
          f"{sum(1 for r in results if r.exposure_kind and plan[r.file] == 0)}장)")
    print(f"사유별: 눈 감김 {reasons['eyes_closed']}장, 노출 {reasons['exposure']}장, 둘 다 {reasons['both']}장")


if __name__ == "__main__":
    main()
