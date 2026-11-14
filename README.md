> **익명 처리한 복제본입니다.** bcut 원본 저장소(비공개)에서 개인·고객 정보를 익명 처리해 공개용으로 옮겼습니다. 바꾼 내용은 [ANONYMIZED.md](ANONYMIZED.md)에 있습니다.

# B컷 후보 사전 필터 (bcut)

포토팀 셀렉 담당자가 행사 사진에서 눈 감김, 흔들림, 초점 실패, 노출 문제를 걸러 내는 시간을 줄이는 로컬 도구. **사진은 이 컴퓨터 밖으로 나가지 않고, 도구는 사진을 삭제하지 않는다.**

문서: [PRD](PRD.md) · [IA](IA.md) · [유저 저니](uj.md) · [개발 계획](devplan.md) · [런북](docs/runbook.md) · [설치](docs/install.md) · [환경 기록](docs/env.md)

## 개발 환경

```bash
python3.13 -m venv ~/.venvs/photo-select
~/.venvs/photo-select/bin/pip install -e ".[dev]"
~/.venvs/photo-select/bin/pytest
~/.venvs/photo-select/bin/ruff check .
~/.venvs/photo-select/bin/bcut --help
```

Python은 3.13을 쓴다 (devplan D3 제안. 3.14는 라이브러리 호환이 확인되지 않음).

**가상환경을 프로젝트 안(`.venv`)에 두지 않는다.** 이 프로젝트가 있는 바탕화면은 iCloud Drive와 동기화된다. iCloud가 가상환경 안의 파일에 "숨김" 표시를 붙여서, 개발 모드 설치 파일(`.pth`)을 Python 3.13이 무시하고 `No module named 'bcut'` 오류가 났다. 동기화되지 않는 홈 폴더(`~/.venvs/`)에 둔다.

## 사용법 (눈 감김 판정 + HTML 리포트)

```bash
~/.venvs/photo-select/bin/bcut scan --folder "<행사 폴더>" --out "<결과 폴더>"
```

결과 폴더의 `bcut-report.html`을 열면 사진 썸네일과 함께 필터·정렬해서 볼 수 있다 ([자세히](docs/html-report.md)). 행사 폴더는 읽기만 하고, 결과 폴더가 행사 폴더 안이면 거부한다. **HTML에는 사진 썸네일이 들어 있으니 이 컴퓨터에서만 쓴다.**

## 폴더 정리 (Capture One 없이)

```bash
bcut scan --folder "<행사 폴더>" --out "<결과 폴더>"
bcut sort --folder "<행사 폴더>" --report "<결과 폴더>/bcut-report.csv" --out "<정리를 만들 폴더>"            # 미리보기
bcut sort --folder "<행사 폴더>" --report "<결과 폴더>/bcut-report.csv" --out "<정리를 만들 폴더>" --commit   # 만들기
```

`버릴 것 같은 컷`/`직접 확인`/`이상 없음`/`문제 종류별` 폴더로 **복제**한다(같은 디스크면 APFS 복제라 시간·공간이 거의 안 듦). 원본은 그대로이고, 실행마다 새 폴더가 생긴다. HTML 리포트에서 "살린 컷 이름 저장"으로 만든 파일을 `--rescue`로 주면 그 컷은 `이상 없음` 폴더로 간다. 계획: [docs/organizer-plan.md](docs/organizer-plan.md).

## 앱으로 쓰기

```bash
bash electron/build.sh     # ~/Applications/bcut.app 을 만든다 (약 15초, 코드를 고칠 때마다 다시)
open ~/Applications/bcut.app
```

앱을 열면 로컬 서버가 자동으로 뜨고(127.0.0.1에서만, 앱을 닫으면 종료) 사진 폴더를 창에 끌어다 놓거나 `⌘O`로 고른다. 처음 Desktop·문서·외장 드라이브의 폴더를 열면 macOS가 접근 허용을 물을 수 있다. 서명은 내 컴퓨터 전용(ad-hoc)이다.

## 화면으로 쓰기 (개발 중, 브라우저)

```bash
bcut serve        # 한 줄로 주소와 토큰을 출력하고 서버가 뜬다 (127.0.0.1에서만)
```

출력된 주소 뒤에 `?t=<토큰>`을 붙여 브라우저에서 연다(예: `http://127.0.0.1:54664/?t=...`). 폴더를 고르면 분석 → 1순위·2순위 순서로 확인(크게 보기, 남기기) → 폴더로 정리까지 화면에서 한다. 앱 아이콘으로 여는 형태는 S4(Electron 셸)에서 만든다.

## 구조

```
src/bcut/        # cli.py, config.py 와 imageio, detect, score, report, calibrate, bridge, store
tests/           # 단위 테스트, 안전 규칙 테스트
tools/           # 라벨 내보내기 스크립트 (Capture One 라벨 -> CSV)
eval/            # 라벨, 평가 결과
docs/            # 환경 기록, 라벨링 가이드, 평가 계획
```

## 지키는 규칙 (테스트로 확인)

- 네트워크 모듈을 import하지 않는다 (`tests/test_safety_rules.py`, 제약 C1). **예외는 로컬 서버 `ui/server.py` 하나뿐**이고, 그 파일도 `127.0.0.1`에만 열고 토큰을 요구하며 접속하는 쪽 코드를 쓰지 않는다(`tests/test_ui_server.py`)
- 삭제 호출을 쓰지 않는다 (같은 테스트, 제약 C3)
- 운영 등급: 눈 감김만 `candidate`, 흔들림·초점·노출은 `review` (`tests/test_config.py`, devplan 1-F)

## 상태

Phase 1 완료 (T1.1~T1.18, G1b 조건부 통과): (`bcut scan`과 HTML 리포트, 노출·흔들림·초점 판정 포함. `scan`, CSV, HTML 리포트에 눈 감김, 노출, 흔들림, 초점 실패가 사유별로 연결되어 있다) (읽기, 얼굴·눈 검출, 눈 감김 판정 규칙, 좁은 눈 판정 불가 규칙, 평가 하네스). **G1a 조건부 통과** ([보고서](docs/g1a-report.md)), **G1b 조건부 통과** ([보고서](docs/g1b-report.md)). 정책 결정: 오탐 허용 A 엄격(Q7), [단체 사진](docs/group-photo-policy.md). 평가는 `python eval/evaluate_eyes.py`. `bcut scan --config 설정.toml`로 사유별 등급과 임계값을 바꿀 수 있다 (T1.8 일부). `bcut calibrate --folder 행사 --labels 라벨.csv`로 눈 감김 경계를 보정해 설정 파일을 만든다 (T1.12). `bcut apply --folder 행사 --catalog 카탈로그이름 [--commit]`으로 후보·확인 컷에 전용 키워드를 붙인다(기본 dry-run, 키워드는 먼저 [직접 만들어야 함](docs/capture-one-setup.md), T2.4). `bcut albums --catalog 이름 --commit`으로 전용 스마트 앨범 7개를 만든다(T2.6). `bcut doctor [--catalog 이름]`으로 환경·연결을 점검하고(T3.6), `bcut rollback --folder 행사 --catalog 이름 [--commit]`으로 apply가 붙인 키워드만 떼어 되돌린다(T2.7, 사용자가 바꾼 값은 보존).
