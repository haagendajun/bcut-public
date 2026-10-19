# B컷 후보 사전 필터 (bcut)

포토팀 셀렉 담당자가 행사 사진에서 눈 감김, 흔들림, 초점 실패, 노출 문제를 걸러 내는 시간을 줄이는 로컬 도구. **사진은 이 컴퓨터 밖으로 나가지 않고, 도구는 사진을 삭제하지 않는다.**

문서: [PRD](PRD.md) · [IA](IA.md) · [유저 저니](uj.md) · [개발 계획](devplan.md) · [환경 기록](docs/env.md)

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

## 구조

```
src/bcut/        # cli.py, config.py 와 imageio, detect, score, report, calibrate, bridge, store
tests/           # 단위 테스트, 안전 규칙 테스트
tools/           # 라벨 내보내기 스크립트 (Capture One 라벨 -> CSV)
eval/            # 라벨, 평가 결과
docs/            # 환경 기록, 라벨링 가이드, 평가 계획
```

## 지키는 규칙 (테스트로 확인)

- 네트워크 모듈을 import하지 않는다 (`tests/test_safety_rules.py`, 제약 C1)
- 삭제 호출을 쓰지 않는다 (같은 테스트, 제약 C3)
- 운영 등급: 눈 감김만 `candidate`, 흔들림·초점·노출은 `review` (`tests/test_config.py`, devplan 1-F)

## 상태

Phase 1 진행 중: T1.1~T1.5, T1.10, T1.13, T1.17, T1.18 완료 (`bcut scan`과 HTML 리포트, 노출 판정 포함. `scan`, CSV, HTML 리포트에 눈 감김과 노출이 사유별로 연결되어 있다) (읽기, 얼굴·눈 검출, 눈 감김 판정 규칙, 좁은 눈 판정 불가 규칙, 평가 하네스). **G1a 조건부 통과** ([보고서](docs/g1a-report.md)). 정책 결정: 오탐 허용 A 엄격(Q7), [단체 사진](docs/group-photo-policy.md). 평가는 `python eval/evaluate_eyes.py`. `calibrate`, `apply`, `rollback` 명령은 아직 구현되지 않았다.
