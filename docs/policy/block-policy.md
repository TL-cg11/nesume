# 차단 정책 (D10)

버전: v0.2 · 작성일: 2026-10-27 · 수정: 2026-11-03 · 소유: D(인프라·플랫폼·보안)
관련: 기획서 `spec.md` 7·8·9장, 역할·등급 정의(D1), `app/policy/matrix.yaml`(D2), `app/guardrail/classifier_rules.yaml`(A3), `app/guardrail/schema.py`(A4), `app/features/ratelimit/policy.py`(C7), `app/retrieval/canary.py`(C12·C13), `app/guardrail/rails/llama_guard.py`(D19), `app/core/session_block.py`(D16, `docs/ops/alerts.md`), D7 인증·MFA, A10 `tests/guardrail/scenarios_a10.yaml`

이 문서는 가드레일이 질의를 **어떻게 처리하고, 막혔을 때 사용자에게 무엇을 말하고, 반복 공격자를 어떻게 제한하는지**를 확정한다. 기획서 9장(차단 정책)을 머지된 코드 현실에 맞춰 못 박은 것이며, 두 문서가 다르면 이 문서가 우선한다.

이 문서가 정하지 **않는** 것
- 역할·등급 식별자 → D1 `roles-grades.md`
- 역할 × 등급 판정표 → D2 `matrix.yaml`
- 탐지 규칙의 패턴(정규식) 자체 → A3 `classifier_rules.yaml`. 패턴은 YAML이 기준이고, 이 문서는 규칙 ID와 그 처리만 참조한다

우선순위: **수치·안내 문구·처리 흐름은 이 문서가 기준**이다. 코드가 이 문서와 다르면 코드를 고친다(10장 변경 절차).

---

## 1. 용어와 판정 체계

### 1.1 판정은 세 값이다

| 판정 | 뜻 |
|---|---|
| `allow` | 정상 처리. 응답을 그대로 돌려준다 |
| `mask` | 처리하되 PII 토큰·마스킹을 유지한 채로만. 복원 금지 |
| `block` | 응답 본문 없음. 안내 문구만 돌려준다 |

`flag`는 판정이 **아니다**. 걸린 규칙은 `flags` 배열에 표식으로 남고 판정은 위 셋 중 하나다. A4가 `audit_logs.decision` DB CHECK 제약으로 확정했다. `tasks.md` A4의 "allow/block/mask/flag" 4값 표기는 이 문서로 폐기한다.

### 1.2 질의 유형과 기본 판정

분류기(A3)가 질의를 네 유형으로 나누고, 유형마다 기본 판정이 정해져 있다(`classifier.py` `TYPE_TO_DECISION`).

| 유형 | 기본 판정 | 뜻 |
|---|---|---|
| `normal` | allow | 정상 질의 |
| `out_of_scope` | **allow** + 표식 | 권한 밖 자료를 요구. 막지 않고 표식만 남긴다(3장·4장) |
| `sensitive` | mask | 민감정보를 요구하거나 포함. 출력 단계에서 가린다 |
| `exfiltration` | block | 탈취·주입 시도. LLM을 부르지 않고 끝낸다 |

### 1.3 판정이 내려지는 세 단계

