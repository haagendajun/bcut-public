# plan: 로컬 기록 클라우드 올리기 (S5-B)

어떻게. 요구는 [spec.md](spec.md). 이전 작업의 plan은 [docs/features/select-mode/plan.md](docs/features/select-mode/plan.md).

## 1. 기술과 버전

파이썬 3.13.15 표준 `urllib.request`·`json`·`subprocess`(키체인 `security` 명령). **새 라이브러리 없음.** 슈파베이스 REST: 로그인 `POST /auth/v1/token?grant_type=password|refresh_token`, 올리기 PostgREST (`/rest/v1/<표>`). 열쇠는 공개용(`sb_publishable_…`)이며 코드에 둘 수 있다(비밀 아님). 서비스·비밀 열쇠는 쓰지 않는다.

## 2. 구조와 파일

| 파일 | 역할 | 규칙 |
|---|---|---|
| `ui/cloud_plan.py` | **순수 규칙**: 로컬 줄 → 올릴 행, 이미 올린 것 제외, 시간순 정렬 | 네트워크 없음 |
| `ui/cloud.py` | 통신: 로그인·갱신·올리기, 허용 주소 `https://*.supabase.co` 하나, 시간 제한 10초 | **네트워크 쓰는 유일한 파일**(안전 시험 예외) |
| `ui/cloud_state.py` | `cloud.json`(동의 시각·올린 줄 id), 키체인 읽기·쓰기 | 비밀번호 저장 금지 |
| `ui/cloud_sync.py` | 행사 한 곳을 올리는 순서(행사→사진→취소→표시→훑기 기록) | 통신은 받은 client가 함 |
| `ui/cloud_service.py` | 동의·로그인·올리기·상태, 서버가 부르는 `handle` | 실패는 상태 글자로만 |
| `ui/server.py` | `GET /api/cloud/status`, `POST consent·login·logout·sync` | 요청이 동의·로그인을 확인 |
| `ui/web/cloud_view.js` | 상태 칩, 로그인·동의 창, 지금 올리기 | `textContent`만 사용 |

올리는 순서: 행사 `events`(이름=폴더 이름, 중복 무시) → `photos`(표시한 사진만, 이름+크기, 중복 무시) → `photo_marks`(시간순, 취소 반영) → `review_sessions`(id로 중복 무시). 폴더 경로·사진 내용은 보내지 않는다. 올린 줄 id는 `cloud.json`에 기록, 다시 시작해도 DB와 대조해 보정한다.

## 3. 단계

1. `cloud_plan.py` + `cloud.py`(가짜 서버 시험) + 안전 시험 예외 한 파일.
2. 로그인·키체인·동의·서버 길 4개.
3. 화면과 자동 시점(훑기 마침, 로그인 직후, 앱 시작, 5분 타이머, 지금 올리기).
4. 실제 DB 확인(사용자 로그인 필요)과 QA 문서.

## 4. 테스트

`test_cloud_plan.py`(순수 규칙: 중복·순서·취소), `test_cloud.py`(로컬 가짜 서버: 동의 전 요청 0건, 재시도, 비밀번호 미저장), `test_safety_rules.py`(예외 한 파일만), `test_ui_server.py`(4개 길). 실제 DB 시험은 사용자 로그인 후 사람 QA.

## 5. 제약·위험

| 위험 | 대응 |
|---|---|
| `security` 명령 인자로 토큰이 잠깐 보임 | 갱신 토큰(수명 있음, 비밀번호 아님)만 저장. 한 사용자 Mac 한정. ADR-0009에 기록 |
| 활성 표시 유일 인덱스 충돌 | 시간순으로 넣고 취소를 먼저 반영 |
| 토큰 만료·네트워크 끊김 | 갱신 토큰으로 재로그인, 실패는 "대기"로 보이고 다음 시점에 재시도 |
| 앱 창 외부 요청 차단 | 인터넷은 서버 프로세스만 사용, 창 제한 유지 |
