"""홀드아웃 평가 전에 판정 로직을 동결한 기록을 남기고, 나중에 바뀌지 않았는지 확인한다 (docs/holdout-plan.md 1장).

기록 (`eval/holdout-freeze.json`): 도구 버전, 기본 설정(임계값·사유별 등급), 판정에 쓰는 소스 코드의 해시,
`requirements-lock.txt`의 해시, 홀드아웃 파일 이름 목록의 해시. **사진 내용은 읽지 않는다** (이름만 본다).

사용법:
    python tools/freeze_holdout.py freeze --folder <홀드아웃 복제 폴더> [--tests "383 passed, 1 skipped"]
    python tools/freeze_holdout.py verify --folder <홀드아웃 복제 폴더>   # 평가 직전에 실행. 바뀌었으면 종료 코드 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "eval" / "holdout-freeze.json"
# 판정 결과에 영향을 주는 코드. 리포트·CLI 같은 출력 코드는 바뀌어도 판정은 같으므로 뺀다.
LOGIC_DIRS = ("score", "detect", "imageio")
LOGIC_FILES = ("scan.py", "config.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def logic_hash() -> str:
    base = ROOT / "src" / "bcut"
    files = [p for d in LOGIC_DIRS for p in sorted((base / d).rglob("*.py"))]
    files += [base / f for f in LOGIC_FILES]
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(str(p.relative_to(base)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def names_hash(folder: Path) -> tuple[str, int]:
    names = sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".cr3")
    return sha("\n".join(names).encode()), len(names)


def current_state(folder: Path) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from bcut import __version__
    from bcut.config import Config

    cfg = Config()
    nh, n = names_hash(folder)
    return {
        "tool_version": __version__,
        "config_version": cfg.config_version,
        "reason_tiers": dict(cfg.reason_tiers),
        "thresholds": {"eyes": asdict(cfg.eyes), "exposure": asdict(cfg.exposure),
                       "sharpness": asdict(cfg.sharpness)},
        "logic_code_sha256": logic_hash(),
        "requirements_lock_sha256": sha((ROOT / "requirements-lock.txt").read_bytes()),
        "holdout_files": n,
        "holdout_names_sha256": nh,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("freeze", "verify"))
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--tests", default="", help="동결 시점의 테스트 결과 (예: '383 passed, 1 skipped')")
    args = ap.parse_args()
    state = current_state(args.folder)

    if args.mode == "freeze":
        if RECORD.exists():
            print(f"이미 동결 기록이 있다: {RECORD}. 다시 쓰지 않는다 (홀드아웃이 무효가 되므로).",
                  file=sys.stderr)
            return 2
        record = {
            "frozen_at": datetime.now().isoformat(timespec="seconds"),
            "tests_at_freeze": args.tests,
            "statement": "이 시점 이후 판정 로직(임계값, 규칙, 판정 코드)을 바꾸지 않는다. 바꾸면 이 "
                         "홀드아웃은 더 이상 홀드아웃이 아니다.",
            **state,
        }
        RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"동결 기록을 남겼다: {RECORD}")
        print(f"  홀드아웃 {state['holdout_files']}장, 판정 코드 해시 {state['logic_code_sha256'][:12]}…")
        return 0

    if not RECORD.exists():
        print("동결 기록이 없다. 먼저 freeze를 실행한다.", file=sys.stderr)
        return 2
    frozen = json.loads(RECORD.read_text(encoding="utf-8"))
    problems = [k for k in state if frozen.get(k) != state[k]]
    if problems:
        print("동결 이후 바뀐 것이 있다: " + ", ".join(problems), file=sys.stderr)
        return 1
    print(f"동결 이후 바뀐 것이 없다 (동결 {frozen['frozen_at']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
