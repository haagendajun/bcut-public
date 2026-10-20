# plan: 기록 관리 화면 (S7)

어떻게. 요구는 [spec.md](spec.md). 이전 작업: [docs/features/capture-one/plan.md](docs/features/capture-one/plan.md).

## 1. 기술과 버전
파이썬 3.13.15 표준 라이브러리만(`pathlib`, `json`, `os.replace`). 새 라이브러리·네트워크 없음.

## 2. 구조와 파일
| 파일 | 역할 |
|---|---|
| `ui/records.py` (새) | `list_records(data_dir)`: 행사별 카드(표시 수·훑기·올림 상태·Capture One 기록), `clear_marks`, `move_to_trash`, `list_trash`, `restore`. 경로 검사 `_safe` |
| `ui/marks.py` | `MarkStore.clear_all(event)`: 활성 표시마다 취소 줄을 한 번에 덧붙임 |
| `ui/server.py` | `GET /api/records`, `POST /api/records/clear-marks|trash|restore` |
| `ui/web/records_view.js` (새) | 기록 관리 창: 행사 카드, 두 번 눌러 확인, 지운 기록 섹션 |
휴지통: `<data-dir>/trash/<시각>__<종류>__<이름>/`에 원래 폴더째 `os.replace`로 옮기고 `trash.json`에 원래 위치를 적는다. 복원은 원래 위치가 비어 있을 때만.

## 3. 단계
1. `records.py`+`clear_all`+서버 길+시험. 2. 화면. 3. 문서·QA·앱 빌드.

## 4. 테스트
`test_records.py`: 목록 값, 해제(취소 줄 보존, 활성 0), 휴지통 이동·복원, 이름 보호(`..`, `/`), 복원 충돌, 삭제 호출 0건(기존 안전 시험). `test_ui_server.py`: 길과 토큰.

## 5. 제약·위험
| 위험 | 대응 |
|---|---|
| 경로 조작으로 data_dir 밖을 옮김 | 이름 검증 + resolve 후 data_dir 안인지 확인 |
| 되돌리기 기록을 지워 Capture One 되돌리기 불가 | 지우기 전에 화면에서 경고, 휴지통에서 복원 가능 |
| 클라우드 상태 파일(`cloud.json`)과 어긋남 | 올린 줄 id는 그대로라 복원하면 다시 맞음, 해제는 취소 줄로 올라감 |
