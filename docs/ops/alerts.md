# 알림 · 자동 대응 (D16)

운영자용. 무엇이 울리고, 어디로 오고, 왔을 때 무엇을 하는지. 로그·대시보드는 `observability.md`, 차단 정책은 `../policy/block-policy.md`.

## 1. 한눈에

```
앱 이벤트 ──emit()──▶ SNS nesume-<env>-alerts ──▶ 이메일 구독(-var alert_email)
CloudWatch 알람 ──────────────▲                 └─▶ Lambda nesume-<env>-webhook-notifier ──▶ Discord 웹훅(또는 Slack)
                                                   (-var webhook_alerts_enabled=true, URL 은 Secrets Manager)
앱 이벤트 중 canary_hit · exfil_threshold ──▶ blocked_sessions 테이블 ──▶ 같은 세션의 다음 AI 요청 429
                                                     ▲
                                 운영자 화면 /admin/sessions (목록 · 수동 차단 · 해제)
```

| 구성 | 위치 |
|---|---|
| 이벤트 발행 `emit(type, summary, …)` | `app/app/core/alerts.py` |
| 자동 차단 래퍼 + 차단 목록 저장소 | `app/app/core/session_block.py`, 테이블 `blocked_sessions`(`app/app/models/blocked_session.py`, 마이그레이션 0025) |
| 운영자 API | `app/app/auth/admin_sessions.py` — `GET /admin/sessions/blocked`, `POST /admin/sessions/{id}/block`, `DELETE …/block` |
| 운영자 화면 | `/admin/sessions` (`web/src/features/admin/AdminSessionsPage.jsx`) |
| SNS·웹훅 Lambda(Discord/Slack)·수집 실패 알람 | `infra/modules/observability/alerts.tf` (+ `files/webhook_notifier.py`) |
| IAM(sns:Publish, D19 모델) | `infra/modules/iam/main.tf` app·batch 역할 |
| 앱 설정 | `ALERTS_SNS_TOPIC_ARN`(Helm `config`), `ALERTS_WEBHOOK_URL`(로컬·kind 만, Secret) |

## 2. 이벤트 스키마

SNS 메시지 본문(JSON)과 감사 로그 그룹(`/nesume/<env>/audit`)의 `msg="alert"` 줄이 같은 필드를 쓴다.

| 필드 | 값 |
|---|---|
| `type` | `canary_hit` · `exfil_threshold` · `block_spike` · `collector_failed` · `alarm` · `session_blocked` · `session_released` |
| `severity` | `info` · `warn` · `critical` (유형별 기본값: 카나리 critical, 임계치·수집·알람 warn, 수동 차단·해제 info) |
| `summary` | 한 줄(300자). **질의 원문·PII·토큰 전체 금지** — 기능·단계·규칙 ID·앞 4자리 정도만 |
| `session_id` / `user_id` | 있을 때만. `user_id` 는 Cognito sub |
| `request_id` | 그 요청의 X-Request-ID. Logs Insights "요청 추적" 쿼리에 넣는다 |
| `ts`, `env` | ISO 시각, `dev`/`production` |

SNS Subject: `[nesume-dev] CRITICAL canary_hit`. Discord 는 같은 내용을 한 메시지로(아이콘 🚨/⚠️/ℹ️, `**굵게**`, 2000자 상한). URL 호스트가 `slack.com` 이면 Slack 형식(`{text}`)으로 보내므로 둘 다 된다.

발송 원칙
- 요청 처리와 **무관**하다. 백그라운드 스레드, 타임아웃 2초, 실패는 `nesume.alerts` 경고 로그로만 남고 요청은 정상 응답한다.
- `ALERTS_SNS_TOPIC_ARN` 이 있으면 SNS(운영). 없고 `ALERTS_WEBHOOK_URL` 만 있으면 웹훅 직접(로컬 compose·kind). 둘 다 없으면 감사 로그 줄만(테스트).
- CloudWatch 알람도 같은 토픽으로 오므로 Discord 채널 하나에 앱 이벤트와 알람이 함께 온다.

## 3. 알림 종류와 대응

