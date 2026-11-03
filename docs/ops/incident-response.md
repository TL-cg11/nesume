# 사고 대응 런북 (D18)

운영자·D용. 카나리 적중·탈취 시도·데이터 유출 의심·시크릿 노출 때 무엇을 어떤 순서로 하는지. 알림 종류와 자동 차단 동작은 `alerts.md`, 로그 쿼리는 `observability.md` 5장, 차단 정책은 `../policy/block-policy.md`.

## 승인 기록

| 버전 | 날짜 | 작성 | 리뷰·승인 | 비고 |
|---|---|---|---|---|
| v1 | 2026-11-03 | D | _(팀 리뷰 후 기입: 날짜·승인자)_ | 최초 작성 |

---

## 1. 심각도

| 등급 | 해당 | 첫 대응 | 사후 리포트 |
|---|---|---|---|
| **SEV1** | 카나리 적중(`canary_hit`), 다른 사용자 데이터가 응답·검색에 섞임, 시크릿·키 노출, 운영자 계정 탈취 의심 | **즉시**(알림 후 30분 안 격리) | **24시간 안** 필수 |
| **SEV2** | 탈취 임계치(`exfil_threshold`) 반복(같은 사용자 2회 이상), 차단 급증 알람(`block-surge`), GuardDuty High | 업무 시간 안(4시간) | 24시간 안 필수 |
| **SEV3** | 단발 탈취 임계치, 수집 실패, 5xx·지연 알람 | 다음 업무일 | 필요 시(장애 노트로 대체) |

애매하면 한 단계 높게 잡고 시작해서 조사 후 내린다.

## 2. 연락 체계

| 역할 | 누가 | 하는 일 |
|---|---|---|
| 1차 대응(인시던트 담당) | D | 알림 수신 확인, 격리, 조사 지휘, 리포트 작성 |
| 가드레일 규칙 | A | 분류 규칙(A3)·출력 검사(A5) 보강, A10 시나리오 추가 |
| 감사 로그·데이터 | B | 감사 로그 조회 지원(B11), 삭제·익명화(B20) |
| 검색 필터·카나리·수집 | C | 검색 사전 필터(C6)·카나리 탐지(C13)·Rate Limit(C7) 원인 분석 |
| 승인 | 팀 전원 합의 | 서비스 전체 중단(LLM off 장기화), 사용자 공지 |

- 알림 채널: Discord(봇 이름 `NESUME RADAR`) + SNS 이메일 구독. 알림이 오면 **그 메시지에 스레드를 만들고 "확인, 담당 D" 를 단다** — 이게 수신 확인이다.
- SEV1 은 스레드에 해당 파트 담당을 멘션한다. 30분 안에 D 응답이 없으면 운영자 권한이 있는 다른 팀원이 3장 격리부터 한다.
- 진행 기록은 그 스레드 한 곳에 시각과 함께 남긴다. 사후 리포트는 이 기록으로 쓴다.

---

## 3. 공통 런북

탐지 → 격리 → 조사 → 복구 → 사후 리포트(24h) → 규칙 보강 → 러너 재실행. 단계마다 "확인" 이 끝나야 다음으로 간다.

### 3.1 탐지

**어디서** Discord/이메일 알림, `/admin/dashboard` 최근 이벤트, GuardDuty·Security Hub, 사용자 신고.

알림 본문에서 **`type`·`severity`·`session_id`·`user_id`·`request_id`** 를 스레드에 옮겨 적는다. `summary` 에는 질의 원문이 없다(설계상). 원문이 필요하면 감사 로그의 마스킹 텍스트로 본다.

### 3.2 격리

가장 좁은 것부터 쓴다. 넓힐수록 정상 사용자도 멈춘다.

