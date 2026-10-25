# 오픈소스 라이선스 고지 (Third-Party Notices)

bcut(사진 셀렉 앱)은 아래 오픈소스를 **그대로** 사용하거나 앱 안에 함께 담아 배포합니다.
각 항목의 라이선스 전문은 [licenses/](licenses/) 폴더에 있습니다.

- bcut 자체 코드는 이 고지의 대상이 아닙니다.
- bcut은 **Capture One, Apple, Adobe 등 어떤 회사와도 제휴·후원 관계가 없는 개인 도구**입니다. 제품 이름은 각 회사의 상표이며, 연동 기능을 설명하는 데만 씁니다.
- 작성 기준: 앱 버전 0.3.6, 2026-10-26. 목록은 `requirements-lock.txt`, `electron/build_dist.sh`(배포용 조립), 배포용 앱 폴더를 직접 열어 확인했습니다.

## 1. 배포용 앱에 함께 담기는 것

| 구성 요소 | 버전 | 라이선스 | 하는 일 | 전문 |
|---|---|---|---|---|
| Electron | 44.7.0 | MIT | 앱 창을 띄우는 틀 | [Electron-MIT.txt](licenses/Electron-MIT.txt) |
| Chromium 등 Electron 안의 묶음 | (Electron에 포함) | 여러 개 (BSD, MIT 등) | 화면을 그리는 엔진 | 아래 3장 참고 |
| Python | 3.13.15 | PSF License 2.0 | 판정·서버 코드를 실행 | [Python-PSF.txt](licenses/Python-PSF.txt) |
| numpy | 2.5.4 | BSD-3-Clause 외 (0BSD, MIT, Zlib, CC0-1.0) | 숫자 계산 | [numpy.txt](licenses/numpy.txt) |
| Pillow | 13.0.0 | MIT-CMU | 사진 읽기·축소 | [Pillow.txt](licenses/Pillow.txt) |
| rawpy | 0.27.1 | MIT | RAW 사진 읽기(LibRaw 연결) | [rawpy-MIT.txt](licenses/rawpy-MIT.txt) |
| **LibRaw** (rawpy 안에 포함) | rawpy 0.27.1에 포함 (`libraw_r.25.dylib`, 정확한 LibRaw 버전은 미확인) | **LGPL-2.1** | RAW 파일 해석 | [LibRaw-LGPL-2.1.txt](licenses/LibRaw-LGPL-2.1.txt) |
| PyObjC (core, Cocoa, CoreML, Quartz, Vision) | 12.2.2 | MIT | 파이썬에서 Apple 얼굴 인식(Vision) 부르기 | [PyObjC-MIT.txt](licenses/PyObjC-MIT.txt) |
| OpenSSL (`libssl.3`, `libcrypto.3`) | 3.6.4 (Homebrew에서 복사) | Apache-2.0 | 파이썬의 암호 통신 | [OpenSSL-Apache-2.0.txt](licenses/OpenSSL-Apache-2.0.txt) |
| libmpdec (`libmpdec.4`) | 4.0.1 (Homebrew에서 복사) | BSD-2-Clause | 파이썬의 정밀 소수 계산 | [libmpdec-BSD-2.txt](licenses/libmpdec-BSD-2.txt) |
| liblzma / xz (`liblzma.5`) | 5.8.4 (Homebrew에서 복사) | 0BSD (liblzma) | 압축 풀기 | [xz-0BSD.txt](licenses/xz-0BSD.txt), [xz-COPYING.txt](licenses/xz-COPYING.txt) |
| SQLite (`libsqlite3`) | 3.53.4 (Homebrew에서 복사) | 퍼블릭 도메인 | 기록 저장 | 없음(저작권 없음, https://www.sqlite.org/copyright.html) |
| Pretendard 글꼴 | 변형 글꼴 (woff2) | SIL OFL 1.1 | 화면 글씨 | [Pretendard-OFL-1.1.txt](licenses/Pretendard-OFL-1.1.txt) |

Pillow 안에 묶여 있는 라이브러리(FreeType, HarfBuzz, libjpeg, libpng, libtiff, libwebp, OpenJPEG, LittleCMS, zlib 등)의 라이선스는 [Pillow.txt](licenses/Pillow.txt) 안에 함께 들어 있습니다. numpy 안에 묶인 라이브러리(libdivide, Highway 등)는 [numpy.txt](licenses/numpy.txt)에 있습니다.

## 2. 전문 파일 출처

- Pretendard: https://github.com/orioncactus/pretendard 의 LICENSE (Pretendard, Source Han Sans, Inter, M PLUS 1의 저작권 문구와 OFL 1.1 본문 포함, 2026-10-26에 받음)
- OpenSSL·libmpdec·xz: 이 컴퓨터의 Homebrew 설치 폴더에 있던 파일을 복사 (앱에 담기는 것과 같은 버전)
- 나머지: 설치된 파이썬 패키지의 `dist-info/licenses`, Electron 받은 폴더, Homebrew Python의 `LICENSE.txt`를 복사
- 정확한 LibRaw 버전은 아직 확인하지 못했습니다.

## 3. 앱에 아직 같이 담기지 않는 것 (확인된 빈틈)

2026-10-26에 빌드 스크립트와 배포용 앱 폴더를 확인한 결과입니다.

1. **Electron의 `LICENSE`와 `LICENSES.chromium.html`(약 20MB)**: Electron을 받은 폴더에는 있지만, `build_dist.sh`가 `Electron.app`만 복사해서 **앱 안에는 없습니다.** Chromium 등의 라이선스 문구를 함께 배포하라는 조건을 채우려면 앱 안(예: `Contents/Resources/`)에 넣어야 합니다.
2. **이 `licenses/` 폴더 전체**: 배포용 앱은 numpy, PIL, rawpy 등 **패키지 폴더만** 복사해서, 각 패키지의 `dist-info/licenses`가 따라오지 않습니다. 이 파일과 `licenses/`를 앱 안에도 넣어야 합니다.
3. **LibRaw(LGPL-2.1) 조건**: LibRaw는 별도 파일(`libraw_r.*.dylib`)로 연결되어 있어 사용자가 같은 이름의 다른 버전으로 바꿔 끼울 수 있습니다. 이 점과 아래 소스 위치를 사용자에게 알려야 합니다.
   - LibRaw 소스: https://www.libraw.org / https://github.com/LibRaw/LibRaw
   - rawpy 소스: https://github.com/letmaik/rawpy
   - 앱 소개 페이지에 "LibRaw(LGPL-2.1)를 사용하며 이 라이브러리 파일은 교체할 수 있다"는 안내를 넣는 것을 권합니다.
4. **개발용 도구**: `build.sh`(내 컴퓨터용 앱)는 개발용 가상환경 전체를 복사해서 pytest, ruff, pip, pygments 등이 따라옵니다. 이들의 라이선스(MIT, BSD, Apache 등)도 해당합니다. **나눠 주는 `build_dist.sh`는 필요한 것만 골라 담아서 이 도구들이 들어가지 않습니다.**

## 4. 앱이 쓰지만 함께 배포하지 않는 것

- Apple Vision, CoreML, AppKit 등 macOS 기본 기능: 사용자의 Mac에 이미 있는 것을 부르기만 합니다.
- Capture One: 사용자가 따로 설치한 프로그램을 AppleScript로 제어합니다. bcut에는 포함되어 있지 않습니다.

## 5. 이 문서를 고치는 때

라이브러리 버전을 올리거나 새로 추가하면, 이 표와 `licenses/` 폴더를 같이 고칩니다. 새 라이브러리는 먼저 사용자에게 묻고(프로젝트 규칙), 라이선스가 **GPL·AGPL**이면 앱 전체에 공개 의무가 번질 수 있으니 쓰지 않습니다.
