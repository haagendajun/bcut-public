"""Electron 껍데기(electron/)의 보안 설정과 빌드 스크립트를 검사한다. Electron을 실제로 띄우지는 않는다."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EL = Path(__file__).resolve().parents[1] / "electron"
MAIN = (EL / "main.js").read_text(encoding="utf-8")
PRELOAD = (EL / "preload.js").read_text(encoding="utf-8")
BUILD = (EL / "build.sh").read_text(encoding="utf-8")


def test_window_is_isolated():
    assert "contextIsolation: true" in MAIN and "nodeIntegration: false" in MAIN
    assert "sandbox: true" in MAIN
    assert "nodeIntegration: true" not in MAIN and "contextIsolation: false" not in MAIN
    assert "webviewTag" not in MAIN or "webviewTag: false" in MAIN


def test_all_requests_outside_the_local_server_are_cancelled():
    assert "onBeforeRequest" in MAIN and "cancel: !ok" in MAIN
    assert "u.startsWith(base + '/')" in MAIN
    # 외부 주소로 나가는 일을 하지 않는다: 외부 열기, 외부 주소 문자열 없음
    assert "openExternal" not in MAIN
    assert not re.findall(r"https?://(?!127\.0\.0\.1)", MAIN)
    assert "setPermissionRequestHandler" in MAIN and "cb(false)" in MAIN
    assert "setWindowOpenHandler" in MAIN and "action: 'deny'" in MAIN
    assert "will-navigate" in MAIN and "will-attach-webview" in MAIN


def test_server_is_started_on_loopback_with_a_random_token():
    assert "crypto.randomBytes(16)" in MAIN and "BCUT_TOKEN" in MAIN
    assert "127.0.0.1" in MAIN and "0.0.0.0" not in MAIN
    assert "['serve','--port'" in MAIN.replace(" ", "")
    assert "stopServer" in MAIN and "SIGINT" in MAIN  # 앱을 닫으면 서버도 끝낸다


def test_preload_exposes_only_three_small_functions():
    assert "contextBridge.exposeInMainWorld('bcutShell'" in PRELOAD
    for name in ("pathForFile", "chooseFolder", "onOpenFolder"):
        assert name in PRELOAD
    assert "require('child_process')" not in PRELOAD and "require('fs')" not in PRELOAD
    assert PRELOAD.count("ipcRenderer.invoke") == 1  # 화면이 부를 수 있는 명령은 폴더 선택 하나


def test_cmd_z_is_handled_by_our_menu_item_not_the_default_undo():
    main = (EL / "main.js").read_text(encoding="utf-8")
    assert "role: 'undo'" not in main  # 기본 실행 취소가 ⌘Z를 가로채지 않게 한다
    assert "accelerator: 'CmdOrCtrl+Z'" in main and "bcut-undo" in main
    assert main.count("executeJavaScript(") == 1 and "executeJavaScript(UNDO_PROBE)" in main  # 고정 문장만
    app = (EL.parent / "src" / "bcut" / "ui" / "web" / "app.js").read_text(encoding="utf-8")
    assert "addEventListener('bcut-undo'" in app


def test_package_json():
    pkg = json.loads((EL / "package.json").read_text(encoding="utf-8"))
    assert pkg["main"] == "main.js" and pkg["private"] is True and pkg["productName"] == "bcut"


def test_build_script_rules():
    assert BUILD.startswith("#!/bin/bash") and "set -euo pipefail" in BUILD
    out = subprocess.run(["bash", "-n", str(EL / "build.sh")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert '$HOME/Applications/$NAME.app' in BUILD  # iCloud인 Desktop이 아니라 ~/Applications
    assert "__editable__" in BUILD  # 개발 모드 표시를 지우고 복사해서 Desktop을 읽지 않게 한다
    assert 'case "$WHERE" in "$RUNTIME"/*' in BUILD  # 실행 환경 안에서 불러와지는지 검사
    assert "codesign --verify --deep --strict" in BUILD
    assert "SHASUMS256" in BUILD  # 내려받을 때는 체크섬 확인


@pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript 없음")
@pytest.mark.parametrize("name", ["main.js", "preload.js"])
def test_scripts_parse(name, tmp_path):
    src = (EL / name).read_text(encoding="utf-8")
    (tmp_path / "x.js").write_text(
        "var src = " + json.dumps(src) + "; var ok = true; try { new Function(src); } catch (e) { ok = String(e); } ok;",
        encoding="utf-8")
    out = subprocess.run(["osascript", "-l", "JavaScript", str(tmp_path / "x.js")],
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "true", out.stdout + out.stderr


def test_app_js_connects_to_the_shell():
    app = (EL.parent / "src" / "bcut" / "ui" / "web" / "app.js").read_text(encoding="utf-8")
    for token in ("bcutShell.chooseFolder", "bcutShell.onOpenFolder", "bcutShell.pathForFile"):
        assert token in app
