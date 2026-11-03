# 로그 보존 · 조회 권한 (D18)

D·운영자용. 어떤 로그가 어디에 얼마 동안 남고, 계정을 지우면 무엇이 익명화되며, 누가 볼 수 있는지. 로그 형식·쿼리는 `observability.md`, 알림은 `alerts.md`.

## 승인 기록

| 버전 | 날짜 | 작성 | 리뷰·승인 | 비고 |
|---|---|---|---|---|
| v1 | 2026-11-03 | D | _(팀 리뷰 후 기입: 날짜·승인자)_ | 최초 작성. 실측 2026-11-03 |

---

## 1. 보존 기준

| 분류 | 보존 | 근거 |
|---|---|---|
| 감사 로그(누가·언제·무엇을·판정) | **90일** | spec 10.2. 사고 조사·러너 재측정에 분기 단위가 필요 |
| 앱 운영 로그(접근·오류) | **30일** | 장애 조사용. 질의 본문이 없고 양이 많다 |
| 보안 서비스 원본(CloudTrail) | 365일 | 계정 수준 조사. 앱 데이터 없음 |
| 그 밖의 운영 메트릭·네트워크 로그 | 14~30일 | 비용 대비 쓰임 |

규칙: 로그에 **질의 원문·PII·토큰 전체·비밀값을 남기지 않는다**. 사용자 식별은 Cognito `sub`(가명 ID)로만 한다. 보존 기간을 늘리는 변경은 D 리뷰 + 이 문서 갱신.

---

## 2. 저장소별 현황 (2026-11-03 실측)

| 저장소 | 내용 | 보존(설정값) | 암호화 | 정의 위치 |
|---|---|---|---|---|
| CloudWatch `/nesume/dev/audit` | `log_type=audit` 줄: 역할 변경, 세션 차단·해제, 알림 이벤트 | **90일** ✅ | KMS `alias/nesume-dev-audit-logs`(연 1회 자동 교체) | `infra/modules/logs` `audit_retention_in_days` |
| CloudWatch `/nesume/dev/app` | 앱·web·배치·애드온 파드 stdout, 접근 로그 1줄/요청 | **30일** ✅ | 기본(AWS 관리) | `infra/modules/logs` `app_retention_in_days` |
| DB `audit_logs` 테이블 | 요청당 1행(마스킹 텍스트·해시·판정·`doc_grades`·`canary_hit`) | **90일 목표 — 자동 정리 미가동** ⚠️ | RDS 저장소 암호화 | 정리 코드 `app/app/features/audit/retention.py`(실행 스케줄 없음) |
| DB `blocked_sessions` | 세션 차단·해제 이력 | 정리 없음(행 수 적음) | 같음 | 마이그레이션 0025 |
| CloudWatch `aws-waf-logs-nesume-dev` | WAF 판정(헤더 `authorization`·`cookie`·`x-eval-token` 가림) | 14일 ✅ | 기본 | `infra/modules/waf` `log_retention_days` |
| S3 CloudTrail 버킷 | AWS API 호출 기록 | 365일(이전 버전 30일) ✅ | KMS `alias/nesume-dev-cloudtrail` | `infra/modules/security` `trail_retention_days` |
| S3 Config 버킷 | 리소스 구성 이력 | 30일 ✅ | 기본 | `infra/modules/security/config.tf` |
| CloudWatch `/aws/eks/nesume-dev/cluster` | EKS 컨트롤 플레인 `api`·`audit`·`authenticator` (kubectl 누가 무엇을) | **무기한** ⚠️ (~500MB) | 기본 | EKS 가 자동 생성. Terraform 관리 밖 |
| CloudWatch `/aws/containerinsights/nesume-dev/performance` | 노드·파드 성능 이벤트 | **무기한** ⚠️ (~120MB) | 기본 | 애드온이 자동 생성 |
| CloudWatch `/aws/lambda/nesume-dev-webhook-notifier` | 알림 전달 결과 | **무기한** ⚠️ | 기본 | Lambda 가 자동 생성 |
| RDS 자동 백업 | DB 전체 | 1일(dev 비용) | RDS 암호화 | `infra/modules/rds` `backup_retention_period` |

⚠️ 항목은 7장 "미결" 에서 고친다.

확인 명령(Git Bash 는 `MSYS_NO_PATHCONV=1` 필요):

```bash
export AWS_PROFILE=nesume MSYS_NO_PATHCONV=1
aws logs describe-log-groups --query 'logGroups[].[logGroupName,retentionInDays,storedBytes]' --output table
```

---

## 3. 감사 로그 두 갈래

| | DB `audit_logs` | CloudWatch `/nesume/dev/audit` |
|---|---|---|
| 쓰는 곳 | B11 `DbAuditSink`(가드레일 요청 종료 시 1행, 예외 포함) | `nesume.audit.*` 로거(역할 변경, 세션 차단·해제, 알림) |
| 보는 곳 | `/ai-logs` 화면, `GET /audit-logs`(운영자 MFA), 운영 대시보드 | Logs Insights, `aws logs tail` |
| 수정 | DB 트리거: **`user_id` 익명화 UPDATE 와 90일 지난 행 DELETE 만** 허용(B11) | 불변(CloudWatch 는 수정 불가, 보존 만료로만 사라짐) |
| 사고 조사 연결 키 | `request_id` | `request_id` |

---

## 4. 계정 삭제 시 익명화

규칙(spec 10.2, B20): 계정을 지워도 감사 로그는 **지우지 않고 `user_id` 를 익명 토큰(`anon-…`)으로 바꿔 보존**한다. 보안 통계(차단율·사고 이력)가 유지되면서 사람과는 끊긴다.

