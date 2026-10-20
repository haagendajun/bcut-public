#!/bin/bash
# 나눠 주기용 bcut.app 조립 (파이썬까지 앱 안에 담는다). 사용: bash electron/build_dist.sh
# 결과: ~/Library/Caches/bcut/dist/bcut.app 과 bcut-<버전>-mac-arm64.zip  (내 ~/Applications 앱은 건드리지 않는다)
# - Electron은 build.sh가 받아 둔 캐시를 쓴다 (없으면 먼저 build.sh를 한 번 실행).
# - 파이썬은 Homebrew 것을 복사하고 외부 라이브러리 연결을 앱 안 상대 경로로 바꾼다 (relocate_py.py).
# - 애플 서명·공증은 없다(ad-hoc 서명). 받은 맥은 처음에 "열기 허용"이 필요하다.
set -euo pipefail

VERSION="44.7.0"; NAME="bcut"; BUNDLE_ID="local.bcut.app"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
VENV_SRC="${BCUT_VENV:-$HOME/.venvs/photo-select}"
CACHE="${BCUT_ELECTRON_CACHE:-$HOME/Library/Caches/bcut/electron-v$VERSION}"
# iCloud 동기화 폴더(Desktop) 밖에서 조립한다: 안에서 하면 서명이 나중에 깨진다
OUT="${BCUT_DIST_DIR:-$HOME/Library/Caches/bcut/dist}"; APP="$OUT/$NAME.app"
PYV="3.13"
PYHOME="$("$VENV_SRC/bin/python" -c 'import sys; print(sys.base_prefix)')"
[ -d "$CACHE/unpacked/Electron.app" ] || { echo "Electron 캐시가 없습니다. 먼저 bash electron/build.sh" >&2; exit 1; }
[ -d "$PYHOME/lib/python$PYV" ] || { echo "파이썬 폴더를 찾지 못했습니다: $PYHOME" >&2; exit 1; }
BCUT_VER="$("$VENV_SRC/bin/python" -c 'import bcut; print(bcut.__version__)')"

rm -rf "$APP"; mkdir -p "$OUT"
ditto --norsrc --noextattr "$CACHE/unpacked/Electron.app" "$APP"
RES="$APP/Contents/Resources"
rm -f "$RES/default_app.asar"; mkdir -p "$RES/app" "$RES/py/bin" "$RES/py/lib"
cp "$HERE/main.js" "$HERE/preload.js" "$HERE/package.json" "$RES/app/"
echo '{ "python": "../py/bin/python3.13" }' > "$RES/app/config.json"

echo "▸ 파이썬 복사·재배치"
PY="$RES/py"
rsync -a "$PYHOME/Resources/" "$PY/Resources/"; rm -f "$PY/Resources/Info.plist"  # 이 파일이 있으면 서명 도구가 폴더 전체를 꾸러미로 봐서 서로의 서명을 깨뜨린다
cp "$PYHOME/Python" "$PY/Python"; cp "$PYHOME/bin/python$PYV" "$PY/bin/python$PYV"
rsync -a --exclude "__pycache__" --exclude "test" --exclude "tests" --exclude "idlelib" \
  --exclude "tkinter" --exclude "turtledemo" --exclude "ensurepip" --exclude "site-packages" \
  "$PYHOME/lib/python$PYV/" "$PY/lib/python$PYV/"
SP="$PY/lib/python$PYV/site-packages"; mkdir -p "$SP"
for pkg in numpy PIL rawpy objc AppKit Cocoa CoreFoundation CoreML Foundation Quartz Vision PyObjCTools \
           numpy.libs pillow.libs rawpy.libs; do
  [ -e "$VENV_SRC/lib/python$PYV/site-packages/$pkg" ] && \
    rsync -a --exclude "__pycache__" --exclude "tests" "$VENV_SRC/lib/python$PYV/site-packages/$pkg" "$SP/"
done
rsync -a --exclude "__pycache__" "$ROOT/src/bcut/" "$SP/bcut/"
python3 "$HERE/relocate_py.py" "$PY"
echo "▸ 고친 파일 다시 서명 (고치면 서명이 깨져 실행 즉시 종료된다)"
# 파이썬 안에서 부르면 서명이 맞지 않는 일이 있어, 폴더 안에서 상대 경로로 하나씩 서명한다
( cd "$PY" && for f in Python "bin/python$PYV" libs/*.dylib "lib/python$PYV"/lib-dynload/*.so; do
    codesign --force --sign - "$f" 2>&1 | grep -v "replacing existing" || true
  done
  codesign --force --deep --sign - Resources/Python.app 2>&1 | grep -v "replacing existing" || true )
echo "▸ 인증서 목록 담기 (시스템 루트 인증서)"
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > "$RES/app/cacert.pem"

echo "▸ 담은 파이썬으로 실행 확인"
"$PY/bin/python$PYV" -I -c "
import sys, ssl, sqlite3, lzma, decimal, numpy, PIL, rawpy, objc, Vision, bcut.ui.server, bcut.cli
assert sys.prefix.startswith('$PY'), sys.prefix
print('ok', sys.version.split()[0])"

echo "▸ 아이콘·정보"
TMP="$(mktemp -d)"
"$VENV_SRC/bin/python" "$HERE/make_icon.py" "$TMP/icon.png"; mkdir "$TMP/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/icon.iconset" -o "$RES/bcut.icns"; rm -f "$RES/electron.icns"; rm -rf "$TMP"
PLIST="$APP/Contents/Info.plist"; pb() { /usr/libexec/PlistBuddy -c "$1" "$PLIST"; }
pb "Set :CFBundleName $NAME"; pb "Set :CFBundleDisplayName $NAME"; pb "Set :CFBundleIdentifier $BUNDLE_ID"
pb "Set :CFBundleIconFile bcut"; pb "Set :CFBundleShortVersionString $BCUT_VER"; pb "Set :CFBundleVersion $BCUT_VER"
pb "Delete :ElectronAsarIntegrity" 2>/dev/null || true

xattr -cr "$APP"
codesign --force --deep --sign - "$APP" 2>&1 | grep -v "replacing existing signature" || true
codesign --verify --deep --strict "$APP"
ZIP="$OUT/$NAME-$BCUT_VER-mac-arm64.zip"; rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "▸ 완료: $ZIP ($(du -h "$ZIP" | awk '{print $1}'))"
shasum -a 256 "$ZIP"