| 범위 | 무엇을 | 누가 | 방법 |
|---|---|---|---|
| 세션 | 그 세션의 AI 요청을 429 로 | 운영자 | `/admin/sessions` → 세션 ID 입력 → 차단(만료 없음). 4장 |
| 사용자 | 역할 회수 + 강제 로그아웃 | 운영자 | `/admin/users` 에서 `user` 로 변경 → 즉시 로그아웃·기존 토큰 401(`access-control.md` 2.2) |
| 사용자(로그인 자체) | Cognito 사용자 비활성 | D | `aws cognito-idp admin-disable-user --user-pool-id <풀> --username <이메일>` |
| AI 기능 전체 | LLM 호출 중단 | D(긴급 시 운영자) | 3.2.1 |
| 출력 검사 강화 | D19 레일 켜기·전수 검사 | D | `LLAMA_GUARD_ENABLED=true`, `LLAMA_GUARD_SAMPLE_RATE=1.0`, `LLAMA_GUARD_FAIL_OPEN=false` (3.2.1 과 같은 방법) |
| 네트워크 | WAF 를 차단 모드로(Rate Limit 등 실제 차단) | D | `infra/envs/dev/base/main.tf` `module "waf"` 의 `mode = "count"` → `"block"` → base apply |
| 시크릿 | 교체 | D | `secrets-rotation.md` |

#### 3.2.1 LLM 기능 끄기 (`LLM_PROVIDER=none`)

끄면 LLM 을 부르는 기능은 규칙 기반 결과로 내려가거나 "잠시 후 다시 시도" 오류를 낸다(`LlmUnavailable` 처리). 로그인·CRUD·검색은 그대로 된다.

D(helm 권한):

```bash
helm -n dev upgrade nesume deploy/nesume --reuse-values --set-string config.LLM_PROVIDER=none --wait --timeout 10m
```

D 가 없을 때 dev 네임스페이스 수정 권한이 있는 팀원:

```bash
kubectl -n dev patch configmap nesume-config --type merge -p '{"data":{"LLM_PROVIDER":"none"}}'
kubectl -n dev rollout restart deploy/nesume-app
kubectl -n dev rollout status deploy/nesume-app
```

- **다음 main 머지 때 CI 가 `values-dev.yaml` 기준으로 다시 배포하면서 `bedrock` 으로 돌아온다.** 격리 중에는 main 머지를 멈추라고 스레드에 공지하거나, 길어지면 `values-dev.yaml` 에 `LLM_PROVIDER: none` 을 넣는 PR 을 올린다.
- 되살리기: 같은 명령에 `bedrock`.

**확인**

```bash
kubectl -n dev exec deploy/nesume-app -- printenv LLM_PROVIDER
```

### 3.3 조사

**누가** D + 해당 파트. **목표** 언제부터·누가·무엇이·어디까지 나갔는지.

1. **요청 1건 추적** — 알림의 `request_id` 로 CloudWatch Logs Insights(`/nesume/dev/app`, `/nesume/dev/audit` 함께 선택) "요청 추적" 저장 쿼리:

   ```
   fields @timestamp, @logStream, level, logger, msg, status, duration_ms, user_id, role
   | filter request_id = "REQUEST_ID_HERE"
   | sort @timestamp asc
   ```

2. **감사 로그(DB)** — 운영자 MFA 세션으로 `/ai-logs` 화면, 또는 API:

   ```bash
   # 같은 요청
   curl -sS -H "Authorization: Bearer $TOKEN" "http://$ALB/api/audit-logs?request_id=<request_id>"
   # 그 사용자의 최근 기록 (판정·flags·doc_grades·canary_hit)
   curl -sS -H "Authorization: Bearer $TOKEN" "http://$ALB/api/audit-logs?user_id=<sub>&from=2026-11-03T00:00:00Z"
   ```

   볼 것: `decision`, `rule_id`·`flags`, `doc_ids`·`doc_grades`(응답에 쓰인 문서 등급 — `personal`/`sensitive` 가 남의 것이었는지), `canary_hit`, `decision_stage`.
