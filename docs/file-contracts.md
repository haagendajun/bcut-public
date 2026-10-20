# 파일 계약 (G1b 고정본, 2026-10-19)

Phase 2(`apply`)와 Phase 5(데이터베이스)가 입력으로 쓰는 파일의 형식. **바꾸려면 이 문서와 `tests/test_contracts.py`를 같이 고친다** (테스트가 열 이름·키를 고정한다).

## 1. `bcut-report.csv` (`scan`이 씀, UTF-8 BOM)

| 열 | 값 | 비고 |
|---|---|---|
| `file` | 파일명 | 행사 폴더 바로 아래의 이름 |
| `status` | `candidate` / `review` / `normal` / `no_face` / `unscorable` | `apply`는 candidate·review만 쓴다 |
| `reason` | `eyes_closed`, `exposure`, `blur`, `out_of_focus`를 `;`로 이음, 없으면 빈 값 | |
| `confidence` | 0~1, 걸린 사유가 없으면 빈 값 | 정렬용 점수([classification-rules.md](classification-rules.md) 3장) |
| `score` | 눈 열림 비율 | **낮을수록 감김** (계획의 "0~1 의심 점수"와 방향이 반대) |
| `note` | `small_eye` / `group` / `read_error` / 빈 값 | 계획의 `unscorable_reason`을 이 열이 대신한다 |
| `exposure`, `exposure_p99`, `exposure_face_hi`, `exposure_global_hi` | 노출 종류와 수치 | |
| `sharpness`, `sharp_best`, `sharp_face` | 흐림 종류(`blur`/`out_of_focus`)와 수치(클수록 흐림) | |
| `face_count`, `faces_considered`, `eye_width_frac`, `error` | 검출·판정에 쓴 얼굴 수, 눈 폭 비율, 읽기 오류 메시지 | |
| `tool_version`, `config_version` | 재현성 | |

## 2. `bcut-log.json` (`scan`이 씀)

키: `version`, `folder`, `started_at`, `finished_at`, `photos`, `seconds`, `seconds_per_photo`, `by_status`, `by_reason`, `unscorable_reasons`, `failed_files`, `config_version`, `reason_tiers`, `thresholds`(`eyes`, `exposure`, `sharpness`).

## 2-1. `bcut-actions.jsonl` (`apply`·`rollback`이 씀, 한 줄에 JSON 하나, 덧붙이기)

공통 키: `command`(`apply`/`rollback`), `mode`(`dry-run`/`commit`), `started_at`, `seconds`, `catalog`, `tool_version`, `config_version`, `error`(연동 오류 설명 또는 null).
`apply` 추가: `planned`, `keywords`(키워드별 장수), `already`, `applied_files`, `warnings`, `violations`, `missing_keywords`, `aborted`, `unmatched`. `rollback` 추가: `entries`, `keywords`, `already_clean`, `missing`, `user_changed`, `stripped_files`, `violations`, `aborted`.
파일 이름과 사진 내용은 담지 않는다. 기록을 못 써도 본 작업은 멈추지 않는다.

## 2-2. 정리 결과 폴더와 `정리 기록.json` (`bcut sort`가 씀)

폴더: `<--out>/<행사 폴더 이름>_정리_<YYYY-MM-DD_HHMM>/` 아래 `버릴 것 같은 컷/`, `직접 확인/`, `이상 없음/`, `판단 못 함/`(있을 때만), `문제 종류별/<눈 감김|너무 밝거나 어두움|흔들려 찍힘|초점이 안 맞음>/`. (2026-10-20 이름 변경: 후보→버릴 것 같은 컷, 확인→직접 확인, 정상→이상 없음, 판정 불가→판단 못 함, 사유별→문제 종류별. 화면과 같은 쉬운 말) 실행마다 새 폴더(같은 분이면 `-2`), 기존 폴더를 덮어쓰지 않는다. 사진은 원본의 **복제본**이다(APFS 복제 또는 복사).
`정리 기록.json` 키: `tool_version`, `created_at`, `event_folder`, `report`, `counts`, `photos`, `placements`, `method`(clone/copy/mixed), `cloned`, `copied`, `rescued`, `missing`, `unlisted`, `size_mismatches`, `aborted`, `files`(파일 이름 → 들어간 폴더들).
`bcut-actions.jsonl`에는 `command: "sort"` 줄이 남는다(`mode`, `photos`, `counts`, `rescued`, `method`, `aborted`, `mismatches`).

## 3. 설정 파일 (TOML, `--config`로 읽고 `calibrate`가 씀)

최상위 `config_version`, `keyword_prefix`; `[reason_tiers]`(사유별 `candidate`/`review`); `[eyes]`, `[exposure]`, `[sharpness]`(임계값). 적지 않은 값은 기본값. 모르는 키·값은 거부. 키 목록은 `bcut.config`와 각 `*Thresholds` 클래스가 정의한다.

## 4. 라벨 CSV (`calibrate`가 읽음)

`file`, `label`(`B` / `OK` / `OK_EXPR`, `UNSURE`·빈 값은 무시). 선택 열 `reason`, `is_final_a`, `source`.

## 5. 아직 고정하지 않은 것

`apply`의 입력으로 필요한 키워드 이름 규칙(`bcut-` 접두어 + 사유)과 되돌리기 기록 파일(`rollback` 입력)은 Phase 2에서 정한다.
