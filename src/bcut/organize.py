"""폴더 정리 (`bcut sort`, devplan Phase 3b S1, docs/organizer-plan.md).

`scan`이 만든 리포트(`bcut-report.csv`)를 읽어 사진을 등급·사유별 폴더로 **복제**한다.

- **원본 폴더는 읽기 전용이다.** 사진을 옮기거나 지우지 않고, 원본 폴더에 아무것도 쓰지 않는다.
- 결과는 `--out` 아래에 **실행마다 새 폴더**(`<행사>_정리_<날짜시각>`)로 만든다. 이 도구는 파일 삭제
  호출을 쓰지 않으므로, 이전 결과를 지우고 다시 만들지 않는다 (필요 없는 결과 폴더는 사람이 지운다).
- 같은 디스크에서는 APFS 복제(`clonefile`)를 써서 시간과 공간이 거의 들지 않는다. 복제가 안 되면
  (다른 디스크 등) 복사하고, 이때는 필요한 용량을 먼저 확인한다.
- **미리보기가 기본이다** (`commit=True`일 때만 만든다).

폴더 규칙 (화면과 같은 쉬운 말):
  셀렉 = 사용자가 셀렉한 사진 (셀렉 폴더에만 담긴다), 보류 = 보류한 사진 (보류 폴더에만)
  버릴 것 같은 컷 = candidate + 사용자가 버릴 컷으로 표시한 사진 (spec FR-25, 기록에서 구분)
  표시가 없는 사진은 등급대로: 직접 확인 = review, 판단 못 함 = unscorable,
  이상 없음 = normal, no_face (옛 "남기기" 목록 `--rescue`는 CLI에만 남고 이상 없음 폴더로 간다)
  문제 종류별/<문제 종류> = 표시가 없는 버릴 것 같은 컷·직접 확인 컷이 걸린 문제마다
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bcut import __version__

FOLDER_CANDIDATE = "버릴 것 같은 컷"
FOLDER_REVIEW = "직접 확인"
FOLDER_NORMAL = "이상 없음"
FOLDER_UNSCORABLE = "판단 못 함"
FOLDER_REASONS = "문제 종류별"
FOLDER_PICK = "셀렉"
FOLDER_MAYBE = "보류"
# 사용자 표시 -> 폴더. 버릴 컷은 도구가 찾은 "버릴 것 같은 컷" 폴더에 합친다
MARK_FOLDER = {"pick": FOLDER_PICK, "maybe": FOLDER_MAYBE, "discard": FOLDER_CANDIDATE}
FOLDER_ORDER = (FOLDER_PICK, FOLDER_MAYBE, FOLDER_CANDIDATE, FOLDER_REVIEW, FOLDER_NORMAL,
                FOLDER_UNSCORABLE, FOLDER_REASONS)  # 미리보기에서 셀렉이 맨 앞
RECORD_NAME = "정리 기록.json"

REASON_LABELS = {
    "eyes_closed": "눈 감김", "exposure": "너무 밝거나 어두움", "blur": "흔들려 찍힘",
    "out_of_focus": "초점이 안 맞음",
}
STATUS_FOLDER = {
    "candidate": FOLDER_CANDIDATE, "review": FOLDER_REVIEW, "normal": FOLDER_NORMAL,
    "no_face": FOLDER_NORMAL, "unscorable": FOLDER_UNSCORABLE,
}
RESCUABLE = ("candidate", "review")  # 살리기로 정상에 합칠 수 있는 등급


class SortError(RuntimeError):
    """정리를 시작할 수 없다 (리포트·폴더 문제, 용량 부족 등)."""


@dataclass(frozen=True)
class Row:
    file: str
    status: str
    reasons: tuple[str, ...]


def read_rows(report_csv: Path) -> list[Row]:
    try:
        with report_csv.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not {"file", "status"} <= set(reader.fieldnames):
                raise SortError("리포트 CSV에 file, status 열이 있어야 한다")
            rows = list(reader)
    except OSError as exc:
        raise SortError(f"리포트를 읽을 수 없다: {exc}. 먼저 `bcut scan`을 실행한다") from exc
    out = []
    for r in rows:
        status = (r["status"] or "").strip()
        if status not in STATUS_FOLDER:
            raise SortError(f"알 수 없는 등급: {status!r} ({r['file']})")
        reasons = tuple(x for x in (r.get("reason") or "").split(";") if x)
        out.append(Row(r["file"], status, reasons))
    return out


def read_rescue(path: Path | None) -> set[str]:
    """HTML 리포트의 "살린 컷 이름 저장"이 만든 파일(한 줄에 파일 이름 하나)을 읽는다."""
    if path is None:
        return set()
    try:
        return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError as exc:
        raise SortError(f"살린 컷 목록을 읽을 수 없다: {exc}") from exc


@dataclass
class SortPlan:
    folders: dict[str, list[str]] = field(default_factory=dict)  # 폴더 상대 경로 -> 파일 이름들
    placements: int = 0  # 만들 복제본 수 (사유별 중복 포함)
    files: int = 0  # 정리할 원본 사진 수
    rescued: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # 리포트에는 있는데 폴더에 없는 파일
    unlisted: list[str] = field(default_factory=list)  # 폴더에는 있는데 리포트에 없는 파일
    # 살린 컷 목록에 있지만 후보·확인이 아닌 것 (무시한다)
    unknown_rescue: list[str] = field(default_factory=list)
    bytes_total: int = 0  # 복제본 전체 크기 (복사가 되면 실제로 드는 용량)
    marked: dict[str, str] = field(default_factory=dict)  # 사용자 표시가 반영된 사진 -> 표시
    unknown_marks: list[str] = field(default_factory=list)  # 표시는 있지만 이번 정리에 없는 사진

    def counts(self) -> dict[str, int]:
        def rank(name: str) -> tuple[int, str]:
            top = name.split("/")[0]
            return (FOLDER_ORDER.index(top) if top in FOLDER_ORDER else len(FOLDER_ORDER), name)
        return {name: len(self.folders[name]) for name in sorted(self.folders, key=rank)}

    def mark_counts(self) -> dict[str, int]:
        return {k: sum(1 for v in self.marked.values() if v == k) for k in MARK_FOLDER}


def plan_sort(
    rows: list[Row], event_folder: Path, *, rescue: set[str] | None = None,
    marks: dict[str, str] | None = None, by_reason: bool = True,
) -> SortPlan:
    rescue = rescue or set()
    marks = {f: k for f, k in (marks or {}).items() if k in MARK_FOLDER}
    plan = SortPlan()
    folders: dict[str, list[str]] = defaultdict(list)
    listed = {r.file for r in rows}
    present = {p.name for p in event_folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    plan.unlisted = sorted(n for n in present - listed if n.lower().endswith(".cr3"))
    plan.unknown_rescue = sorted(
        f for f in rescue if f not in listed
        or next(r for r in rows if r.file == f).status not in RESCUABLE)
    for r in sorted(rows, key=lambda x: x.file):
        if r.file not in present:
            plan.missing.append(r.file)
            continue
        size = (event_folder / r.file).stat().st_size
        plan.files += 1
        if r.file in marks:  # 사용자 표시가 도구 판정보다 우선한다
            plan.marked[r.file] = marks[r.file]
            places = [MARK_FOLDER[marks[r.file]]]
        elif r.status in RESCUABLE and r.file in rescue:
            plan.rescued.append(r.file)
            places = [FOLDER_NORMAL]
        else:
            places = [STATUS_FOLDER[r.status]]
            if by_reason and r.status in RESCUABLE:
                places += [f"{FOLDER_REASONS}/{REASON_LABELS.get(x, x)}" for x in r.reasons]
        for p in places:
            folders[p].append(r.file)
            plan.placements += 1
            plan.bytes_total += size
    plan.unknown_marks = sorted(f for f in marks if f not in plan.marked)
    plan.folders = dict(folders)
    return plan


# ---- 복제 --------------------------------------------------------------------------------

def _clonefile(src: Path, dst: Path) -> bool:
    try:
        libc = ctypes.CDLL("libSystem.B.dylib", use_errno=True)
        fn = libc.clonefile
    except (OSError, AttributeError):
        return False
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    fn.restype = ctypes.c_int
    return fn(os.fsencode(src), os.fsencode(dst), 0) == 0


def clone_or_copy(src: Path, dst: Path) -> str:
    """APFS 복제를 먼저 시도하고, 안 되면 복사한다. 돌려주는 값: "clone" 또는 "copy"."""
    if _clonefile(src, dst):
        return "clone"
    shutil.copy2(src, dst)
    return "copy"


def same_volume(a: Path, b: Path) -> bool:
    """b(없으면 가장 가까운 상위 폴더)가 a와 같은 디스크인가."""
    probe = b
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return a.stat().st_dev == probe.stat().st_dev


def result_dir_name(event_folder: Path, now: datetime) -> str:
    return f"{event_folder.name}_정리_{now.strftime('%Y-%m-%d_%H%M')}"


def unique_dir(parent: Path, name: str) -> Path:
    """없는 폴더 이름을 고른다 (같은 분에 다시 실행해도 이전 결과를 덮어쓰지 않는다)."""
    candidate, n = parent / name, 2
    while candidate.exists():
        candidate = parent / f"{name}-{n}"
        n += 1
    return candidate


@dataclass
class SortResult:
    mode: str
    plan: SortPlan
    result_dir: Path | None = None
    method: str = ""  # clone | copy | mixed (미리보기에서는 예상)
    needs_space: int = 0  # 복사가 될 때 필요한 용량(바이트). 복제면 0
    aborted: str | None = None
    cloned: int = 0
    copied: int = 0
    mismatches: list[str] = field(default_factory=list)  # 크기가 다른 복제본

    @property
    def ok(self) -> bool:
        return self.aborted is None and not self.mismatches


def run_sort(
    event_folder: Path, report_csv: Path, out_root: Path, *, commit: bool = False,
    rescue: set[str] | None = None, marks: dict[str, str] | None = None, by_reason: bool = True,
    now: Callable[[], datetime] = datetime.now,
    free_space: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free,
) -> SortResult:
    rows = read_rows(report_csv)
    plan = plan_sort(rows, event_folder, rescue=rescue, marks=marks, by_reason=by_reason)
    res = SortResult(mode="commit" if commit else "dry-run", plan=plan)
    if not plan.files:
        res.aborted = "정리할 사진이 없다 (리포트의 파일이 행사 폴더에 없다)"
        return res
    clone_ok = same_volume(event_folder, out_root)
    res.method = "clone" if clone_ok else "copy"
    res.needs_space = 0 if clone_ok else plan.bytes_total
    if not clone_ok:
        probe = out_root
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free = free_space(probe)
        if free < plan.bytes_total * 1.05:
            need, have = plan.bytes_total / 1e9, free / 1e9
            res.aborted = (f"디스크 여유 공간이 부족하다: 필요 {need:.1f}GB, 여유 {have:.1f}GB. "
                           "같은 디스크의 폴더를 --out으로 지정하면 복제라 공간이 거의 들지 않는다")
            return res
    if not commit:
        return res

    out_root.mkdir(parents=True, exist_ok=True)
    result_dir = unique_dir(out_root, result_dir_name(event_folder, now()))
    result_dir.mkdir()
    res.result_dir = result_dir
    entries: dict[str, list[str]] = defaultdict(list)
    try:
        for folder, files in sorted(plan.folders.items()):
            target = result_dir / folder
            target.mkdir(parents=True, exist_ok=True)
            for name in files:
                src, dst = event_folder / name, target / name
                if clone_or_copy(src, dst) == "clone":
                    res.cloned += 1
                else:
                    res.copied += 1
                entries[name].append(folder)
                if src.stat().st_size != dst.stat().st_size:
                    res.mismatches.append(f"{folder}/{name}")
    except OSError as exc:
        res.aborted = (f"정리 중 멈췄다: {exc}. 이미 만든 파일은 그대로 있다({result_dir}). "
                       "필요 없으면 Finder에서 그 폴더를 지운다")
        _write_record(result_dir, event_folder, report_csv, plan, entries, res, now())
        return res
    res.method = "clone" if res.copied == 0 else ("copy" if res.cloned == 0 else "mixed")
    _write_record(result_dir, event_folder, report_csv, plan, entries, res, now())
    return res


def _write_record(result_dir: Path, event_folder: Path, report_csv: Path, plan: SortPlan,
                  entries: dict[str, list[str]], res: SortResult, when: datetime) -> None:
    record = {
        "tool_version": __version__,
        "created_at": when.isoformat(timespec="seconds"),
        "event_folder": str(event_folder),
        "report": str(report_csv),
        "counts": plan.counts(),
        "photos": plan.files,
        "placements": plan.placements,
        "method": res.method, "cloned": res.cloned, "copied": res.copied,
        "rescued": plan.rescued, "marks": plan.marked, "missing": plan.missing,
        "unlisted": plan.unlisted,
        "size_mismatches": res.mismatches, "aborted": res.aborted,
        "files": {name: places for name, places in sorted(entries.items())},
    }
    try:
        (result_dir / RECORD_NAME).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
