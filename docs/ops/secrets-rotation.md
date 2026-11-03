# 시크릿 교체 (D18)

D용. 어떤 비밀값이 어디 있고, 언제·어떻게 바꾸고, 바꾼 뒤 무엇을 재기동해야 하는지. 설정·비밀값 구조는 `dev-cluster.md` 6장.

## 승인 기록

| 버전 | 날짜 | 작성 | 리뷰·승인 | 비고 |
|---|---|---|---|---|
| v1 | 2026-11-03 | D | _(팀 리뷰 후 기입: 날짜·승인자)_ | 최초 작성 |

---

## 1. 주기와 원칙

- **정기: 분기 1회**(1·4·7·10월 첫 주). 2장 표에서 "정기" 인 항목.
- **즉시: 유출 의심 시**(저장소·채팅·로그에 값이 보임, CloudTrail 에 모르는 `GetSecretValue`, 팀원 이탈). 분기 주기와 무관하게 그날 바꾼다. 사고로 다루면 `incident-response.md` 6장.
- 값은 저장소·values·로그·Discord 에 적지 않는다(CI gitleaks 가 잡는다). 전달이 필요하면 1:1 메시지로, 받은 쪽이 확인하면 지운다.
- 비밀값은 **Secrets Manager 가 원본**이다. K8s Secret `nesume-secret` 은 ExternalSecret 이 1시간마다 복사해 오는 사본이다.
- 교체 후 5장 기록 표에 한 줄(값은 적지 않는다).

---

## 2. 목록

| 비밀값 | 저장 위치 | 쓰는 곳 | 주기 | 교체 절차 | 재기동 | 교체 중 영향 |
|---|---|---|---|---|---|---|
| `DB_PASSWORD` | SM `nesume/dev/app` | RDS 마스터, app·migrate·batch 파드 | 정기 | 4.1 | app 재시작 | 반영~재시작 사이 **새 DB 연결 실패**(1~3분) |
| 시드 계정 비밀번호(`SEED_PASSWORD`) · `svc-batch`(`BATCH_PASSWORD`) | SM `nesume/dev/seed`, `nesume/dev/app` | Cognito 시드 계정 5개, B16 러너 | 정기 + 팀원 이탈 | 4.2 | 없음 | 기존 로그인 세션 끊김 |
| Cognito client secret | — | — | — | 4.3 (**없음**: 두 클라이언트 모두 `generate_secret = false`) | — | — |
| Discord/Slack 웹훅 `ALERTS_WEBHOOK_URL` | SM `nesume/dev/app` | Lambda `nesume-dev-webhook-notifier` | 정기 | 4.4 | Lambda 콜드 스타트 | 교체 중 알림 수 초 유실 가능 |
| 공공 API 키 `WORK24_*_API_KEY`(5개) · `SEOUL_OPENAPI_KEY` · `KMOOC_API_KEY` | SM `nesume/dev/app` | CronJob `nesume-jobs-collector` | 발급처 만료 전 + 유출 시 | 4.5 | 없음(다음 실행) | 없음 |
| WAF 평가 토큰 | SM `nesume/dev/eval-waf-token` (Terraform 생성) | WAF Rate Limit 예외, B16 러너 `EVAL_WAF_TOKEN` | 정기 | 4.6 | 없음 | 러너가 새 값을 받기 전까지 Rate Limit 대상 |
| IAM 사용자 액세스 키 | 각자 PC `~/.aws/credentials` | 팀원 CLI·kubectl | 정기(본인) | 4.7 | 없음 | 없음 |
| GitHub Actions → AWS | 없음(OIDC 역할 `nesume-github-ci`) | CI | — | 교체할 키 없음 | — | — |
| KMS 키(PII·감사 로그·CloudTrail) | KMS | S3·필드 암호화·로그 그룹 | 매년 자동 | `enable_key_rotation = true`. 할 일 없음 | — | — |

---

## 3. 공통 도구

### 3.1 시크릿 JSON 의 키 하나만 바꾸기

`nesume/dev/app` 은 여러 키가 든 JSON 하나다. 통째로 덮으면 다른 키가 사라지므로 **읽고 → 한 키만 바꾸고 → 다시 쓴다.** 값이 화면·셸 기록에 남지 않게 입력은 숨김 프롬프트로 받는다. Git Bash 에서:

