# bcut ERD (로그인 포함)

> 기획 상태. 근거: `docs/database-plan.md`, `GLOSSARY.md`, `docs/adr/0001~0006`.
> 슈파베이스 DB(PostgreSQL)에 둘 테이블이다. 로컬 CSV·올릴 대기 목록은 DB 밖이다.

```mermaid
erDiagram
    auth_users ||--|| profiles : "계정 1:1"
    auth_users ||--o{ events : "소유"
    auth_users ||--o{ photos : "소유"
    auth_users ||--o{ scans : "소유"
    auth_users ||--o{ verdicts : "소유"
    auth_users ||--o{ keep_marks : "소유"
    auth_users ||--o{ sorts : "소유"
    auth_users ||--o{ sort_items : "소유"

    events ||--o{ photos : "has"
    events ||--o{ scans : "검사"
    scans ||--o{ verdicts : "판정"
    photos ||--o{ verdicts : "받음"
    photos ||--o{ keep_marks : "남기기"
    scans ||--o{ sorts : "나누어 담기"
    sorts ||--o{ sort_items : "사진별"
    photos ||--o{ sort_items : "담김"

    auth_users {
        uuid id PK "슈파베이스가 관리 (이메일·비밀번호 해시)"
        text email
    }
    profiles {
        uuid id PK "= auth.users.id"
        text display_name "사용자 이름"
        timestamptz created_at
        timestamptz last_sign_in_at "로그인 시 갱신"
    }
    events {
        uuid id PK
        uuid owner_id FK "auth.users"
        text name "행사 이름 (owner별 유일)"
        text last_scan_folder "검사 위치(참고)"
        timestamptz created_at
    }
    photos {
        uuid id PK
        uuid owner_id FK
        uuid event_id FK
        text file_name
        bigint file_size
        timestamptz first_seen_at
    }
    scans {
        uuid id PK "이 컴퓨터에서 생성"
        uuid owner_id FK
        uuid event_id FK
        text folder_path
        text tool_version
        jsonb config "설정 전체"
        int photo_count
        jsonb counts "등급별 장수"
        timestamptz started_at
        timestamptz finished_at
    }
    verdicts {
        uuid id PK
        uuid owner_id FK
        uuid scan_id FK
        uuid photo_id FK
        text tier "candidate|review|normal|no_face|unscorable"
        text[] reasons "eyes_closed|exposure|blur|out_of_focus"
        numeric suspicion "0~1"
        int face_count
        text error
        jsonb details "눈 점수 등 나머지 수치"
    }
    keep_marks {
        uuid id PK
        uuid owner_id FK
        uuid photo_id FK
        timestamptz marked_at
        timestamptz cancelled_at "취소하면 채움"
    }
    sorts {
        uuid id PK "이 컴퓨터에서 생성"
        uuid owner_id FK
        uuid scan_id FK
        text out_path "사본 위치"
        text method "clone|copy"
        text tool_version
        jsonb counts "폴더별 장수"
        int missing
        int unlisted
        bool aborted
        timestamptz created_at
    }
    sort_items {
        uuid sort_id FK
        uuid photo_id FK
        uuid owner_id FK
        text[] folders "담긴 폴더 이름들"
        bool kept "남기기로 이동됨"
    }
```

## 제약
- `profiles.id`는 `auth.users.id`와 같다. 계정을 만들 때 함께 만든다(대시보드에서 계정 생성 후 한 줄 추가 또는 DB 트리거).
- `photos`: unique(event_id, file_name, file_size) · `verdicts`: unique(scan_id, photo_id)
- `events`: unique(owner_id, name) · `sort_items`: PK(sort_id, photo_id)
- `keep_marks`: 사진당 취소 안 된 행은 하나만 (부분 유일 인덱스 `where cancelled_at is null`)

## 로그인 설계 (ADR-0006)
| 항목 | 결정 |
| --- | --- |
| 방식 | 이메일 + 비밀번호만 |
| 가입 | 앱에 가입 화면 없음. 슈파베이스에서 공개 가입을 막고 계정은 대시보드에서 직접 생성 |
| 로그인 요청 | 앱 창이 아닌 로컬 서버(슈파베이스 통신 전용 파일)가 보냄 |
| 상태 유지 | 한 번 로그인하면 유지. 토큰은 macOS 키체인(Electron `safeStorage`)에 암호화 저장, 브라우저 저장소·평문 파일 금지 |
| 로그인 안 했을 때 | 검사·남기기·나누어 담기는 로컬에서 정상 동작, 올리기만 "올릴 대기 목록"에 대기 |
| 비밀번호 분실 | 앱 기능 없음, 슈파베이스 대시보드에서 직접 재설정 |
| 접속 기록 | 별도 테이블 없음, `profiles.last_sign_in_at`만 갱신 |

## 접근 제한 (RLS)
- 모든 테이블: `owner_id = auth.uid()`인 행만 읽기·insert 허용. `profiles`는 `id = auth.uid()`.
- delete 정책 없음. update 허용: `keep_marks.cancelled_at`, `events.last_scan_folder`, `profiles.display_name·last_sign_in_at`.
- 업로드는 같은 UUID면 무시(`on conflict do nothing`).
