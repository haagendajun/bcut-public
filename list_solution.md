# Solution List: 명백한 B컷 걷어내기 (1차 컷) 시간 단축

> 작성일: 2026-10-19
> 근거 문서: [raw_problem.md](raw_problem.md), [problem_definition.md](problem_definition.md)
> 상태: 기획 단계. 웹 조사로 타당성을 1차 확인했고, 실제 사진으로 하는 검증은 아직 하지 않았다.

## 1. 인터뷰 결과 (우선순위 기준)

| 질문 | 답변 | 의미 |
|---|---|---|
| 가장 고통스러운 지점 | **명백한 B컷 걷어내기** (②단계) | 이번 프로젝트가 풀 문제를 이것 하나로 한정한다 |
| 개발 형태 | **Capture One 연동** | 결과가 Capture One 안에서 바로 보여야 한다 |
| 보안 | **외부 업로드 불가 (로컬만)** | 클라우드 AI/API 사용 금지. iMac 안에서만 처리 |
| 성공 기준 | **셀렉 시간 50% 이상 단축** | 품질은 현재 수준을 유지해야 한다 |

**선정한 단 하나의 문제:** 300~1500장 중 눈 감김, 초점 실패, 흔들림 같은 명백한 B컷을 사람이 한 장씩 눈으로 걷어내느라 시간이 오래 걸린다.

## 2. 웹 조사에서 확인한 핵심 사실