3. **범위 확인** — 같은 `user_id`·같은 시간대의 다른 세션, 같은 `rule_id` 가 다른 사용자에게도 있는지("사용자별 차단" 쿼리). 남의 문서가 섞였다면 `doc_ids` 의 소유자를 B 와 함께 확인해 **영향받은 사용자 목록**을 만든다.
4. **AWS 쪽** — 시크릿·키 노출 의심이면 CloudTrail:

   ```bash
   aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=GetSecretValue \
     --start-time 2026-11-03T00:00:00Z --query 'Events[].[EventTime,Username,CloudTrailEvent]' --output text | head -50
   aws guardduty list-findings --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text)
   ```

5. 원인을 한 줄로 쓸 수 있을 때까지 격리를 풀지 않는다.

### 3.4 복구

| 원인 | 복구 |
|---|---|
| 분류 규칙 누락(A3) | A 가 규칙 PR → 머지·배포 → 6장 재측정 |
| 검색 필터·매트릭스(C6·C2) | C 가 수정 PR, 매트릭스면 `access-control.md` 4장 절차 |
| 배포 회귀(최근 배포 이후 시작) | `deploy-rollback.md` 5장 롤백 |
| 시크릿 노출 | `secrets-rotation.md` 해당 항목 **즉시** 교체 |
| 계정 탈취 | 비밀번호 재설정 강제(`admin-reset-user-password`), TOTP 재등록, 역할 재부여는 본인 확인 후 |

그다음 격리를 푼다: 세션 해제(4장), LLM 되살리기(3.2.1), 역할 복원. **카나리 적중 세션은 원인 수정 배포 전에는 풀지 않는다.**

### 3.5 사후 리포트 (24시간 안)

5장 양식으로 `docs/ops/incidents/YYYY-MM-DD-<짧은-이름>.md` 를 PR 로 올린다. 리포트에 질의 원문·PII·토큰 전체를 적지 않는다(마스킹 텍스트·앞 4자리까지).

### 3.6 규칙 보강 → 러너 재실행

1. 사고 질의를 **A10 시나리오로 추가**(A) — 같은 공격이 다시 오면 러너가 잡는지 보는 회귀 테스트가 된다.
2. 규칙·필터 수정 배포 후 B16 러너 전체 재실행(`access-control.md` 4.2 6번 명령).
3. 차단율 ≥ 95%, 과차단율 ≤ 5% 확인 → 리포트 "후속 조치" 에 수치 기록. 미달이면 리포트를 닫지 않는다.

---

## 4. 세션 차단 · 해제

화면: `/admin/sessions` (운영자 + MFA). API 는 같은 동작이다.

```bash
# 차단 목록
curl -sS -H "Authorization: Bearer $TOKEN" "http://$ALB/api/admin/sessions/blocked"
# 차단 — minutes 를 빼면 해제할 때까지. note 에는 사고 스레드 링크 정도만
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"note":"SEV1 canary 2026-11-03","minutes":null}' "http://$ALB/api/admin/sessions/<session_id>/block"
# 해제
curl -sS -X DELETE -H "Authorization: Bearer $TOKEN" "http://$ALB/api/admin/sessions/<session_id>/block"
```

- 차단 단위는 `X-Session-Id` 다. 클라이언트가 바꿀 수 있으므로 **같은 사용자가 반복하면 역할 회수(3.2)** 로 올린다.
- 차단·해제는 Discord 에 `session_blocked`/`session_released`(info) 로 오고 감사 로그 그룹에 같은 줄이 남는다.
- 해제 기준: 원인 수정 배포 완료(SEV1), 또는 의도치 않은 차단으로 확인(SEV3). 해제 사유를 스레드에 남긴다.
- `system` 역할과 `test-` 세션은 자동 차단 대상이 아니다. 평가 러너 트래픽이 알림을 울리면 SEV3 로 기록만 한다.

**확인** — 차단 후 같은 세션으로 AI 요청 → 429. 해제 후 → 200.

---

## 5. 사후 리포트 양식