| 단계 | 담당 | 보는 것 |
|---|---|---|
| `classifier` | A1 입력 검사 + A3 분류 + A12 멀티턴 | 사용자가 친 질의 |
| `retriever` | C6 검색 필터 + C13 결과 재검사 | 역할 × 등급으로 걸러진 검색 결과. 걸러진 결과를 한 행씩 다시 확인한다(2장 #13·#14) |
| `output_guard` | A5 출력 검사 + D19 출력 레일 | 모델 응답(복원 전). A5 규칙 검사 뒤 안전 분류 모델(Llama Guard 계열)이 유해 콘텐츠를 한 번 더 본다(2장 #15) |

세 단계의 판정은 A8이 합친다. **더 무거운 쪽이 이긴다**(block > mask > allow). 감사 로그의 `decision_stage`에는 무거운 판정을 만든 단계가 남는다.

---

## 2. 유형별 처리 규칙

| # | 상황 | 규칙 ID | 판정 | LLM 호출 | 응답 본문 | 탈취 카운트 | 안내 문구 |
|---|---|---|---|---|---|---|---|
| 1 | 입력에 거절 대상 PII(주민번호·계좌번호) | `PII_RRN`, `PII_ACCOUNT` | block | ✗ | 없음 | ✗ | `MSG_BLOCK_PII_RRN` / `MSG_BLOCK_PII_ACCOUNT` |
| 2 | 탈취·주입 시도(명시 패턴) | `INJ_SYSPROMPT`, `INJ_DIRECT` | block | ✗ | 없음 | **✓** | `MSG_BLOCK_INTERNAL` |
| 3 | 대량 유출 요구 | `EXF_BULK` | block | ✗ | 없음 | **✓** | `MSG_BLOCK_OTHER_USER` |
| 4 | 멀티턴 누적으로 탈취 판정(A12) | A12 규칙 ID | block | ✗ | 없음 | **✓** | 걸린 규칙에 따라 2·3과 같음 |
| 5 | 민감정보 요구·포함 | `SENS_IDNUM`, `SENS_OTHER_PERSON`, `PII_PHONE`, `PII_EMAIL`, `PII_PERSON` | mask | ✓ | 마스킹 유지 | ✗ | `MSG_MASKED` / `MSG_MASKED_OTHER_PERSON` |
| 6 | 권한 밖 자료 요구, 검색 결과 **있음** | `AUTHZ_*` | allow + 표식 | ✓ | 정상 | ✗ | 없음 |
| 7 | 권한 밖 자료 요구, 검색 결과 **없음** | `AUTHZ_*` | block | ✗ | 없음 | ✗ | `MSG_BLOCK_AUTHZ` |
| 8 | 출력에 카나리·타인 문서·시스템 프롬프트 조각 | `LEAK_CANARY`, `LEAK_OTHER_USER`, `LEAK_SECRET.*` | block | (이미 호출됨) | 없음, **복원하지 않음** | ✗ | `MSG_BLOCK_INTERNAL` |
| 9 | 출력에 알 수 없는 토큰 | `OUT_UNKNOWN_TOKEN` | mask | (이미 호출됨) | 해당 토큰 제거 | ✗ | `MSG_MASKED` |
| 10 | 탈취 세션 제한 중 | — | 거부(429) | ✗ | 없음 | ✗ | `MSG_SESSION_LIMITED` |
| 11 | 파이프라인 내부 오류 | `ERR_PIPELINE` | block | — | 없음 | ✗ | 공통 서버 오류 문구 |
| 12 | 정상 | — | allow | ✓ | 정상 | ✗ | 없음 |
| 13 | **검색 결과**에 카나리 미끼가 섞임(C13) | `LEAK_CANARY` | block | ✗ | 없음 | ✗ | `MSG_BLOCK_INTERNAL` |
| 14 | **검색 결과**에 그 역할이 받을 수 없는 행이 섞임(C13. 예: user에게 남의 자소서, mentor에게 개인 행) | `AUTHZ_FILTER_BYPASS` | block | ✗ | 없음 | ✗ | `MSG_BLOCK_INTERNAL` |
| 15 | 출력이 **유해 콘텐츠**(폭력·무기·자해·혐오·성적 내용 등 Llama Guard 3 범주 S1~S13. D19 레일, `LLAMA_GUARD_ENABLED`) | `UNSAFE_CONTENT`(+ `UNSAFE_CONTENT.S9` 같은 범주 표식) | block | (이미 호출됨) | 없음, **복원하지 않음** | ✗ | `MSG_BLOCK_UNSAFE` |
| 15-1 | D19 레일 오류·타임아웃(3s)·판정 형식 불명 | `OUTRAIL_ERROR` | **allow + 표식**(fail-open 기본). `LLAMA_GUARD_FAIL_OPEN=false` 면 block | (이미 호출됨) | 정상 | ✗ | 없음 / 차단 시 `MSG_BLOCK_UNSAFE` |
| 15-2 | D19 레일 **기록 전용**: `LLAMA_GUARD_ENFORCE=false` 이거나 찍힌 범주가 전부 `LLAMA_GUARD_IGNORE_CATEGORIES` 안(대역 모델이 보안 직무 자소서 문장을 unsafe 로 찍는 오탐, 11-03 dev 5건) | `UNSAFE_CONTENT`(+범주 표식, 심각도 warn) | **allow + 표식**. dev 는 기록 전용 | (이미 호출됨) | 정상(복원함) | ✗ | 없음 |

원칙
- **1·2·3·4·7·13·14는 LLM을 부르지 않는다.** 부르면 그 자체가 비용이고 유출 경로다.
- **8은 복원(detokenize)하지 않는다.** 막기로 한 본문에 진짜 이름이 들어가면 안 된다.
- **탈취 카운트(6장)는 2·3·4에서만 는다.** 입력 PII 거절(1)과 출력 유출(8)은 사용자 실수나 모델 문제일 수 있으므로 세지 않는다. 검색 단계 유출(13·14)도 세지 않는다. 질의가 아니라 **필터 쪽이 뚫린 것**이라 사용자 탓으로 돌릴 수 없고, 탈취 질의였다면 분류 단계(2·3·4)에서 이미 셌다.
- **13·14는 그 요청의 검색 결과 전체를 버린다.** 나올 수 없는 행이 하나라도 섞이면 같은 결과의 다른 행도 믿을 수 없다. 걸러낸 뒤 나머지로 응답하지 않는다. 판정 단계는 `retriever`, 13은 감사 로그 `canary_hit`도 True다(9장).
- **15는 A5 뒤에만 돈다.** A5 가 이미 막은 응답(#8)은 레일을 부르지 않는다(비용). 레일은 마스킹·토큰화된 본문을 보므로 PII 가 모델 밖으로 나가지 않는다. 표본 비율(`LLAMA_GUARD_SAMPLE_RATE`)로 일부만 검사할 수 있고, 미검사 요청은 `OUTRAIL_SKIPPED` 표식만 남는다. fail-open 을 기본으로 둔 이유: 레일은 **2차** 그물이고(A5 가 1차), 외부 모델 장애로 글쓰기 기능 전체가 멈추는 쪽이 더 큰 피해다. 오류 표식 비율은 대시보드에서 본다.
- **13·14는 보안 이벤트다.** 차단으로 끝나지 않고 `nesume.security` 로거(`security_event=canary_hit|filter_bypass`)로 남겨 D16 알림(`SecurityLogBridge` → Discord·이메일)과 대시보드(D15)가 받는다. **8(출력 단계 카나리)은 D16 이 그 세션을 즉시 차단**한다(운영자가 풀 때까지, `docs/ops/alerts.md` 3장). 미끼는 모든 역할에게 차단되는 기밀 등급이라 정상 경로에서는 절대 나오지 않는다. 나왔다는 것은 C6 WHERE 필터가 깨졌거나 우회됐다는 뜻이므로 **즉시 대응**한다(운영 문서 D18).
- 모든 행은 감사 로그 한 행으로 남는다(9장). 11도 남는다.

---

## 3. 하드 차단의 범위

하드 차단(`block`)은 **명시 패턴에 한정**한다(`tasks.md` A3). 구체적으로는 `classifier_rules.yaml`에서 `query_type: exfiltration`인 규칙만이며, v0 기준 세 개다.

| 규칙 ID | 잡는 것 | 안내 문구 |
|---|---|---|
| `INJ_SYSPROMPT` | 시스템 프롬프트·지침·초기 지시 노출 요구 | `MSG_BLOCK_INTERNAL` |
| `INJ_DIRECT` | 지시 무시·역할 탈취·`system:` 위장 | `MSG_BLOCK_INTERNAL` |
| `EXF_BULK` | 전체 사용자·문서·DB 덤프 요구 | `MSG_BLOCK_OTHER_USER` |

규칙
- **역할과 무관하다.** 멘토·운영자 토큰이어도 위 세 규칙은 막는다. 운영자가 템플릿·설정을 다루는 길은 관리 API이고 LLM 대화가 아니다(D1).
- **전처리 후 판정한다.** 제로폭 문자·NFKC 정규화 등 우회를 분류 전에 지운다. 우회 표현이 발견되면 패턴을 추가하는 것으로 대응하고 처리 규칙은 바꾸지 않는다.
- **멀티턴(A12)**이 누적 이력으로 내린 block도 같은 하드 차단으로 취급하며 탈취 카운트가 는다.
- `exfiltration` 규칙을 **추가**하는 것은 보안 리뷰 대상이다(10장). 패턴 보강은 A 리뷰로 충분하다.
- `sensitive`·`out_of_scope` 규칙을 `exfiltration`으로 올리는 것은 유형 변경이므로 보안 리뷰 대상이다.

---

## 4. 권한 외 질의 처리 흐름

권한 밖 자료를 요구하는 질의(`AUTHZ_OPERATOR_ONLY`, `AUTHZ_TEMPLATE`, `AUTHZ_OTHER_RESUME`)는 **분류 단계에서 막지 않는다.** "내 자소서 얘기를 했는데 왜 막히지?" 같은 과차단을 피하기 위해서다. 실제 문서 제외는 C6 검색 필터가 `matrix.yaml`로 한다.

흐름
1. 분류기가 `flags`에 `AUTHZ_*`를 남기고 판정은 `allow`로 통과시킨다.
2. C6가 역할 × 등급 사전 필터로 검색한다. 검색 후 걸러내기는 금지한다(보안 계획 원칙 1).
3. **검색 결과가 비어 있으면** LLM을 부르지 않고 `block` + `MSG_BLOCK_AUTHZ`로 끝낸다. 판정 단계는 `retriever`로 남긴다.
4. 결과가 있으면 정상 응답하되 로그에 표식을 유지한다.
5. 대시보드(D15)에서 표식 비율이 높은 사용자·세션을 모니터링한다.

3번의 적용 범위
- **검색을 쓰는 기능에서만** 적용한다. 검색이 없는 기능(맞춤법 교정 등)은 표식만 남기고 정상 처리한다. 권한 밖 질의였더라도 검색이 없으면 노출될 문서가 없다.
- `exempt_roles`(`operator`, `system`)에는 표식 자체가 붙지 않으므로 이 흐름의 대상이 아니다.

> **구현 요청(A8):** 현재 `pipeline.py`는 `AUTHZ_*` 표식이 있고 검색 결과가 비어도 LLM을 호출한다. 3번을 구현해야 한다. 조건은 "분류 단계 `flags`에 `AUTHZ_` 접두 규칙이 있고, retriever가 주입돼 있고, 결과가 0건". 결과를 `Verdict("block", "retriever", (Finding(해당 AUTHZ 규칙, "info"),))`로 만들어 합치면 감사 로그 모양은 그대로다.

---

## 5. 사용자 안내 문구

### 5.1 원칙

- 어떤 문서가 **존재하는지**, 어떤 **규칙**에 걸렸는지 드러내지 않는다. 규칙 ID는 감사 로그에만 남는다.
- 사용자가 할 수 있는 **다음 행동**을 한 줄 넣는다. 다음 행동이 없는 경우(탈취)는 거절만 한다.
- 문구는 ID로 관리한다. 코드·시나리오·화면은 ID를 참조하고, 문장은 이 표 한 곳에서만 고친다.
- 문장은 A10 시나리오 초안(2026-10-26)을 기준으로 삼았다. 마스킹·권한·세션 제한 문구는 기획서 9.1에서 보강했다.

### 5.2 문구표

| ID | 문구 | 쓰는 곳 |
|---|---|---|
| `MSG_BLOCK_PII_RRN` | 주민등록번호는 자기소개서에 넣을 수 없습니다. 해당 부분을 지우고 다시 시도해 주십시오. | 2장 #1 |
| `MSG_BLOCK_PII_ACCOUNT` | 계좌번호는 자기소개서에 넣을 수 없습니다. 해당 부분을 지우고 다시 시도해 주십시오. | 2장 #1 |
| `MSG_BLOCK_INTERNAL` | 요청을 처리할 수 없습니다. 서비스 내부 설정은 제공하지 않습니다. | 2장 #2·#4·#8·#13·#14 |
| `MSG_BLOCK_OTHER_USER` | 요청을 처리할 수 없습니다. 다른 사용자의 문서는 제공하지 않습니다. | 2장 #3·#4 |
| `MSG_BLOCK_AUTHZ` | 요청하신 자료는 현재 권한으로 열람할 수 없습니다. | 2장 #7 |
| `MSG_MASKED` | 민감한 정보가 포함되어 일부를 가렸습니다. | 2장 #5·#9 |
| `MSG_MASKED_OTHER_PERSON` | 다른 지원자의 개인정보는 제공할 수 없습니다. | 2장 #5 (`SENS_OTHER_PERSON`) |
| `MSG_BLOCK_UNSAFE` | 요청을 처리할 수 없습니다. 유해하거나 부적절한 내용은 제공하지 않습니다. | 2장 #15 |
| `MSG_SESSION_LIMITED` | 반복된 부적절한 요청으로 잠시 이용이 제한되었습니다. {retry_after_min}분 후 다시 시도해 주십시오. | 2장 #10 · D16 차단 세션 |
| `MSG_RATE_LIMITED` | 요청이 많아 잠시 이용이 제한되었습니다. {retry_after_sec}초 후 다시 시도해 주십시오. | 7장 비용 쿼터 |

`MSG_BLOCK_INTERNAL`은 출력 유출(#8)과 검색 단계 유출(#13·#14)에도 쓴다. 모델이 뭘 흘렸는지(카나리·타인 문서), 검색에 뭐가 섞였는지 사용자에게 구분해 알릴 이유가 없다. #14에 `MSG_BLOCK_AUTHZ`를 쓰지 않는 이유: 그 문구는 "권한 밖 자료를 **요구**했다"는 뜻인데 #14는 요구와 무관하게 필터가 뚫린 경우라, 권한 문구를 주면 "열람할 자료가 있다"는 힌트가 된다.

### 5.3 응답 모양

차단·마스킹은 **오류가 아니다**. HTTP 200으로 돌려주되 본문에 판정과 문구를 싣는다. 사용자 세션 제한과 비용 쿼터만 429다.

| 필드 | 값 | 비고 |
|---|---|---|
| `decision` | `allow` / `mask` / `block` | |
| `notice_code` | 5.2의 문구 ID 또는 `null` | **규칙 ID를 넣지 않는다** |
| `notice` | 5.2의 문장 또는 `null` | 치환자(`{retry_after_min}`)는 서버가 채운다 |
| 기능별 본문 | block이면 비어 있다 | |

> **구현 요청(A9, A matching·style 서비스):** 현재 `blocked_reason`에 규칙 ID(`INJ_SYSPROMPT` 등)가 그대로 나간다. 5.1 원칙 위반이므로 `notice_code`·`notice`로 바꾼다. 규칙 ID → 문구 ID 매핑은 2장 표를 따른다. A10 YAML의 `message`는 이 표의 문장과 같으니 유지하고, `notice_code`를 기대값으로 추가하는 것을 권한다.

---

## 6. 탈취 세션 제한

| 항목 | 값 | 조정 |
|---|---|---|
| 기준 단위 | 세션(`session_id`) | |
| 임계치 | **5회** | 환경변수 `RL_EXFIL_VIOLATIONS` |
| 시간창·제한 시간 | **600초(10분)** | 환경변수 `RL_EXFIL_BLOCK_SECONDS` |
| 경계 | 창 안 누적이 임계치 **이상**이면 거부. 5회째 탈취 판정 직후부터 막힌다 | |
| 제한 중 응답 | HTTP 429, `code: rate_limited`, `Retry-After: <남은 초>`, `MSG_SESSION_LIMITED` | |
| D16 차단 목록(`blocked_sessions`) | 임계치 도달 시 같은 세션을 목록에 넣고 알림(`exfil_threshold`). 출력 단계 카나리(#8)는 **해제까지** 차단. 운영자 수동 차단·해제 `/admin/sessions`. 제한 중 응답은 위와 같다 | `docs/ops/alerts.md` |

규칙
- **카운트 대상**은 판정이 `block`이고 `query_type`이 `exfiltration`인 요청만이다(2장 #2·#3·#4). 입력 PII 거절·출력 유출·권한 안내는 세지 않는다.
- 탈취 판정을 받은 요청은 그 자체가 차단되면서 카운트 1이 는다. 제한 중에 들어온 요청은 LLM 경로 **앞**에서 거부되므로 분류되지 않고, 따라서 세지 않는다. 창은 첫 위반 시점에서 시작해 600초 뒤 리셋된다(C7 store 기준, 고정 창).
- 테스트 트래픽(`is_test`, `session_id`가 `test-`로 시작)은 제한 대상이 아니다. 평가 러너(B16)가 탈취 시나리오 10건을 한 세션으로 돌리면 바로 막히기 때문이다.
- `system` 역할은 대화형 API 자체가 403이므로 해당 없다.
- 수치 변경은 환경변수로만 한다. 코드 기본값은 이 표와 같아야 하며, Helm `values*.yaml`에 명시하지 않으면 기본값이 쓰인다.

> **구현 상태(2026-11-03):** C7 래퍼(`RateLimitedGuardrail`)와 D16 래퍼(`SessionBlockGuardrail`)가 `get_guardrail()` 공급 지점에서 모든 LLM 경로를 감싼다. 바깥이 C7: C7 한도 → D16 차단 목록 → A8 → D16 자동 차단·알림(이번 위반을 더해 임계치 판정) → C7 위반 기록.
>
> **(2026-10-27 기록)** C7 `RateLimiter.check_session`·`record_violation`은 라이브러리로만 있고 라우터에 연결되지 않았다. **배선 담당은 A8(파이프라인 호출부)이 아니라 라우터 의존성(B)**으로 정한다. 위치는 LLM 경로 앞 `check_session` → A8 호출 → 판정이 탈취 block이면 `record_violation`. A8을 건드리지 않는다(`docs/C7.md` 배선 그림과 같다).

---

## 7. 비용 쿼터와의 관계

C7의 요청/분(기본 60), 토큰/일(기본 100,000)은 **비용·남용 방지 축**이며 차단 정책이 아니다. 걸리면 429 + `MSG_RATE_LIMITED`이고 감사 로그의 `decision`에는 영향을 주지 않는다. 테스트 트래픽과 `system` 역할은 쿼터 대상이 아니다(D1).

---

## 8. 인증 관련 거부 (D7)

| 상황 | 처리 |
|---|---|
| 운영자 토큰인데 TOTP 미등록 | 403 `forbidden`. `user`로 격하하지 않는다 |
| 운영자 MFA 세션 만료 | 403. 세션 기준은 토큰 `auth_time`으로부터 **15분**(`mfa_session_minutes`, D7과 같은 값) |
| `system` 토큰으로 대화형 API 호출 | 403 |
| 로컬(cognito-local) | `OPERATOR_MFA_REQUIRED=false`로 MFA 검사를 끈다. dev·prod는 `true` |

인증 거부는 가드레일 파이프라인 **앞**에서 일어나므로 감사 로그(`audit_logs`)가 아니라 접근 로그(D3)에 남는다.

---

## 9. 감사·모니터링 연계

- 모든 요청은 B11이 요청 종료 시 `finally`에서 **정확히 한 번** 감사 로그를 쓴다. 차단되든 예외가 나든 기록이 남는다.
- 대표 `rule_id`는 가장 무거운 것, 동률이면 먼저 걸린 것(A4). 나머지는 `flags`에 전부 남는다.
- `canary_hit`는 별도 불리언 컬럼으로 나간다. 카나리 탐지율 100%가 목표라 배열 안에서 세지 않는다. 출력 단계(#8)와 검색 단계(#13) 모두 `LEAK_CANARY`이므로 같은 컬럼이 True가 된다. 어느 단계였는지는 `decision_stage`로 구분한다.
- 미끼 문서는 helm `canarySeed` 훅 Job(`deploy/nesume/templates/canary-seed-job.yaml`, `python -m app.batch.seed_canaries`)이 배포마다 멱등으로 심는다. 임베더가 없는 환경(kind, `embedder.enabled=false`)에는 미끼가 없으므로 #13은 일어나지 않고 #14만 동작한다. 토큰은 DB에만 있고 로그에는 앞 4자리만 남는다.
- 대시보드(D15)에서 보는 것: 탈취 차단 건수·세션 제한 발동 횟수, `AUTHZ_*` 표식 비율이 높은 사용자·세션, 과차단율(A10 정상 케이스가 막힌 비율), 카나리 적중.

---

## 10. 정책 변경 절차

| 변경 대상 | 승인 | 검증 |
|---|---|---|
| 안내 문구 문장(5.2) | A·D 합의, PR 리뷰 | A10 러너 재실행 |
| 문구 ID 추가·삭제 | D 리뷰 + A9 반영 | 같음 |
| 탈취 제한 수치(6장) | D 리뷰. 환경변수 변경은 D18 운영 절차 | B16 러너로 과차단율 확인 |
| `exfiltration` 규칙 추가, 유형 승격 | **보안 리뷰**(D + A) | A10 25건 전부 재실행 |
| 기존 규칙의 패턴 보강 | A 리뷰 | 해당 시나리오 재실행 |
| 2장 처리 규칙 표 자체 | D 리뷰 + A·B·C 승인 | 전체 러너 |

- 변경 후 평가 러너(B16)를 다시 돌려 차단율·과차단율이 기준(spec 11.3) 안에 있는지 확인한다.
- 변경 이력은 이 문서 끝의 표와 운영 문서(D18)에 날짜·사유·전후 수치와 함께 기록한다.

---

## 11. 다른 파트에 요청 (v0 기준)

| 파트 | 요청 | 근거 |
|---|---|---|
| A8 | 권한 외 표식 + 검색 결과 0건이면 LLM 미호출·`MSG_BLOCK_AUTHZ` | 4장 |
| A8 / C13 | 검색 단계 `LEAK_CANARY`·`AUTHZ_FILTER_BYPASS`를 `Verdict("block", "retriever", …)`로 합쳐 LLM 미호출·`MSG_BLOCK_INTERNAL`·`canary_hit`. 지금(2026-11-03)은 C13이 결과를 비워 fail-closed로만 막는다(A #23 머지 전). 그 상태에서는 감사 로그에 `retriever` 판정이 남지 않고, `AUTHZ_*` 표식이 없는 질의는 빈 맥락으로 LLM이 호출된다 | 2장 #13·#14 |
| A9 / A(matching·style) | `blocked_reason` → `notice_code`·`notice`. 규칙 ID는 응답에서 제거 | 5.3 |
| A10 | 시나리오 기대값에 `notice_code` 추가. `message` 문장은 유지 | 5.2 |
| A8 / A9 | D19 레일 포트(`Guardrail.output_rail`, `OutputRail` 프로토콜)와 `_run`·`_run_split` 의 호출 지점 리뷰. `UNSAFE_CONTENT` → `MSG_BLOCK_UNSAFE` 문구 매핑 반영 | 2장 #15 |
| B16 | 레일 on/off 로 러너를 두 번 돌려 차단율·과차단율 비교(`docs/ops/output-rail.md` 표를 실측으로 갱신) | 2장 #15, 10장 |
| C4 | 수집 3회 연속 실패 시 `emit("collector_failed", …)` 호출 | D16 |
| B | 라우터 의존성으로 C7 `check_session`·`record_violation` 배선. 429 응답에 `MSG_SESSION_LIMITED` | 6장 |
| B16 | 테스트 세션은 `test-` 접두어로 제한 예외 확인 | 6장 |
| 전원 | `tasks.md` A4 "allow/block/mask/flag" → "allow/block/mask + flags" 수정 | 1.1 |

---

## 변경 이력

| 날짜 | 버전 | 내용 |
|---|---|---|
| 2026-10-27 | v0 | 최초 작성. 판정 3값 확정, 유형별 처리 표 12행, 하드 차단 3규칙, 권한 외 빈 결과 안내 결정, 문구 ID 9종(A10 초안 기준), 탈취 제한 5회/600초·카운트 대상 확정, 응답에서 규칙 ID 제거 결정 |
| 2026-11-03 | v0.3 | 2장 #15-2 추가: D19 레일 기록 전용(`LLAMA_GUARD_ENFORCE=false`)·범주 제외(`LLAMA_GUARD_IGNORE_CATEGORIES`). 대역 모델이 보안 직무 자소서 문장을 unsafe 로 찍는 오탐(dev 5건)으로 dev 는 기록 전용. `docs/ops/output-rail.md` 5장 |
| 2026-11-03 | v0.2 | D16·D19 반영. 2장 #15(`UNSAFE_CONTENT`, D19 레일)·#15-1(`OUTRAIL_ERROR` fail-open) 추가, 문구 `MSG_BLOCK_UNSAFE` 추가, 1.3 output_guard 단계에 레일 명시, 6장에 D16 차단 목록·자동 차단, 9장 #8 즉시 차단, 11장 요청 추가 |
| 2026-11-03 | v0.1 | C12·C13 반영. 2장에 검색 단계 행 #13(`LEAK_CANARY`)·#14(`AUTHZ_FILTER_BYPASS`, 신규 ID) 추가: block·LLM 미호출·결과 전체 폐기·탈취 카운트 ✗·`MSG_BLOCK_INTERNAL`. 미끼 시드 helm 훅 Job 기록, A8/C13 합산 요청 추가 |