순서(B20 `app/app/features/deletion/service.py`)
1. 사용자가 삭제 요청 → `users.deleted_at` 기록 + Cognito 사용자 비활성(30일 유예, 철회 가능). 유예 중 로그인·멘토 열람 차단.
2. 30일 뒤 삭제 배치: **감사 로그 `user_id` → `users.anon_id`** → S3 `users/{id}/` 삭제 → 데이터 키 폐기 → 사용자 행 삭제(소유 데이터 연쇄) → 공유 재동기화 → Cognito 사용자 삭제.
3. 검증: `python -m app.features.deletion.verify --e2e`(B23). 감사 로그에 원래 ID 로 된 행 0건.

CloudWatch 로그는 익명화하지 않는다
- `/nesume/dev/app`·`/nesume/dev/audit` 의 `user_id` 는 Cognito `sub` 다. Cognito 사용자가 지워지면 `sub` 를 사람에게 되돌릴 방법이 없어지므로 가명 ID 로 보고, **보존 기간(30·90일)이 지나 자연 삭제**되게 둔다.
- 이메일·이름은 애초에 로그에 남기지 않는다(접근 로그 필드에 없음). 새 로그 줄을 추가하는 PR 은 이 규칙을 리뷰에서 본다.

⚠️ 현재 삭제 배치 CronJob 은 꺼져 있다(`values.yaml` `cronjobs.purge.enabled: false`). 또 values 의 명령 `python -m app.batch.purge` 는 존재하지 않는 모듈이고 실제 진입점은 `python -m app.features.deletion.service` 다. 켜기 전까지 30일 유예가 지난 계정은 수동으로 돌려야 한다(7장).

---

## 5. 조회 권한

| 대상 | 누가 | 어떻게 | 통제 |
|---|---|---|---|
| DB 감사 로그 | **운영자(MFA 세션)만** | `/ai-logs`, `GET /audit-logs` | `require_operator_mfa`. 다른 역할 403 |
| 운영 대시보드 | 운영자(MFA) | `/admin/dashboard` | 같음 |
| CloudWatch `/nesume/dev/audit` | D(인시던트 담당) | Logs Insights | KMS 키 정책은 계정 IAM 에 위임 → **IAM 권한**으로 결정. 원칙: `logs:GetLogEvents`·`StartQuery` 와 `kms:Decrypt`(감사 키)는 D·운영 담당만 |
| CloudWatch `/nesume/dev/app` | 팀 전원 | Logs Insights, `aws logs tail` | IAM. 질의 본문·PII 가 없는 그룹 |
| 파드 로그(최근분) | 팀 전원 | `kubectl -n dev logs` | EKS 액세스 엔트리(클러스터 조회 권한) |
| CloudTrail·GuardDuty·Security Hub | D | 콘솔·CLI | IAM |

- 운영자의 감사 로그 열람은 장애 대응·신고 처리·평가 목적에 한정한다. 마스킹 텍스트만 보이고 원문은 저장돼 있지 않다.
- 권한 점검(분기 1회, D): 팀원 IAM 사용자가 감사 로그 그룹을 읽을 수 있는지

  ```bash
  aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::852138520969:user/<이름> \
    --action-names logs:StartQuery logs:GetLogEvents kms:Decrypt \
    --resource-arns "arn:aws:logs:ap-northeast-2:852138520969:log-group:/nesume/dev/audit:*" \
    --context-entries "ContextKeyName=aws:RequestedRegion,ContextKeyValues=ap-northeast-2,ContextKeyType=string" \
    --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
  ```

  D·운영 담당 외에 `allowed` 가 나오면 그 사용자의 그룹 정책에서 감사 그룹 리소스를 `Deny` 로 뺀다.

---

## 6. 보존 기간 바꾸기

**누가** D. **어떻게** Terraform 변수만. 콘솔에서 바꾸면 다음 apply 때 되돌아간다.

1. `infra/envs/dev/base/main.tf` 의 `module "logs"` 에 `app_retention_in_days`·`audit_retention_in_days` 지정(기본 30·90). 감사 로그를 90일 **밑으로** 줄이는 변경은 보안 리뷰.
2. PR → 머지 → `terraform -chdir=infra/envs/dev/base apply`.
3. 이 문서 2장 표 갱신.

**확인** `aws logs describe-log-groups --log-group-name-prefix /nesume/dev`(Git Bash 는 `MSYS_NO_PATHCONV=1`).

---

## 7. 미결 (D18 기준 남은 일)

| # | 문제 | 해결 | 담당 |
|---|---|---|---|
| 1 | DB `audit_logs` 90일 정리가 스케줄 없이 코드로만 있다 → 90일이 지나도 행이 남는다 | Helm CronJob 추가: `python -m app.features.audit.retention`(하루 1회, 1회 5,000행) | D(차트), B 확인 |
| 2 | 삭제 배치 CronJob 이 꺼져 있고 명령이 틀렸다 | `values.yaml` `cronjobs.purge.command` → `["python","-m","app.features.deletion.service"]`, dev 에서 `enabled: true`. 배치 SA 에 S3·KMS·Cognito(AdminDeleteUser) 권한 확인 | D(차트·IAM), B 확인 |
| 3 | `/aws/eks/nesume-dev/cluster`·`/aws/containerinsights/…/performance`·`/aws/lambda/nesume-dev-webhook-notifier` 무기한 보존 | Terraform `aws_cloudwatch_log_group` 으로 가져와(import) EKS 컨트롤 플레인 90일(kubectl 감사 성격), 나머지 30일 | D |
| 4 | 감사 로그 그룹 조회를 IAM 으로 D·운영 담당에 한정하는지 미점검 | 5장 점검 명령으로 확인 후 그룹 정책 조정 | D |
