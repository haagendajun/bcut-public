#!/bin/bash
# bcut.app 조립 스크립트 (Nook의 build.sh와 같은 방식: Node/npm 없이 Electron 공식 배포본만 사용, Apple Silicon)
#   사용: bash electron/build.sh        결과: ~/Applications/bcut.app
#
# - 앱이 쓰는 파이썬 환경은 ~/Library/Application Support/bcut/runtime 에 **복사**해서 쓴다. 프로젝트가 있는
#   Desktop은 iCloud 동기화 폴더라, 앱이 그 안을 직접 읽으면 macOS 폴더 접근 허용 창이 뜨고 서명도 실패한다.
# - 개발용 가상환경(~/.venvs/photo-select)을 복사한 뒤 **개발 모드 설치(editable) 표시를 지우고**
#   `src/bcut`을 그대로 복사해 넣는다 (그래야 Desktop을 읽지 않는다).
# - Electron 배포본은 ~/Library/Caches/bcut/ 에 둔다 (iCloud 밖). 없으면 Nook 폴더의 캐시를 복제하고,
#   그것도 없으면 공식 배포본을 받아 체크섬을 확인한다 (빌드할 때만 네트워크를 쓴다).
set -euo pipefail

VERSION="44.7.0"
ARCH="darwin-arm64"
NAME="bcut"
BUNDLE_ID="local.bcut.app"

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
VENV_SRC="${BCUT_VENV:-$HOME/.venvs/photo-select}"
APP="$HOME/Applications/$NAME.app"
CACHE="${BCUT_ELECTRON_CACHE:-$HOME/Library/Caches/bcut/electron-v$VERSION}"
NOOK_CACHE="$HOME/Desktop/LS JUMP UP/Day5/Nook/cutout-app/.cache/electron-v$VERSION"
BASE_URL="https://github.com/electron/electron/releases/download/v$VERSION"
RUNTIME="$HOME/Library/Application Support/$NAME/runtime"

[ "$(uname -m)" = "arm64" ] || { echo "Apple Silicon(arm64) 전용입니다." >&2; exit 1; }
[ -x "$VENV_SRC/bin/python" ] || { echo "파이썬 환경이 없습니다: $VENV_SRC (docs/install.md)" >&2; exit 1; }
"$VENV_SRC/bin/python" -c "import PIL, numpy, rawpy" || { echo "라이브러리가 설치되어 있지 않습니다 (docs/install.md)" >&2; exit 1; }

# 1) Electron 확보
if [ ! -d "$CACHE/unpacked/Electron.app" ]; then
  mkdir -p "$(dirname "$CACHE")"
  if [ -d "$NOOK_CACHE/unpacked/Electron.app" ]; then
    echo "▸ Nook의 Electron 캐시를 복제 (같은 디스크라 공간이 거의 안 듭니다)"
    cp -c -R "$NOOK_CACHE" "$CACHE"
  else
    ZIP="$CACHE/electron-v$VERSION-$ARCH.zip"; mkdir -p "$CACHE"
    echo "▸ Electron v$VERSION 다운로드 (약 130MB)"
    curl -L --fail --progress-bar -o "$ZIP" "$BASE_URL/electron-v$VERSION-$ARCH.zip"
    curl -sL --fail -o "$CACHE/SHASUMS256.txt" "$BASE_URL/SHASUMS256.txt"
    EXPECTED="$(grep " \*\?electron-v$VERSION-$ARCH.zip\$" "$CACHE/SHASUMS256.txt" | awk '{print $1}')"
    ACTUAL="$(shasum -a 256 "$ZIP" | awk '{print $1}')"
    [ -n "$EXPECTED" ] && [ "$EXPECTED" = "$ACTUAL" ] || { echo "체크섬 불일치" >&2; exit 1; }
    unzip -q "$ZIP" -d "$CACHE/unpacked"
  fi
fi
UNPACKED="$CACHE/unpacked"
echo "▸ Electron 사용: $UNPACKED"

# 2) 앱 복제 (이미 있으면 새로 만든다)
rm -rf "$APP"; mkdir -p "$HOME/Applications"
ditto --norsrc --noextattr "$UNPACKED/Electron.app" "$APP"

# 3) 앱 코드
RES="$APP/Contents/Resources"
rm -f "$RES/default_app.asar"; mkdir -p "$RES/app"
cp "$HERE/main.js" "$HERE/preload.js" "$HERE/package.json" "$RES/app/"

# 4) 실행 환경 (venv 복사 + 개발 모드 표시 제거 + 앱 코드 복사)
echo "▸ 실행 환경 복사"
mkdir -p "$RUNTIME"
rsync -a --delete --exclude "__pycache__" "$VENV_SRC/" "$RUNTIME/venv/"
SP="$(ls -d "$RUNTIME"/venv/lib/python3.*/site-packages | head -1)"
rm -f "$SP"/__editable__.bcut-*.pth "$SP"/__editable___bcut_*_finder.py
rm -rf "$SP"/bcut-*.dist-info
rsync -a --delete --exclude "__pycache__" "$ROOT/src/bcut/" "$SP/bcut/"
WHERE="$("$RUNTIME/venv/bin/python" -c "import bcut; print(bcut.__file__)")"
case "$WHERE" in "$RUNTIME"/*) ;; *) echo "bcut가 실행 환경 안에서 불러와지지 않습니다: $WHERE" >&2; exit 1;; esac
"$RUNTIME/venv/bin/python" -c "import bcut.ui.server, bcut.cli" || { echo "앱 코드를 불러오지 못했습니다" >&2; exit 1; }
cat > "$RES/app/config.json" <<EOT
{ "python": "$RUNTIME/venv/bin/python" }
EOT

# 5) 아이콘
TMP="$(mktemp -d)"
"$VENV_SRC/bin/python" "$HERE/make_icon.py" "$TMP/icon.png"
mkdir "$TMP/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/icon.iconset" -o "$RES/bcut.icns"
rm -f "$RES/electron.icns"; rm -rf "$TMP"

# 6) Info.plist
PLIST="$APP/Contents/Info.plist"
pb() { /usr/libexec/PlistBuddy -c "$1" "$PLIST"; }
pb "Set :CFBundleName $NAME"
pb "Set :CFBundleDisplayName $NAME"
pb "Set :CFBundleIdentifier $BUNDLE_ID"
pb "Set :CFBundleIconFile bcut"
pb "Set :CFBundleShortVersionString 0.1.0"
pb "Set :CFBundleVersion 0.1.0"
pb "Delete :ElectronAsarIntegrity" 2>/dev/null || true

# 7) 수정했으므로 ad-hoc 재서명 (내 컴퓨터에서 실행하는 용도)
xattr -cr "$APP"
codesign --force --deep --sign - "$APP" 2>&1 | grep -v "replacing existing signature" || true
codesign --verify --deep --strict "$APP"
echo "▸ 완료: $APP"