```bash
export AWS_PROFILE=nesume
python - nesume/dev/app DB_PASSWORD <<'EOF'
import getpass, json, subprocess, sys
sid, key = sys.argv[1], sys.argv[2]
aws = ["aws", "secretsmanager"]
cur = json.loads(subprocess.check_output(aws + ["get-secret-value", "--secret-id", sid, "--query", "SecretString",
                                                "--output", "text"], text=True).lstrip("﻿"))
if key not in cur:
    sys.exit(f"{key} 가 {sid} 에 없다. 새 키 추가는 의도한 경우에만 코드를 고쳐서")
cur[key] = getpass.getpass(f"new {key}: ").strip()
subprocess.run(aws + ["put-secret-value", "--secret-id", sid, "--secret-string", json.dumps(cur)],
               check=True, stdout=subprocess.DEVNULL)
print(f"{sid}: {key} updated ({len(cur)} keys kept)")
EOF
```

- PowerShell 5.1 의 `>` 리다이렉트로 JSON 을 파일에 저장했다가 다시 올리지 않는다. UTF-16/BOM 으로 저장돼 ESO·Lambda 가 못 읽는다.
- 무작위 값 만들기: `python -c "import secrets; print(secrets.token_urlsafe(24))"` (RDS 가 거부하는 `/ @ " 공백` 이 없다).
- 직전 값으로 되돌리기: Secrets Manager 는 이전 버전을 `AWSPREVIOUS` 로 남긴다. 그 내용을 새 버전으로 다시 올린다(값이 화면에 나오지 않는다).

  ```bash
  aws secretsmanager get-secret-value --secret-id nesume/dev/app --version-stage AWSPREVIOUS --query SecretString --output text \
    | python -c "import subprocess,sys; subprocess.run(['aws','secretsmanager','put-secret-value','--secret-id','nesume/dev/app','--secret-string',sys.stdin.read().strip()],check=True,stdout=subprocess.DEVNULL); print('restored AWSPREVIOUS')"
  ```

### 3.2 ESO 즉시 동기화 + 재기동

ExternalSecret 은 1시간 주기(`refreshInterval: 1h`)다. 바로 반영하려면:

```bash
kubectl -n dev annotate externalsecret nesume-secret force-sync=$(date +%s) --overwrite
kubectl -n dev get externalsecret nesume-secret        # STATUS SecretSynced, READY True
kubectl -n dev rollout restart deploy/nesume-app       # 환경변수는 파드 시작 때만 읽힌다
kubectl -n dev rollout status deploy/nesume-app
```

- CronJob·hook Job 은 **다음 실행 때** 새 Secret 을 읽는다. 재기동할 것이 없다.
- web 파드는 비밀값을 쓰지 않는다.

---

## 4. 항목별 절차

### 4.1 DB 비밀번호

**언제** 분기 1회, 유출 의심 즉시. **누가** D. **영향** Postgres 는 비밀번호가 바뀌어도 이미 열린 연결을 끊지 않는다. 문제는 그 사이 새로 여는 연결(풀 확장·재시작한 파드)이다. 사용자가 적은 시간에 하고 팀 채널에 5분 공지.

1. 새 값 생성 후 3.1 로 `nesume/dev/app` 의 `DB_PASSWORD` 교체.
2. RDS 에 반영 — compute 레이어가 Secrets Manager 값을 읽어 RDS 마스터 비밀번호로 쓴다(`apply_immediately = true`). **`-target` 으로 RDS 만** 적용한다. 그냥 `apply` 하면 tfvars 에 없는 `webhook_alerts_enabled`·`alert_email` 이 기본값으로 돌아가 알림 Lambda 가 지워진다.

   ```bash
   terraform -chdir=infra/envs/dev/compute plan  -target=module.rds    # aws_db_instance.this 1개 update in-place(password) 만 나와야 한다
   terraform -chdir=infra/envs/dev/compute apply -target=module.rds
   aws rds wait db-instance-available --db-instance-identifier nesume-dev
   ```

3. 3.2 로 동기화 + app 재시작.

**확인**

```bash
curl -sS "http://<ALB>/api/ready"                                       # db: ok
kubectl -n dev logs deploy/nesume-app --since=5m | grep -i "password authentication failed"   # 아무것도 없어야 한다
```

다음 배포의 migrate Job·내일 새벽 수집 CronJob 이 성공하는지 한 번 더 본다. 실패하면 Secret 동기화부터 확인.

**되돌리기** 3.1 의 `AWSPREVIOUS` → 2번 다시 → 3.2.

