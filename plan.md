# plan: Capture One에도 표시하기 (S6)

어떻게. 요구는 [spec.md](spec.md). 이전 작업: [docs/features/cloud-upload/plan.md](docs/features/cloud-upload/plan.md).

## 1. 기술과 버전
파이썬 3.13.15. **기존 코드 재사용(수정 없음):** `bcut.apply.run_apply`(키워드 붙이기·백업·검증), `bcut.rollback.run_rollback`, `bcut.bridge.capture_one.CaptureOneBridge`(AppleScript, `osascript`). 새 라이브러리 없음. 한글 인자는 `osascript`가 그대로 전달함을 확인(`bcut-셀렉` 왕복).

## 2. 구조와 파일
| 파일 | 역할 |
|---|---|
| `ui/capture.py` (새) | `KEYWORDS`(pick→`bcut-셀렉`, maybe→`bcut-보류`, discard→`bcut-버릴컷`), `build_plan`(표시 → `파일 → [키워드]`), `handle`(요청 → 미리보기·반영·되돌리기 → 쉬운 JSON). 창구는 주입 가능 |
| `ui/server.py` | `POST /api/jobs/<job>/capture-one {catalog, action: preview|apply|rollback}` 한 길만 추가, `ServerConfig.capture_bridge`(시험용) |
| `ui/web/capture_view.js` (새) | 창: 카탈로그 입력 → 미리보기 → 반영 → 되돌리기, 결과 문장 |
| `ui/web/sort_view.js` | 나누어 담기 창에 "Capture One에도 표시하기…" 버튼 |
백업 위치: `<data-dir>/capture-one/<행사 키>/bcut-backup.json`, 카탈로그 백업은 같은 폴더의 `catalog-backups/`.

## 3. 단계
1. `capture.py` + 서버 길 + 시험. 2. 화면. 3. 문서·QA.

## 4. 테스트
가짜 창구(변형·키워드 목록을 메모리로 흉내)로 `test_capture_mark.py`: 계획 변환, 미리보기가 쓰기 호출 0건, 반영, 재반영 0건, 되돌리기, 키워드 없음 중단, 카탈로그 불일치, 별점·태그 불변, 파일 이름 겹침. `test_ui_server.py`에 길 시험. 실제 Capture One은 사람 QA(`bcut-test` 카탈로그).

## 5. 제약·위험
| 위험 | 대응 |
|---|---|
| 한글 키워드가 Capture One에서 안 통함 | 사람 QA에서 확인, 안 되면 `KEYWORDS`만 영문으로 |
| 실제 작업 카탈로그를 건드림 | 카탈로그 이름을 입력받고, 미리보기가 기본, 반영은 확인 후 |
| 오래 걸리는 AppleScript | 기존 청크(200장)·시간 제한 사용, 화면에 진행 문구 |
