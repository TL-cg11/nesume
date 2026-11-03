# 로그·모니터링·운영 대시보드 (D14·D15)

운영자용. 무엇이 어디에 기록되고, 어디서 보고, 무엇이 울리는지. 올리고 내리는 쪽은 `infra/README.md`.

## 1. 한눈에

| 보는 곳 | 내용 | 출처 |
|---|---|---|
| 웹 **운영 대시보드** `/admin/dashboard` (운영자 로그인 시 홈) | AI 가드레일 판정(허용·가림·차단) 추이, 유형·역할·기능·단계별, flag 비율 상위 사용자, 최근 차단·카나리, HTTP 트래픽(요청·4xx·5xx·p95·라우트별) | 감사 로그 테이블(B11) 집계 `GET /admin/dashboard/summary`, 파드 프로세스 집계 `GET /admin/dashboard/traffic` |
| 웹 **AI 사용 기록** `/ai-logs` | 요청 1건씩(마스킹된 질문·판정·flag) | B11 `GET /audit-logs` |
| CloudWatch 대시보드 **`nesume-dev`** | 환경 전체 요청 수·5xx 비율·p50/p95/p99·차단·노드 CPU/메모리·파드 재시작·RDS·최근 5xx·배치 결과·운영자 조치 | Fluent Bit 메트릭 필터 + Container Insights + RDS |
| CloudWatch Logs `/nesume/dev/app` (30일) | 앱·웹·배치·애드온 파드 stdout. 접근 로그 1줄/요청 | Fluent Bit |
| CloudWatch Logs `/nesume/dev/audit` (90일, KMS) | `log_type=audit` 줄: 운영자 조치(역할 변경 등). B11 이 로그 스트림에도 남기면 가드레일 판정도 여기 | Fluent Bit `rewrite_tag` |
| SNS `nesume-dev-alerts` | 아래 알람 전부 + 앱 보안 이벤트(카나리·탈취 임계치·세션 차단). 이메일(선택)·Slack(Lambda). 자동 차단과 대응 절차는 `alerts.md` | CloudWatch 알람, `app/app/core/alerts.py` |

웹 대시보드의 **트래픽 패널은 응답한 파드 1개의 프로세스 집계**다(`app/app/core/metrics.py`, 24시간 링 버퍼, 재시작하면 비워짐). 환경 전체 수치·추세·알람은 CloudWatch 가 기준이다. 둘 다 평가 러너(`is_test=true`)와 헬스 프로브는 뺀다.

## 2. 로그 형식과 분리 규칙

- 앱은 한 줄 JSON(`app/app/core/logging.py`). 모든 줄에 `request_id`, `log_type`(`app`|`audit`), `level`, `logger`, `msg`.
- 접근 로그: `msg="http_request"`, `method`, `path`, `status`, `duration_ms`, `user_id`, `role`, `is_test`. 질의 본문·토큰·이메일은 없다.
- **감사 성격의 줄은 `nesume.audit.<모듈>` 로거**로 남긴다 → `log_type=audit` → Fluent Bit 가 `/nesume/dev/audit` 로 보낸다. 지금은 역할 변경(`role_changed`)이 여기 들어간다. B11 감사 로그 기록 함수(`features/audit/sink.py`)가 DB 외에 로그 스트림에도 남기려면 같은 로거로 `decision`·`canary_hit`·`is_test` 필드를 찍으면 되고, 그러면 `BlockCount`·`CanaryHitCount` 메트릭과 차단 급증·카나리 알람이 살아난다(B 요청 사항).
- Fluent Bit 는 `logging` 네임스페이스 DaemonSet(`aws-for-fluent-bit`). 스트림 이름 `<namespace>.<pod>`. `kubernetes.*` 메타데이터가 붙는다(라벨·주석 제외).

## 3. 알람

| 알람 | 조건 | 먼저 볼 것 |
|---|---|---|
| `nesume-dev-5xx-rate` | 5xx 비율 > 2% (5분, 요청 있을 때만) | Logs Insights "5xx 요청" → `request_id` 로 "요청 추적" |
| `nesume-dev-p95-latency` | p95 > 3000ms (5분) | "느린 라우트 p95", 임베더·Bedrock 지연, 노드 CPU |
| `nesume-dev-block-surge` | 차단 수가 기준선 밴드(3σ) 초과 (15분, 이상 탐지) | 운영 대시보드 상위 사용자 → D16 세션 차단 |
| `nesume-dev-canary-hit` | 카나리 탐지 ≥ 1 (5분) | 운영 대시보드 최근 이벤트의 사용자. 즉시 대응 |
| `nesume-dev-pod-restarts` | 컨테이너 재시작 ≥ 5회/5분 | `kubectl -n dev describe pod` Events. 스팟 회수 1~2회는 정상 |
| `nesume-dev-node-cpu` / `-node-memory` | 노드 평균 > 85% (10분) | `kubectl top nodes`, HPA(`hpa.enabled`) |
| `nesume-dev-rds-connections` | 연결 > 60 (t4g.micro 상한 ~80) | app 레플리카 수 × 풀 크기 |
| `nesume-dev-rds-free-storage` | 여유 < 2GB | 감사 로그 보존 배치(B11 retention), 스토리지 확장 |
| `nesume-dev-collector-failed` (D16) | jobs-collector 로그 `FAILED` 가 3일 연속 | `alerts.md` 3장 |

