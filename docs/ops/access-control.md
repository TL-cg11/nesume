# 접근 통제 운영 (D18)

운영자·D용. 누가 어떤 역할을 받는지, 데이터에 어떤 등급이 붙는지, 역할 × 등급 매트릭스를 어떻게 바꾸고 기록하는지. 차단 판정·안내 문구는 `../policy/block-policy.md`, 사고 대응은 `incident-response.md`.

## 승인 기록

| 버전 | 날짜 | 작성 | 리뷰·승인 | 비고 |
|---|---|---|---|---|
| v1 | 2026-11-03 | D | _(팀 리뷰 후 기입: 날짜·승인자)_ | 최초 작성 |

---

## 1. 한눈에

| 무엇 | 기준 파일(코드) | 바꾸는 사람 | 바꾸는 방법 |
|---|---|---|---|
| 역할(`user`·`mentor`·`operator`·`system`) | Cognito 그룹(`infra/modules/cognito`), 토큰 → `app/app/auth/cognito.py` | 운영자(MFA) | `/admin/users` 화면 = `PUT /admin/users/{user_id}/role` |
| 데이터 등급(`public`~`confidential`) | `app/app/models/grading.py` `GRADE_BY_MODEL`, 임베딩 테이블 기본값(`app/app/models/embedding.py`) | 코드 PR | 3장 |
| 역할 × 등급 매트릭스 | `app/app/policy/matrix.yaml` (C2 로더 `app/app/policy/policy.py` 가 읽음) | 코드 PR | 4장 |
| 변경 이력 | 이 문서 5장 | 변경 PR 작성자 | 같은 PR 에서 표에 한 줄 |

- 역할은 **요청마다 액세스 토큰의 `cognito:groups`** 에서 읽는다. 대화 중 "나는 운영자야" 같은 발화로 바뀌지 않는다(spec 7.4).
- 등급은 **저장할 때 테이블 기준으로 자동 부여**되고 바꿀 수 없다(`GradeChangeForbidden`). 사용자가 고르지 않는다.
- 매트릭스는 파일 하나를 분류기(A3)와 검색 사전 필터(C6)가 같이 읽는다. 칸 하나를 바꾸면 두 곳이 함께 바뀐다.

---

## 2. 역할 부여 기준

### 2.1 기준

| 역할 | 누구에게 | 부여 조건 | 부여 주체 | 회수 시점 |
|---|---|---|---|---|
| `user` | 가입자 전원 | 가입 + 이메일 확인 | 자동(그룹 없음 = `user`) | 계정 삭제(B20) |
| `mentor` | 공유받은 자소서를 읽는 사람 | 멘토 신청 확인(소속·경력 확인은 운영 판단) | 운영자 | 활동 종료, 신고 접수, 6장 정기 점검에서 90일 미로그인 |
| `operator` | 팀 운영 담당 | D 승인 + **TOTP 등록** | 운영자(다른 운영자) | 프로젝트 이탈, 사고 조사 대상, 정기 점검 |
| `system` | 배치 서비스 계정(`svc-batch@`) | 사람에게 주지 않는다 | 시드 스크립트(`app/app/auth/seed.py`)만 | — |

규칙
- 한 토큰에 역할은 하나다. 역할 그룹이 2개 이상이면 401(설정 오류, fail closed).
- API 는 **자기 자신의 역할 변경 403**, **`system` 부여 422** 로 막는다. 운영자를 늘리려면 다른 운영자가 해야 한다.
- 테스트 계정 표시는 그룹 `test` 로 따로 붙는다(역할 아님). 평가·시드 계정 외에는 붙이지 않는다.
- 운영자의 `personal`·`sensitive` 열람은 **마스킹 상태**로만 되고, 용도는 장애 대응·신고 처리로 한정한다. 이 목적 제한은 지금 규칙(사람의 약속)이지 코드로 강제되지는 않는다(매트릭스 v1 후보: `purpose` 조건).

### 2.2 절차 — 역할 변경

**언제** 멘토 신청·운영자 합류·이탈·사고 대응 시. **누가** 운영자 1명(MFA 세션). 운영자 부여·회수는 D 가 승인한다.

1. 운영자로 로그인 → TOTP 확인 → `/admin/users` 에서 대상 이메일 검색 → 역할 선택 → 저장.
2. 저장되면 서버가 그 사용자를 **즉시 로그아웃**시킨다(`AdminUserGlobalSignOut` + `users.token_not_before`). 기존 액세스 토큰도 다음 요청부터 401 이므로 다시 로그인해야 새 역할이 적용된다.
3. 운영자 부여였다면 대상자가 첫 로그인 때 TOTP 를 등록해야 운영자 API 가 열린다(`OPERATOR_MFA_REQUIRED=true`).

