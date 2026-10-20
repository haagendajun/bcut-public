# 설치와 재설치 (T3.3)

대상: macOS, Python 3.13. 2026-10-19에 **새 가상환경에서 처음부터 설치해 확인했다**(테스트 368개 통과, 실제 행사 145장 스캔 결과가 기존 환경과 등급 0건 차이). iMac에는 아직 설치해 보지 않았다.

## 1. 준비물

| 항목 | 확인 방법 | 없으면 |
|---|---|---|
| Python 3.13 | `python3.13 --version` | Homebrew로 설치 (`brew install python@3.13`). 3.14는 라이브러리 호환을 확인하지 않았다 |
| Capture One 16.7.1 | 앱 정보 | `apply`·`albums`·`rollback`에만 필요. `scan`은 Capture One 없이 돈다 |
| macOS 자동화 권한 | 처음 `apply`를 실행할 때 팝업 | 팝업에서 허용. 놓쳤으면 시스템 설정 > 개인정보 보호 및 보안 > 자동화에서 터미널의 Capture One을 켠다 |

## 2. 설치

```bash
python3.13 -m venv ~/.venvs/photo-select
~/.venvs/photo-select/bin/pip install -r requirements-lock.txt
~/.venvs/photo-select/bin/pip install -c requirements-lock.txt -e ".[dev]"
~/.venvs/photo-select/bin/bcut --version
~/.venvs/photo-select/bin/pytest
```

- **가상환경은 `~/.venvs/`(홈 폴더)에 둔다.** 프로젝트 폴더나 바탕화면(iCloud 동기화)에 두면 iCloud가 파일에 숨김 표시를 붙여 설치가 망가진다 ([env.md](env.md)).
- `requirements-lock.txt`가 라이브러리 버전을 고정한다(numpy 2.5.4, Pillow 13.0.0, rawpy 0.27.1, pyobjc 12.2.2). 이 파일 없이 설치하면 최신 버전이 들어가 결과가 달라질 수 있다.
- 설치 직후 `pytest`가 모두 통과하는지 본다(1개는 Capture One 실기 전용이라 건너뛴다).

## 3. 사진·결과 보관 위치

- 사진과 카탈로그는 **iCloud 동기화가 안 되는 폴더**(예: `~/photo-select-data/`)에 둔다. 이 도구는 사진을 읽기만 하고, 사진·리포트가 네트워크로 나가지 않는다.
- `scan` 결과(`--out`)는 행사 폴더 **밖**에 둔다(안이면 거부한다).

## 4. 재설치 시나리오 (iMac 포함)

1. 프로젝트 폴더를 옮긴다(복사).
2. 위 2장을 그대로 따른다. 가상환경은 새로 만든다(옛 가상환경은 복사하지 않는다).
3. 확인: `bcut --version`, `pytest`, 그리고 **지난 행사 하나를 `scan`해서 이전 결과와 같은 등급이 나오는지** 비교한다.
4. Capture One 쪽은 카탈로그마다 [전용 키워드를 한 번 만든다](capture-one-setup.md) (카탈로그에 들어 있으므로 도구를 재설치해도 다시 만들 필요는 없다).

## 5. 지우기

가상환경 폴더(`~/.venvs/photo-select`)를 지우면 도구가 사라진다. 사진, 카탈로그, 결과 폴더는 건드리지 않는다. Capture One 카탈로그에 붙은 전용 키워드를 없애려면 `bcut rollback`을 쓴다.