```markdown
# 사고 리포트: <제목>

| 항목 | 값 |
|---|---|
| 심각도 | SEV1 / SEV2 / SEV3 |
| 탐지 | YYYY-MM-DD HH:MM KST, 경로(알림 type / 신고) |
| 격리 | HH:MM, 조치(세션 차단 / 역할 회수 / LLM off / …) |
| 복구 | HH:MM, 조치(PR 링크, 배포 sha) |
| 리포트 작성 | 이름, 작성 시각(탐지 후 24h 안) |

## 요약
무슨 일이 있었고 사용자에게 어떤 영향이 있었는지 3줄.

## 타임라인 (KST)
- HH:MM 알림 수신 (request_id: …)
- HH:MM …

## 영향 범위
- 영향받은 사용자 수, 노출된 데이터 등급(doc_grades), 노출 여부(응답까지 나갔는지 / 검색에서 막혔는지)

## 원인
기술적 원인 한 단락. "왜 기존 규칙·필터가 못 막았나" 포함.

## 잘 된 것 / 안 된 것
- 

## 후속 조치
| 조치 | 담당 | 기한 | 상태 |
|---|---|---|---|
| A10 시나리오 추가 | A | | |
| 규칙·필터 수정 PR | | | |
| 러너 재실행: 차단율 __% / 과차단율 __% | B | | |
| 문서 갱신(이 런북, block-policy) | D | | |
```

---

## 6. 시나리오별 체크리스트

### 카나리 적중 (`canary_hit`, SEV1)

- [ ] 응답 단계면 세션이 이미 자동 차단됐는지 `/admin/sessions` 확인. 검색 단계(C13)는 세션을 몰라 **알림만** 온다 → 감사 로그로 세션을 찾아 수동 차단
- [ ] 사용자 역할 회수 여부 판단(반복·의도적이면 회수)
- [ ] `decision_stage` 확인: `retriever` 면 검색 필터가 기밀 등급을 통과시킨 것 → C 호출, 매트릭스·필터 최근 변경 확인
- [ ] 응답까지 나갔으면(출력 단계) 영향 범위 = 그 응답을 받은 사용자 1명. 미끼 토큰은 진짜 데이터가 아니지만 **같은 경로로 진짜 기밀도 나갈 수 있었다**는 뜻이므로 SEV1 유지
- [ ] 원인 수정 배포 전까지 세션 해제 금지

### 탈취 임계치 (`exfil_threshold`)

- [ ] 단발이면 SEV3: 자동 차단(≤10분) 그대로 두고 감사 로그 `rule_id` 분포만 기록
- [ ] 같은 사용자 반복이면 SEV2: 만료 없는 수동 차단 + 역할 회수 검토
- [ ] 정상 사용자 오탐이면(과차단) A 에 규칙 조정 요청, 세션 해제

### 다른 사용자 데이터 노출 의심 (SEV1)

- [ ] LLM off(3.2.1) 검토 — 원인이 검색 경로면 끄는 게 가장 빠른 격리
- [ ] `doc_ids`·`doc_grades` 로 노출 문서와 소유자 목록 작성(B)
- [ ] 노출이 확인되면 영향받은 사용자 공지 여부를 팀 합의로 결정, 리포트에 기록

### 시크릿·키 노출 (SEV1)

- [ ] `secrets-rotation.md` 해당 항목 즉시 교체(분기 주기와 무관)
- [ ] CloudTrail 로 노출 시점 이후 그 자격 증명 사용 내역 확인(3.3 4번)
- [ ] 저장소에 커밋됐다면 교체가 먼저, 히스토리 정리는 그다음(이미 복제됐다고 가정)

### 운영자 계정 탈취 의심 (SEV1)

- [ ] `admin-disable-user` → `admin-user-global-sign-out`
- [ ] 감사 로그 그룹에서 그 운영자의 `role_changed`·`session_released` 등 조치 내역 확인, 되돌리기
- [ ] 본인 확인 후 비밀번호 재설정 + TOTP 재등록

---

## 7. 훈련 기록

분기 1회, 카나리 시연(`alerts.md` 5장)으로 3.1~3.5 를 한 바퀴 돈다.

| 날짜 | 시나리오 | 참여 | 걸린 시간(탐지→격리) | 발견한 문제 |
|---|---|---|---|---|
| | | | | |