**확인**

```bash
# 감사 로그 그룹에 role_changed 가 남았는지 (누가 · 누구를 · 무엇에서 무엇으로)
aws logs tail /nesume/dev/audit --since 1h --format short --filter-pattern '{ $.msg = "role_changed" }'
```

대상자가 예전 토큰으로 API 를 부르면 401 이 나와야 한다.

---

## 3. 등급 부여 기준

### 3.1 등급 정의

| 등급 | 정의 | 판단 질문 | RAG 인덱스 |
|---|---|---|---|
| `public` 공개 | 누구나 볼 수 있는 외부·참고 자료 | 출처가 공개돼 있고 특정 사용자 것이 아닌가? | 공개 인덱스 |
| `internal` 내부 | 서비스 운영용. 사용자에게 직접 보여주지 않음 | 운영자·시스템만 써야 하는가? | 없음 |
| `personal` 개인 | 특정 사용자 소유 | `owner_id` 가 있는가? 소유자·공유 대상만 봐야 하는가? | 개인 인덱스(토큰화 후) |
| `sensitive` 민감 | PII 원문 노출이 금지되는 데이터 | 원문에 PII 가 있거나, 요청 기록(감사)인가? | 없음 |
| `confidential` 기밀 | RAG 로 절대 나가면 안 됨 | 새면 서비스 보안이 무너지는가(프롬프트·키·미끼)? | 카나리 미끼만(탐지용) |

새 데이터는 **위에서부터가 아니라 아래에서부터** 묻는다. 기밀인가 → 민감인가 → 개인인가 → 내부인가 → 공개. 애매하면 높은 쪽으로 둔다.

### 3.2 현재 부여 표 (코드 기준)

| 데이터(테이블) | 등급 | 부여 위치 |
|---|---|---|
| 자소서·문항·버전(`resumes`·`questions`·`versions`), 경험, 지원 기록, 말투 프로필, 멘토 코멘트, 면접 세션·메시지 | `personal` | `GRADE_BY_MODEL` |
| 프롬프트 템플릿 | `internal` | `GRADE_BY_MODEL` |
| PII 토큰 ↔ 원문(`pii_vault`), 감사 로그(`audit_logs`) | `sensitive` | `GRADE_BY_MODEL` |
| 공고 청크·학습 강좌 임베딩 | `public` | `embedding.py` 컬럼 기본값 |
| 사용자 문서 임베딩 | `personal` | `embedding.py` 컬럼 기본값 |
| 카나리 미끼(`owner_id='system:canary'`) | `confidential` | `app/app/batch/seed_canaries.py` |
| 시스템 프롬프트, Secrets Manager 값 | `confidential`(분류상) | DB·인덱스에 넣지 않는다 |
| `blocked_sessions` | 등급 없음 | RAG 대상이 아닌 인프라 테이블 |

### 3.3 절차 — 새 데이터에 등급 붙이기

**언제** 새 테이블·새 인덱스를 만들 때. **누가** 그 테이블 소유 파트가 PR, D 리뷰.

1. 3.1 판단 질문으로 등급을 정한다.
2. 같은 PR 에서: 모델에 `grade_column(Grade.X)` + `grade_check()`, ORM 저장 테이블이면 `GRADE_BY_MODEL` 에 한 줄, 이 문서 3.2 표에 한 줄.
3. 리뷰: 새 행 추가는 **D 리뷰**만으로 된다. 기존 데이터의 **등급 하향**이나 표에서 삭제는 **보안 리뷰(D + A)**.

**확인** — `app/tests/test_models_b8_grading.py` 가 CI 에서 돈다. 새 모델에 등급이 자동 부여되고 변경이 막히는지 같은 파일에 케이스를 추가한다.

---

## 4. 매트릭스 변경 절차

### 4.1 누가 승인하나

| 바꾸는 것 | 리뷰·승인 | 재측정 |
|---|---|---|
| 칸의 `decision`(allow/mask/block) | D + A(분류기) + C(검색 필터) | B16 러너 전체 |
| 칸의 `scope`(own/shared/all) | D + C | B16 러너 전체 |
| 역할·등급 **식별자** 추가·이름 변경 | D + A·B·C 전원(토큰 클레임·DB CHECK·벡터 메타데이터·YAML 이 동시에 바뀜) | 전체 + 마이그레이션 |
| 주석·설명만 | D | 없음 |

`block` → `allow` 처럼 **넓히는 변경은 보안 리뷰**로 취급한다. 좁히는 변경은 과차단율만 본다.

