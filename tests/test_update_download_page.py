"""다운로드 페이지 갱신 스크립트: 버전·링크·크기·SHA가 한 번에 바뀐다."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "update_download_page", Path(__file__).parent.parent / "tools" / "update_download_page.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

HTML = (
    '<a href="https://github.com/o/r/releases/download/v0.3.3/bcut-0.3.3-mac-arm64.zip">x</a>'
    '<p>v0.3.3 · Apple 칩</p><h2>bcut 0.3.3 다운로드</h2><p>약 160MB</p>'
    f'<code>SHA-256 · {"a" * 64}</code>'
)


def test_update_changes_every_spot() -> None:
    out = mod.update(HTML, "0.4.0", "b" * 64, 170)
    assert "v0.4.0/bcut-0.4.0-mac-arm64.zip" in out
    assert "v0.4.0 · Apple" in out and "bcut 0.4.0 다운로드" in out
    assert "약 170MB" in out and "SHA-256 · " + "b" * 64 in out
    assert "0.3.3" not in out and "a" * 64 not in out


def test_real_page_has_all_spots() -> None:
    html = mod.PAGE.read_text(encoding="utf-8")
    assert mod.update(html, "9.9.9", "c" * 64, 1) != html