| # | 사실 | 신뢰도 | 출처 |
|---|---|---|---|
| F1 | **Capture One 16.8(2026-05-28)에 Assisted Review(베타)가 추가됐다.** 눈 감김, 초점 실패, 노출 문제가 있는 인물 사진을 AI로 표시해 준다. 결과는 브라우저의 **태그**로 붙고, 스마트 앨범 조건과 별점·컬러 태그와 조합할 수 있다. | 높음 (공식 페이지) | [Capture One 16.8](https://www.captureone.com/en/explore-features/whats-new/16-8) |
| F2 | 자동으로 삭제하지 않고 태그만 붙인다. 최종 판단은 사람이 한다. 16.8.6부터 테더링 중에도 동작한다. | 중간 (언론 보도) | [DPReview](https://www.dpreview.com/news/capture-ones-latest-update-includes-automatic-culling-and-more-canon-support/), [CameraJabber](https://camerajabber.com/photography-news/capture-one-16-8-6-adds-assisted-review-while-tethering-and-wireless-tethering-for-canon-eos-r3-and-r6-iii/) |
| F3 | **Assisted Review가 로컬에서 처리되는지는 확인하지 못했다.** 공식 페이지와 검색 결과 어디에도 명시가 없다. | **미확인** | 위 출처들 |
| F4 | Capture One은 AppleScript로 별점(`rating`)과 컬러 태그(`color tag`) 설정이 가능하다. 커뮤니티 예제가 있다. 다만 정확한 속성 범위는 공식 사전에서 확인해야 한다. | 중간 (커뮤니티 예제) | [별점 스크립트](https://support.captureone.com/hc/de/community/posts/6784324083357-Applescript-to-rate-elements-including-videos), [컬러 태그 스크립트](https://latenightsw.com/dt-coding-series-part-3-getting-started-with-applescript-for-capture-one/) |
| F5 | XMP 사이드카의 **별점·키워드는 Capture One이 읽는다.** 반면 **컬러 태그는 앱마다 표준이 달라 불안정**하다. 읽기는 Image > Load Metadata로 수동 실행할 수 있다. | 중간 (공식 문서 + 포럼) | [Capture One 지원](https://support.captureone.com/hc/en-us/articles/360002544898), [XMP 포럼](https://support.captureone.com/hc/es/community/posts/360012159237-XMP-Behaviour) |
| F6 | 눈 감김은 눈 종횡비(EAR)로 판별하는 방식이 널리 쓰인다. 단일 임계값은 고개 돌림이나 랜드마크 오류에서 오판하기 쉽다. | 중간 | [PyImageSearch](https://www.pyimagesearch.com/2017/04/24/eye-blink-detection-opencv-python-dlib/) |
| F7 | 흔들림 점수(Laplacian 분산)는 인물 사진에서 **배경 보케 때문에 신뢰도가 떨어진다.** 얼굴 영역만 따로 측정하는 방식이 대안으로 제시된다. 임계값은 내 사진으로 보정해야 한다. | 중간 (논문) | [CEUR-WS 논문](https://ceur-ws.org/Vol-3664/paper18.pdf) |
| F8 | macOS Vision 프레임워크에 얼굴 품질 점수(0~1, 조명·흔들림·가림·표정·초점 종합)가 있다. 단, **눈 감김을 따로 보는 항목은 아니다.** pyobjc 사용법은 확인하지 못했다. | 중간 (Apple 문서) | [Apple Vision](https://developer.apple.com/documentation/vision/detectfacecapturequalityrequest.md) |
| F9 | 상용 도구(Aftershoot 등)는 로컬 처리를 내세우지만, 출처가 경쟁사 마케팅 글뿐이라 정확도 수치는 신뢰하기 어렵다. 유료다. | 낮음 | [Imagen 글](https://imagen-ai.com/post/best-ai-culling/) |

## 3. 솔루션 후보 3개

### S1. Assisted Review 검증 + 전용 워크플로 구성 (개발 거의 없음)

- **기획:** 이미 있는 Capture One 기능이 내 문제를 얼마나 풀어 주는지 먼저 측정한다. 쓸 만하면 스마트 앨범과 단축키로 "B컷 후보 → 일괄 확인 → 일괄 제외" 흐름을 만든다.
- **개발 범위:**
  1. 지난 행사 3건(소·중·대)에 Assisted Review를 돌리고 오탐·미탐을 기록한다.
  2. 태그를 조건으로 하는 스마트 앨범("B컷 후보", "정상")을 만든다.
  3. 확인용 작업 순서를 문서화한다.
- **타당성:** 높음. F1, F2 근거. 비용이 가장 낮다.
- **한계와 위험:**
  - **F3 미확인.** 외부 업로드 불가 조건에 걸릴 수 있다. 네트워크 모니터링(Little Snitch 등)으로 직접 확인해야 한다.
  - 베타라 놓치거나 잘못 표시할 수 있다.
  - 인물 사진 중심이라 음식·현장 컷은 대상이 아닐 수 있다. (확인 필요)
  - 얼마나 잘 맞는지 알 수 없어서, **놓친 B컷과 잘못 걸린 A컷 비율**을 반드시 측정해야 한다.

### S2. 로컬 B컷 사전 필터 CLI (Python, 핵심 개발)

- **기획:** 행사 폴더를 지정하면 모든 사진에 B컷 의심 점수를 매겨 CSV로 저장하는 로컬 도구. 네트워크를 쓰지 않는다. S1의 한계(F3, 음식·현장 컷, 내 기준 반영)를 보완한다.
- **개발 범위:**
  1. 얼굴 검출 후 눈 감김 판정 (EAR 계열, 얼굴이 작거나 옆모습이면 "판정 불가"로 분리)
  2. 얼굴 영역만 대상으로 한 초점·흔들림 점수 (F7)
  3. 얼굴이 없는 컷(음식, 현장)은 전체 선명도만 판정
  4. 내가 직접 A/B로 라벨링한 사진 100~200장으로 임계값 보정
  5. 출력: 파일명, 사유(눈 감김/흔들림/초점), 점수, 확신도
- **타당성:** 중간~높음. F6, F7, F8 근거. 알고리즘은 모두 공개된 기법이다.
- **한계와 위험:**
  - **A컷을 B컷으로 잘못 걸러내는 오류가 가장 위험하다.** 그래서 도구는 삭제·제외하지 않고 **후보 표시만** 하고, 확신도가 낮으면 "사람이 확인"으로 둔다.
  - 연사 속 의도적 표정(눈을 가늘게 뜬 웃음 등)을 눈 감김으로 오판할 수 있다.
  - 대용량 RAW는 처리 시간이 길 수 있어서 내장 JPEG 프리뷰를 쓰는 방식을 검토해야 한다. (미검증)
  - pyobjc로 Vision을 쓸 수 있는지 확인하지 못했다. 안 되면 오픈소스 얼굴 랜드마크로 대체한다.

### S3. Capture One 연동 브리지 (AppleScript)

- **기획:** S2(또는 S1)가 만든 결과를 Capture One 안에서 바로 쓰이게 연결한다. CSV를 읽어 해당 파일에 별점·키워드·컬러 태그를 자동 적용해, 스마트 앨범에서 "B컷 후보"만 모아 보게 한다.
- **개발 범위:**
  1. AppleScript로 변형(variant)을 파일명으로 찾아 태그 적용 (F4)
  2. 사유별 구분(눈 감김/흔들림/초점)을 키워드로 부여
  3. 스마트 앨범 템플릿 제공
  4. 적용 전후 롤백(원래 별점·태그 복구) 기능
- **타당성:** 중간. 컬러 태그와 별점 설정은 스크립트로 가능하다는 예제가 있다 (F4). 반면 XMP 경유는 컬러 태그가 불안정하므로(F5) **AppleScript 직접 적용을 기본으로 한다.**
- **한계와 위험:**
  - Capture One 버전별로 스크립트 문법이 달라질 수 있다. 사용 중인 버전의 스크립팅 사전으로 먼저 확인한다.
  - 기존에 쓰던 별점·컬러 태그를 덮어쓰지 않도록 전용 키워드를 쓰고 롤백을 만든다.
  - 수천 장 일괄 적용 속도는 미검증이다.

## 4. 우선순위와 진행 순서

| 순위 | 솔루션 | 이유 | 선행 조건 |
|---|---|---|---|
| **1** | **S1 검증** | 비용이 가장 낮고, 이미 있는 기능이 문제를 풀면 개발량이 줄어든다. 결과에 따라 S2의 범위가 정해진다. | 없음 |
| **2** | **S2 CLI** | 로컬 제약(F3 위험)과 내 기준 반영, 음식·현장 컷 처리를 모두 만족시키는 유일한 후보 | S1 결과 (대체 가능한지 판단) |
| **3** | **S3 브리지** | S1·S2 어느 쪽 결과든 Capture One 안에서 쓰이게 하는 연결부. 단독으로는 효과가 없다. | S1 또는 S2 |

**분기 규칙:**
- S1이 로컬 처리이고 정확도가 충분하면 → S2는 "S1이 못 잡는 것(음식, 현장, 내 기준)"만 보완하는 작은 범위로 축소
- S1이 외부 전송으로 확인되면 → **사용 금지**, S2가 주 솔루션이 됨
- S1 정확도가 낮으면 → S2를 주 솔루션으로 개발

## 5. 검증 지표 (50% 단축 기준)

문제 정의의 가설을 숫자로 확인하려면 개발 전에 **현재 기준값(baseline)**부터 재야 한다.

| 지표 | 측정 방법 |
|---|---|
| ② 1차 컷 소요 시간 | 행사 1건에서 작업 시작/종료를 기록, 장수로 나눠 장당 초로 환산 |
| 기준값 대비 단축률 | (기존 장당 초 − 도구 사용 후 장당 초) ÷ 기존 장당 초 → 목표 50% 이상 |
| **미탐률** (놓친 B컷) | 도구가 안 걸렀는데 사람이 B컷으로 제외한 비율 |
| **오탐률** (잘못 걸린 A컷) | 도구가 B컷 후보로 걸었는데 사람이 A컷으로 살린 비율. **가장 중요하게 본다.** |

**주의:** 50% 단축 목표는 ②단계 기준이다. 전체 셀렉 시간에서 ②가 차지하는 비중을 아직 측정하지 못했으므로, 전체가 얼마나 줄지는 기준값을 잰 뒤에 알 수 있다.

## 6. 아직 확인하지 못한 것 (리스크 목록)

1. Assisted Review의 **로컬/클라우드 처리 여부** (S1의 가장 큰 위험)
2. 사용 중인 Capture One 버전이 16.8 이상인지, Assisted Review를 쓸 수 있는지
3. Assisted Review가 음식·현장 컷도 처리하는지
4. AppleScript로 별점·컬러 태그를 쓰는 정확한 문법 (사용 중인 버전의 스크립팅 사전으로 확인)
5. 사진당 처리 시간 (RAW 직접 vs 내장 JPEG 프리뷰)
6. 내 사진 기준에서 눈 감김·흔들림 임계값을 어디에 둘지

## 7. 다음 단계

1. 사용 중인 Capture One 버전을 확인한다.
2. 지난 행사 사진 중 소·중·대 규모 각 1건을 골라 S1 검증을 시작한다.
3. 같은 사진으로 현재 ② 단계 소요 시간(기준값)을 기록한다.
4. 검증 결과에 따라 S2 개발 범위를 확정한다.

## 출처

- [Capture One 16.8 What's New](https://www.captureone.com/en/explore-features/whats-new/16-8)
- [DPReview: Capture One 자동 컬링 업데이트](https://www.dpreview.com/news/capture-ones-latest-update-includes-automatic-culling-and-more-canon-support/)
- [CameraJabber: Capture One 16.8.6](https://camerajabber.com/photography-news/capture-one-16-8-6-adds-assisted-review-while-tethering-and-wireless-tethering-for-canon-eos-r3-and-r6-iii/)
- [Capture One 지원: 별점 AppleScript](https://support.captureone.com/hc/de/community/posts/6784324083357-Applescript-to-rate-elements-including-videos)
- [Late Night Software: Capture One AppleScript 입문](https://latenightsw.com/dt-coding-series-part-3-getting-started-with-applescript-for-capture-one/)
- [Capture One 지원: XMP 동기화](https://support.captureone.com/hc/en-us/articles/360002544898)
- [Capture One 지원 포럼: XMP 동작](https://support.captureone.com/hc/es/community/posts/360012159237-XMP-Behaviour)
- [PyImageSearch: 눈 깜빡임 검출](https://www.pyimagesearch.com/2017/04/24/eye-blink-detection-opencv-python-dlib/)
- [CEUR-WS: 인물 사진 선명도 평가 논문](https://ceur-ws.org/Vol-3664/paper18.pdf)
- [Apple Vision: 얼굴 캡처 품질](https://developer.apple.com/documentation/vision/detectfacecapturequalityrequest.md)
- [Imagen: AI 컬링 도구 비교 (경쟁사 글, 참고용)](https://imagen-ai.com/post/best-ai-culling/)