### 4.2 순서

**언제** 정책 결정이 났을 때(회의록·이슈 링크 필요). **누가** D 가 PR 을 연다.

1. 브랜치에서 `app/app/policy/matrix.yaml` 수정 + `version` 올리기.
2. 같은 PR 에 이 문서 5장 표에 한 줄 추가(날짜·버전·사유. 수치 칸은 비워 둔다).
3. CI 통과(`app/tests` 의 C2 로더·C6 필터·A3 분류기 테스트).
4. 리뷰 승인 → main 머지 → CI `build-deploy` 가 dev 에 배포.
5. 배포 확인:

   ```bash
   kubectl -n dev exec deploy/nesume-app -- head -12 /srv/app/policy/matrix.yaml   # version 이 올라갔는지
   kubectl -n dev get deploy nesume-app -o jsonpath='{.spec.template.spec.containers[0].image}'
   ```

   `POLICY_MATRIX_PATH` 를 설정하지 않았으므로 이미지에 들어간 번들 파일이 운영본이다.
6. B16 러너 재실행(시나리오 전체):

   ```bash
   # 앱 이미지 안, DB 접근 가능한 환경. 로컬 compose 스택(app·db·cognito-local)을 띄우고 시드(D6)한 뒤
   docker compose run --rm -e PYTHONPATH=/eval test python -m runner --base-url http://app:8000
   ```

   결과 `eval/reports/<round>/summary.json` 의 차단율·과차단율을 5장 표에 채운다. 기준: 차단율 ≥ 95%, 과차단율 ≤ 5%(spec 11.3).
7. 기준 미달이면 **되돌린다**: `git revert <머지 커밋>` PR → 머지 → 재배포. 수치와 함께 5장 표에 "롤백" 한 줄.

### 4.3 주의

- 저장소의 운영 매트릭스는 지금 **C 로더용 v0(`version: 0`, `history` 없음)** 이다. D2 공식본(`schema_version`·`history[]`·조건 정의 포함)은 아직 저장소에 들어가지 않았다. 공식본으로 바꾸는 PR 이 들어오면 `history[]` 와 5장 표를 같은 내용으로 맞춘다(사람용은 이 표, 기계용은 `history[]`).
- 운영 중 파일만 바꿔 끼우는 방법(`POLICY_MATRIX_PATH` 로 ConfigMap 마운트)은 쓰지 않는다. 이미지 sha 와 정책 버전이 어긋나 사고 조사 때 어느 정책이었는지 알 수 없게 된다.

---

## 5. 매트릭스 변경 이력

| 날짜 | 버전 | 내용·사유 | 차단율 전 → 후 | 과차단율 전 → 후 | PR·커밋 |
|---|---|---|---|---|---|
| 2026-10-16 | 0 | 최초. spec 6.3 표를 그대로 YAML 로(C2 로더 동봉) | 측정 전 | 측정 전 | `2081e7b` (브랜치 `feat/jobs-recommend` 직접 머지 `31ff4fd`, 10-18) |
| 2026-10-16 | 0 | 등급 키를 B2 영문 값으로, 공유 조건을 `resumes.shared_with` JSONB 로 | 측정 전 | 측정 전 | `e60241d` (같은 머지) |
| 2026-10-27 | 0 | 변경 없음. 기준선 측정 round1(시나리오 90건) | — → 85.0% (34/40) | — → 0.0% (0/50) | `eval/reports/round1` |

다음 줄부터는 4.2 절차대로 추가한다. 차단율 미달(85.0% < 95%)의 원인은 매트릭스가 아니라 분류 규칙(A3)이다(`eval/reports/REPORT.md`).

---

## 6. 정기 점검

| 주기 | 누가 | 무엇을 | 어떻게 확인 |
|---|---|---|---|
| 월 1회 | D | 운영자·멘토 목록이 2.1 기준에 맞는지 | `/admin/users` 에서 역할 필터. 이탈자·90일 미로그인 멘토는 `user` 로 |
| 월 1회 | D | 운영자 전원 TOTP 등록 여부 | `aws cognito-idp admin-get-user --user-pool-id <풀> --username <이메일> --query UserMFASettingList` |
| 분기 1회 | D | 매트릭스·3.2 표가 코드와 같은지 | `GRADE_BY_MODEL` 과 3.2 표 대조, 5장 마지막 줄 버전 = `matrix.yaml` `version` |
| 배포 전 | D | `MFA_EXEMPT_TEST_OPERATORS` 가 production 에서 `false` | `values-prod.yaml`. 앱도 production 에서는 무시한다 |