### 4.2 시드 계정 · 배치 계정 비밀번호

계정: `test-user1@` `test-user2@`(user) `test-mentor1@`(mentor) `test-operator1@`(operator) `svc-batch@`(system). 도메인은 `example.com`(`SEED_EMAIL_DOMAIN`). 전부 `test` 그룹.

**언제** 분기 1회, 비밀번호를 아는 팀원이 이탈했을 때 즉시. **누가** D.

1. 새 값 생성. Secrets Manager 갱신:

   ```bash
   aws secretsmanager put-secret-value --secret-id nesume/dev/seed --secret-string "$(python -c "import getpass,json; print(json.dumps({'SEED_PASSWORD': getpass.getpass('new SEED_PASSWORD: ')}))")"
   ```

   `svc-batch` 는 앱 시크릿의 `BATCH_PASSWORD` 와 같아야 하므로 3.1 로 `nesume/dev/app` `BATCH_PASSWORD` 도 같은 값으로. (현재 앱·배치 코드는 `BATCH_PASSWORD` 를 쓰지 않는다. 배치는 Pod Identity 와 DB 로 직접 일한다. 그래도 계약상 맞춰 둔다.)
2. Cognito 에 반영 + 기존 세션 끊기:

   ```bash
   POOL=ap-northeast-2_jFqNdpDUg
   read -rsp "new password: " NEW; echo
   for u in test-user1 test-user2 test-mentor1 test-operator1 svc-batch; do
     aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$u@example.com" --password "$NEW" --permanent
     aws cognito-idp admin-user-global-sign-out --user-pool-id "$POOL" --username "$u@example.com"
   done
   unset NEW
   ```

   또는 시드 스크립트로(멱등. 그룹 소속도 다시 맞춘다): `SEED_PASSWORD` 를 넣고 `python -m app.auth.seed`(`app/app/auth/seed.py` 머리 주석).
3. 새 비밀번호를 쓰는 사람(러너 담당 B, 시연 담당)에게 1:1 로 전달.

**확인** 웹에서 `test-user1@example.com` 새 비밀번호로 로그인 → 성공, 옛 비밀번호 → 실패.

### 4.3 Cognito 앱 클라이언트

교체할 client secret 이 **없다**. `web`(SRP) 과 `runner`(USER_PASSWORD_AUTH) 모두 public 클라이언트(`generate_secret = false`)이고 앱은 토큰을 JWKS 로 검증만 한다(`infra/modules/cognito/main.tf`).

유출 대응이 필요한 것은 클라이언트가 아니라 **사용자 토큰**이다:
- 특정 사용자: 역할 변경 화면이나 `aws cognito-idp admin-user-global-sign-out` → 리프레시 토큰 무효. 액세스 토큰까지 즉시 막으려면 역할 재저장(서버가 `users.token_not_before` 를 갱신해 기존 토큰 401).
- 클라이언트 ID 자체를 바꿔야 할 때(예: 클라이언트 설정이 오용됨): Terraform 으로 새 클라이언트 추가 → `COGNITO_CLIENT_IDS` 에 새·옛 ID 둘 다 넣어 배포 → web 이 새 ID(`COGNITO_WEB_CLIENT_ID`)로 전환 → 하루 뒤 옛 ID 제거. 두 단계 배포라 사용자 로그아웃 없이 바뀐다.

나중에 confidential 클라이언트(secret 있음)를 추가하면 그 secret 은 Secrets Manager 에 두고 이 문서 2장에 행을 추가한다.

### 4.4 Discord(또는 Slack) 웹훅

**언제** 분기 1회, URL 이 어디든 노출됐으면 즉시(URL 만 있으면 누구나 채널에 글을 쓸 수 있다). **누가** D(Discord 채널 관리 권한 필요).

1. Discord 채널 설정 → 연동 → 웹훅 → **새 웹훅** 생성 → URL 복사. 옛 웹훅은 아직 지우지 않는다.
2. 3.1 로 `ALERTS_WEBHOOK_URL` 교체.
3. Lambda 는 URL 을 실행 환경 수명 동안 캐시한다. 설정을 한 번 바꿔 새 실행 환경을 띄운다:

   ```bash
   aws lambda update-function-configuration --function-name nesume-dev-webhook-notifier \
     --description "webhook rotated $(date +%F)" >/dev/null
   aws lambda wait function-updated --function-name nesume-dev-webhook-notifier
   ```