이메일을 받으려면 `infra/envs/dev/compute` apply 때 `-var alert_email=<주소>`(또는 tfvars). 구독 확인 메일의 링크를 눌러야 활성화된다. Slack 은 `-var slack_alerts_enabled=true`(웹훅 URL 은 Secrets Manager) — 설정 절차는 `alerts.md` 4장.

## 4. 올리기 · 확인

```powershell
$env:AWS_PROFILE = "nesume"
terraform -chdir="infra/envs/dev/base" apply      # 로그 그룹 보존 30/90일·KMS, fluent-bit·cloudwatch-agent 역할 (한 번)
terraform -chdir="infra/envs/dev/compute" apply   # Fluent Bit, Container Insights 애드온, 메트릭 필터, 알람, SNS, 대시보드
```

compute 는 `up.ps1`/Actions `infra` 워크플로가 올릴 때 함께 올라간다(base 를 먼저 apply 해 두어야 `fluent_bit_role_arn` 출력이 있다).

```powershell
kubectl -n logging get pods                                   # aws-for-fluent-bit 노드 수만큼 Running
kubectl -n amazon-cloudwatch get pods                         # cloudwatch-agent DaemonSet
aws logs describe-log-groups --log-group-name-prefix /nesume/dev
aws logs tail /nesume/dev/app --since 10m --format short --filter-pattern '{ $.msg = "http_request" }'
aws logs tail /nesume/dev/audit --since 1h --format short     # 역할 관리 화면에서 역할을 한 번 바꾸면 role_changed 가 온다
aws cloudwatch describe-alarms --alarm-name-prefix nesume-dev --query 'MetricAlarms[].[AlarmName,StateValue]' --output table
```

5xx 알람 시험: 존재하지 않는 DB 호스트로 잠깐 바꾸는 대신, `kubectl -n dev exec deploy/nesume-app -- python -c "import logging; ..."` 로는 접근 로그가 안 남으므로 **ALB 주소로 500 을 내는 요청을 5분 안에 요청 수의 2% 이상** 보내거나(예: 임베더를 잠시 내리고 추천 API 호출), 콘솔에서 알람 상태를 `aws cloudwatch set-alarm-state --alarm-name nesume-dev-5xx-rate --state-value ALARM --state-reason test` 로 바꿔 SNS 수신만 확인한다.

## 5. Logs Insights 저장 쿼리

콘솔 Logs Insights → 저장된 쿼리 → `nesume-dev/` 아래. 같은 내용:

요청 추적 (`/nesume/dev/app`, `/nesume/dev/audit`):

```
fields @timestamp, @logStream, level, logger, msg, status, duration_ms, user_id, role
| filter request_id = "REQUEST_ID_HERE"
| sort @timestamp asc
```

5xx 요청:

```
fields @timestamp, request_id, method, path, status, duration_ms, user_id, role
| filter msg = "http_request" and status >= 500 and (isblank(is_test) or is_test = 0)
| sort @timestamp desc | limit 100
```

느린 라우트 p95:

```
filter msg = "http_request" and (isblank(is_test) or is_test = 0)
| stats count() as requests, pct(duration_ms, 95) as p95_ms, avg(duration_ms) as avg_ms by method, path
| sort p95_ms desc | limit 30
```

사용자별 차단 (`/nesume/dev/audit`, B11 이 로그 스트림에 남긴 뒤):

```
filter decision = "block" and (isblank(is_test) or is_test = 0)
| stats count() as blocks by user_id, role
| sort blocks desc | limit 20
```

예외 스택:

```
fields @timestamp, request_id, logger, msg, exc
| filter level = "ERROR" or ispresent(exc)
| sort @timestamp desc | limit 50
```

## 6. 비용 메모

Fluent Bit·Container Insights(enhanced) 는 dev 노드 3대 기준 월 수 달러 수준(로그 수집 GB 당 과금 + 메트릭). 앱 로그 보존 30일, 라벨·주석 제외, 기본 애드온 로그 수집은 꺼 둬서(이중 전송 방지) 양을 줄였다. 비용이 걱정되면 `/nesume/dev/app` 보존을 14일로(`infra/modules/logs` 변수).