| 유형 | 언제 | 자동 조치 | 운영자가 할 일 |
|---|---|---|---|
| `canary_hit` **critical** | 응답(A5)이나 검색 결과(C13)에 카나리 미끼가 섞임 | 응답 단계면 **세션 즉시 차단(해제까지)**. 검색 단계(C13 로그 경유)는 세션을 몰라 알림만 | 블록 정책 2장 #8·#13. 검색 필터(C6)·권한 매트릭스가 뚫린 것이므로 **즉시**: `/admin/dashboard` 최근 이벤트 → 사용자 확인 → 필요하면 `/admin/users` 역할 회수. 원인(쿼리·필터 변경)을 찾기 전엔 세션을 풀지 않는다 |
| `exfil_threshold` warn | 한 세션이 탈취 판정(block·exfiltration)을 5회/10분 (C7 `RL_EXFIL_VIOLATIONS`) | 세션 차단(제한 시간 = C7 남은 창, 기본 ≤10분). C7 의 429 와 겹치지만 목록에 남는다 | `/ai-logs` 에서 그 세션의 질의 유형 확인. 반복 시도면 `/admin/sessions` 에서 **해제까지** 로 다시 차단하거나 사용자 역할 회수 |
| `block_spike` (알람 `nesume-dev-block-surge`) | 차단 수가 2주 기준선 밴드(3σ) 초과(15분) | 없음 | 대시보드 상위 사용자·유형 확인. 특정 세션이면 수동 차단 |
| `collector_failed` (알람 `nesume-dev-collector-failed`) | jobs-collector 파드 로그에 `FAILED` 가 **3일 연속**(하루 1회 실행 기준). C4 가 `emit("collector_failed")` 를 부르면 즉시 | 없음(배치는 다음 날 다시 돈다) | 대시보드 '배치 결과' 패널 → `kubectl -n dev logs job/<name>`. 공공 API 키 만료(Secrets Manager)·서울시 8088 http·임베더 다운이 흔한 원인 |
| `alarm` (그 외 CloudWatch 알람) | 5xx·p95·노드·RDS·파드 재시작 | 없음 | `observability.md` 3장 |
| `session_blocked` / `session_released` info | 운영자 수동 조치 | — | 기록용. 감사 로그 `session_blocked`/`session_released` 줄과 짝 |

세션 자동 차단의 규칙
- 차단은 **`X-Session-Id`** 단위다. 헤더는 클라이언트가 정하므로 바꿔 가며 우회할 수 있다 → 같은 사용자가 반복되면 C7 사용자 축(10회/시간)과 역할 회수가 뒤를 받친다. 목록에는 `user_id` 가 같이 남는다.
- `system` 역할, 평가 트래픽(`test-` 세션), 세션 없는 요청은 차단하지 않는다(블록 정책 6장). 카나리 **알림은** 그래도 간다.
- 차단 중 응답은 C7 세션 제한과 같은 429 + 같은 문구(`MSG_SESSION_LIMITED` 계열) — 어떤 차단인지 드러내지 않는다. `Retry-After` 는 만료 있는 차단이면 남은 초, 해제까지면 3600.
- 차단 목록 DB 오류는 **fail-open**(요청 허용 + 경고 로그 + 알림 summary 에 "수동 차단 필요"). C7 과 같은 판단: 이 층이 빠져도 A3·A5 가 요청마다 막는다.
- 같은 세션이 이미 차단 중이면 알림을 다시 보내지 않는다(중복 방지). 만료 있는 차단 위에 카나리가 오면 만료 없는 차단으로 올라간다.

## 4. 처음 설정 (dev)

1. **base apply** — IAM 변경(app·batch 역할 `sns:Publish`, app 역할 D19 모델 권한)
   ```bash
   terraform -chdir=infra/envs/dev/base apply
   ```
2. **Discord 웹훅** — Discord 서버의 채널 설정 → 연동 → 웹훅 → 새 웹훅 → URL 복사(`https://discord.com/api/webhooks/<id>/<token>`). 앱 시크릿 JSON 에 필드를 추가한다(기존 필드 유지). Slack 이면 Incoming Webhook URL 을 같은 키에 넣는다.
   ```bash
   aws secretsmanager get-secret-value --secret-id nesume/dev/app --query SecretString --output text > current.json
   # current.json 에 "ALERTS_WEBHOOK_URL": "https://discord.com/api/webhooks/..." 추가
   aws secretsmanager put-secret-value --secret-id nesume/dev/app --secret-string file://current.json
   ```
   URL 은 저장소·values·로그에 적지 않는다(gitleaks).
3. **compute apply** — Lambda 구독 + 수집 실패 알람 + 이메일(선택)
   ```bash
   terraform -chdir=infra/envs/dev/compute apply -var webhook_alerts_enabled=true -var alert_email=<주소>
   ```
   이메일은 확인 메일 링크를 눌러야 활성.