4. 시험 발송:

   ```bash
   aws sns publish --topic-arn arn:aws:sns:ap-northeast-2:852138520969:nesume-dev-alerts \
     --subject "[nesume-dev] INFO alarm" --message '{"type":"alarm","severity":"info","summary":"웹훅 교체 점검","env":"dev"}'
   ```

5. 새 웹훅으로 메시지가 오면 Discord 에서 **옛 웹훅 삭제**. 이게 실제 무효화다.

앱 파드는 SNS 가 설정돼 있으면 웹훅을 직접 쓰지 않으므로 재기동하지 않는다.

**확인** 안 오면 `aws logs tail /aws/lambda/nesume-dev-webhook-notifier --since 10m`.

### 4.5 공공 API 키

| 키 | 발급처 |
|---|---|
| `WORK24_JOB_API_KEY`, `WORK24_TRAINING_API_KEY`, `WORK24_OCCUPATION_API_KEY`, `WORK24_DUTY_API_KEY`, `WORK24_COMMON_CODE_API_KEY` | 고용24 Open API |
| `SEOUL_OPENAPI_KEY` | 서울 열린데이터광장 |
| `KMOOC_API_KEY` | 공공데이터포털(K-MOOC) |

**언제** 발급처 만료 안내를 받았을 때, 유출 시. **누가** D(발급 계정 소유자와 함께).

1. 발급처에서 재발급(가능하면 옛 키는 새 키 확인 뒤 폐기).
2. 3.1 로 해당 키 교체.
3. 3.2 의 force-sync 만(app 재시작 불필요. 수집은 CronJob 이 한다).
4. 바로 확인하려면 수동 1회 실행:

   ```bash
   kubectl -n dev create job --from=cronjob/nesume-jobs-collector nesume-jobs-collector-manual-$(date +%m%d%H%M)
   kubectl -n dev logs -f job/nesume-jobs-collector-manual-<위 이름 끝>
   ```

**확인** 로그에 해당 소스 `FAILED` 가 없다. 발급처 쪽 옛 키 폐기.

### 4.6 WAF 평가 토큰

Terraform 이 만든 무작위 값이다. 손으로 Secrets Manager 를 바꾸면 WAF 규칙과 어긋난다 → **반드시 Terraform 으로**.

```bash
terraform -chdir=infra/envs/dev/base plan  -replace="module.waf.random_password.eval_token"
terraform -chdir=infra/envs/dev/base apply -replace="module.waf.random_password.eval_token"
```

plan 에 `random_password` 교체, `aws_secretsmanager_secret_version` 교체, `aws_wafv2_web_acl` 수정 3개만 나와야 한다. 러너 담당(B)에게 새 값을 받아 가라고 알린다:

```bash
aws secretsmanager get-secret-value --secret-id nesume/dev/eval-waf-token --query SecretString --output text   # EVAL_WAF_TOKEN 에 넣는다. 출력하지 말고 바로 환경변수로
```

### 4.7 IAM 사용자 액세스 키 (각자)

**언제** 분기 1회 본인이, 노트북 분실·키 노출 시 즉시. 이탈자 키는 D 가 비활성화.

```bash
aws iam list-access-keys --profile nesume                       # 지금 키 ID
aws iam create-access-key --profile nesume                       # 새 키. 출력은 바로 aws configure 로
aws configure --profile nesume                                   # 새 키 입력
aws sts get-caller-identity --profile nesume                     # 새 키로 되는지
aws iam update-access-key --access-key-id <옛 키 ID> --status Inactive --profile nesume
aws iam delete-access-key --access-key-id <옛 키 ID> --profile nesume   # 하루 써 보고 삭제
```

본인 키만 다룰 수 있다(`nesume-self-manage` 정책). 키는 사람당 최대 2개.

---

## 5. 교체 기록

값은 적지 않는다. 날짜·항목·사유·수행자·확인 결과만.

| 날짜 | 항목 | 사유(정기/유출 의심/이탈) | 수행 | 확인 |
|---|---|---|---|---|
| | | | | |

## 6. 리허설

완료 기준: 신규 팀원이 이 문서만 보고 dev 에서 **4.4(웹훅)** 또는 **4.2(시드 비밀번호)** 를 한 번 수행한다. DB 비밀번호(4.1)는 D 가 함께한다.

| 날짜 | 수행자 | 항목 | 걸린 시간 | 문서에서 막힌 곳 |
|---|---|---|---|---|
| | | | | |
