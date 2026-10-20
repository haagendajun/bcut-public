"""Homebrew 파이썬을 앱 안으로 옮긴 뒤, 절대 경로(/opt/homebrew/...)로 연결된 라이브러리를
앱 안의 상대 경로로 바꾼다. 사용: python3 relocate_py.py <py 폴더>

py 폴더 모양: Python(핵심 라이브러리), bin/python3.13, lib/python3.13/...,
libs/*.dylib (함께 담은 것)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def deps(f: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(f)], capture_output=True, text=True).stdout
    lines = [ln for ln in out.splitlines() if ln.startswith("\t")]  # 첫 줄(파일 이름)은 제외
    return [ln.strip().rsplit(" (compatibility", 1)[0] for ln in lines]


def is_macho(f: Path) -> bool:
    if not f.is_file() or f.is_symlink():
        return False
    with f.open("rb") as fh:
        return fh.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")  # 64비트 Mach-O, 겹파일


def loader_path(frm: Path, to: Path) -> str:
    return "@loader_path/" + os.path.relpath(to, frm.parent)


def main(py: Path) -> None:
    libs = py / "libs"
    libs.mkdir(exist_ok=True)
    core = py / "Python"
    for _ in range(5):  # 담은 라이브러리가 또 다른 외부 라이브러리를 부르면 그것도 담는다
        for f in [x for x in py.rglob("*") if is_macho(x)]:
            for d in deps(f):
                if not d.startswith(("/opt/homebrew/", "/usr/local/")):
                    continue  # 시스템·상대 경로·바퀴 파일 자체 표시(/DLC/...)는 그대로 둔다
                name = Path(d).name
                if name == "Python":
                    target = core
                else:
                    target = libs / name
                    if not target.exists():
                        shutil.copy2(Path(d).resolve(), target)
                        target.chmod(0o755)
                subprocess.run(["install_name_tool", "-change", d, loader_path(f, target), str(f)],
                               check=True, capture_output=True)
    for f in [x for x in py.rglob("*") if is_macho(x)]:
        if f.parent == libs or f == core:  # 우리가 담은 라이브러리만 (바퀴 파일 것은 그대로)
            subprocess.run(["install_name_tool", "-id", "@loader_path/" + f.name, str(f)],
                           check=True, capture_output=True)
    left = [(f, d) for f in py.rglob("*") if is_macho(f) for d in deps(f)
            if d.startswith("/opt/") or d.startswith("/Users/")]
    if left:
        sys.exit(f"아직 절대 경로가 남아 있다: {left[:5]}")
    print("libs:", sorted(p.name for p in libs.iterdir()))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
