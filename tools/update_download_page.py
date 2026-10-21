"""다운로드 페이지(download/index.html)의 버전·링크·크기·SHA-256을 새 zip에 맞게 바꾼다.

사용: python tools/update_download_page.py 0.3.4 /경로/bcut-0.3.4-mac-arm64.zip
릴리스 올린 뒤 이것만 돌리면 손으로 고칠 곳이 없다. 페이지 배포는 따로(사용자 확인 후) 한다.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "download" / "index.html"
ZIP_NAME = "bcut-{v}-mac-arm64.zip"
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def update(html: str, version: str, sha: str, size_mb: int) -> str:
    html = re.sub(r"releases/download/v[\d.]+/bcut-[\d.]+-mac-arm64\.zip",
                  f"releases/download/v{version}/{ZIP_NAME.format(v=version)}", html)
    html = re.sub(r"v\d+\.\d+\.\d+ · Apple", f"v{version} · Apple", html)
    html = re.sub(r"bcut \d+\.\d+\.\d+ 다운로드", f"bcut {version} 다운로드", html)
    html = re.sub(r"약 \d+MB", f"약 {size_mb}MB", html)
    return re.sub(r"SHA-256 · [0-9a-f]{64}", f"SHA-256 · {sha}", html)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not VERSION_RE.fullmatch(argv[1]):
        print("사용: update_download_page.py <버전 예: 0.3.4> <zip 경로>")
        return 2
    zip_path = Path(argv[2])
    if not zip_path.is_file():
        print(f"zip 파일이 없다: {zip_path}")
        return 1
    size_mb = round(zip_path.stat().st_size / 1_000_000)
    html = PAGE.read_text(encoding="utf-8")
    PAGE.write_text(update(html, argv[1], sha256(zip_path), size_mb), encoding="utf-8")
    print(f"{PAGE.name}: v{argv[1]}, {size_mb}MB, SHA {sha256(zip_path)[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