4. **앱** — `values-dev.yaml` 의 `ALERTS_SNS_TOPIC_ARN` 은 토픽 이름이 고정이라 이미 들어 있다. 배포(main 머지 → CI `build-deploy`)하면 ExternalSecret 이 1시간 안에 `ALERTS_WEBHOOK_URL` 도 주입하지만 SNS 가 있으면 앱은 SNS 만 쓴다.
5. **확인**
   ```bash
   aws sns publish --topic-arn $(terraform -chdir=infra/envs/dev/compute output -raw alerts_topic_arn) \
     --subject "[nesume-dev] WARN alarm" --message '{"type":"alarm","severity":"warn","summary":"D16 수동 점검","env":"dev"}'
   ```
   Discord 채널에 메시지가 오면 끝. 안 오면 `aws logs tail /aws/lambda/nesume-dev-webhook-notifier --since 10m`.
   Lambda 를 거치지 않고 웹훅 자체를 먼저 확인하려면:
   ```bash
   curl -sS -X POST -H 'Content-Type: application/json' -d '{"content":"nesume 웹훅 점검"}' "$WEBHOOK_URL"
   ```

로컬 compose 에서 Discord 로 바로 받으려면 `.env` 에 `ALERTS_WEBHOOK_URL=` 만 넣는다(SNS 미설정 → 직접 POST).

## 5. 시연 절차 (완료 기준)

**카나리 → 알림 → 자동 차단 → 429**
1. 카나리 토큰: dev DB `user_profile_embeddings` 의 `owner_id='system:canary'` 행에서 `NSM-CANARY-…` 하나를 읽는다(시드 Job `canary-seed`가 심음). 토큰은 로그·채팅에 전체를 적지 않는다.
2. 운영자 로그인 후 `X-Session-Id: demo-canary-1` 로 글 다듬기 API 를 호출하되 응답에 토큰이 섞이게 한다. 가장 확실한 방법은 **평가 러너가 아니라** 테스트 전용 경로로 A5 를 통과시키는 것인데 운영 환경에서는 모델이 토큰을 그대로 되돌리지 않는다. 그래서 시연은 두 단계로 나눈다:
   - (a) 단위 시연: `app/tests/test_session_block.py::test_canary_hit_blocks_session_and_alerts_once` — 판정 → 차단 → 429 → 알림 1회.
   - (b) 실환경 시연: 운영자 화면 `/admin/sessions` 에서 `demo-canary-1` 을 수동 차단 → 같은 세션으로 글 다듬기 호출 → 429 → Discord 에 `session_blocked` 도착 → 해제 → 다시 200. 검색 단계 카나리(C13)는 `tests/scenarios/test_canary.py` 가 `nesume.security` 로그를 만들고, 그 로그가 `SecurityLogBridge` 로 `canary_hit` 알림이 되는 것은 `tests/test_alerts.py::test_security_bridge_turns_c13_log_into_alert`.
3. 세션 해제는 운영자 MFA 세션(`require_operator_mfa`)에서만 된다. dev 의 `test-operator1` 은 MFA 면제(`MFA_EXEMPT_TEST_OPERATORS`).

**수집 3회 실패 알림**: 알람은 3일이 걸리므로 시연은 `aws cloudwatch set-alarm-state --alarm-name nesume-dev-collector-failed --state-value ALARM --state-reason demo` 로 상태를 강제해 Discord·이메일 수신을 확인하고, 즉시 `--state-value OK` 로 되돌린다. 메트릭 필터 자체는 `aws logs test-metric-filter --filter-pattern '{ $.kubernetes.pod_name = "*jobs-collector*" && $.log = "*FAILED*" }' --log-event-messages '{"log":"seoul: FAILED","kubernetes":{"pod_name":"nesume-jobs-collector-abc"}}'` 로 확인한다.

## 6. 다른 파트에 요청

| 파트 | 요청 |
|---|---|
| C4 | 수집 소스 3회 연속 실패를 세어 `from app.core.alerts import emit; emit("collector_failed", "<source>: 3회 연속 실패")` 호출(배치 역할에 sns:Publish 있음). 지금은 CloudWatch 알람(3일)만 |
| C13 / A8 | `canary.report()` 에 `session_id` 를 넘기거나 A8 이 검색 판정을 `Verdict("block","retriever",…)` 로 합치면 검색 단계 카나리도 자동 차단된다(지금은 알림만). 블록 정책 11장과 같은 요청 |
| B | `blocked_sessions` 모델·마이그레이션 0025 취합 확인(models/README ERD 에 인프라 테이블로 추가) |
| B11 | 감사 로그 기록 함수가 `nesume.audit` 로거로 1줄 남기면 `BlockCount`·`CanaryHitCount` 알람이 살아난다(`observability.md` 2장과 같음) |
