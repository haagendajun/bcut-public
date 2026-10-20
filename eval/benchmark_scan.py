"""T1.14 성능 측정: 실제 `scan` 파이프라인(읽기, 얼굴, 눈·노출·흔들림·초점, 썸네일, 리포트 쓰기)의
시간과 메모리를 잰다.

- 시간: 분석(scan_folder)과 리포트 쓰기(CSV+HTML)를 따로 잰다.
- 메모리: 0.5초마다 이 프로세스와 자식 프로세스의 상주 메모리(RSS) 합계를 `ps`로 읽어 최댓값을 낸다.
- 사진은 읽기만 한다. 큰 행사는 같은 사진을 심볼릭 링크로 여러 번 세워 만든 임시 폴더로 흉내 낸다
  (**디스크 캐시가 데워져 있어 실제 첫 읽기보다 빠를 수 있다**).

사용법:  python eval/benchmark_scan.py <폴더> [--copies 1] [--workers 6] [--limit N]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from bcut.report.csv_report import write_csv
from bcut.report.html_report import render_html
from bcut.scan import list_photos, scan_folder


def tree_rss_mb(root_pid: int) -> float:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
    rows = [tuple(int(x) for x in line.split()) for line in out.splitlines() if line.strip()]
    children: dict[int, list[int]] = {}
    rss = {}
    for pid, ppid, kb in rows:
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kb
    total, stack = 0, [root_pid]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total / 1024


class PeakSampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0.0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, tree_rss_mb(os.getpid()))
            self._stop.wait(0.5)

    def finish(self) -> float:
        self._stop.set()
        self.join()
        return self.peak


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--copies", type=int, default=1, help="같은 사진을 이만큼 반복해 큰 행사를 흉내")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    photos = list_photos(args.folder)[: args.limit]
    with tempfile.TemporaryDirectory(prefix="bcut-bench-") as tmp:
        work = Path(tmp)
        for c in range(args.copies):
            for p in photos:
                (work / f"{c:02d}_{p.name}").symlink_to(p.resolve())
        n = len(photos) * args.copies
        sampler = PeakSampler()
        sampler.start()
        t0 = time.perf_counter()
        results = scan_folder(work, workers=args.workers)
        t_scan = time.perf_counter() - t0
        t1 = time.perf_counter()
        out = work.parent / f"{work.name}-out"
        out.mkdir()
        write_csv(results, out / "r.csv")
        html = render_html(results, folder_name="bench", generated_at="-")
        (out / "r.html").write_text(html, encoding="utf-8")
        t_write = time.perf_counter() - t1
        peak = sampler.finish()
        size_mb = (out / "r.html").stat().st_size / 1_048_576
        for f in out.iterdir():
            f.unlink()
        out.rmdir()

    errs = sum(1 for r in results if r.error)
    secs = sorted(r.seconds for r in results)
    print(f"{n}장, 병렬 {args.workers}개: 분석 {t_scan:.1f}초 ({t_scan / n * 1000:.0f} ms/장), "
          f"리포트 쓰기 {t_write:.1f}초, 합계 {t_scan + t_write:.1f}초")
    print(f"  장당(한 장 처리) 중앙 {secs[n // 2] * 1000:.0f} ms, 95% {secs[int(n * .95)] * 1000:.0f} ms,"
          f" 최대 {secs[-1] * 1000:.0f} ms, 오류 {errs}장")
    print(f"  메모리 최대(전체 프로세스 합) {peak:.0f} MB, HTML {size_mb:.1f} MB")
    print(f"  1500장 환산: 약 {(t_scan + t_write) / n * 1500:.0f}초")


if __name__ == "__main__":
    main()
