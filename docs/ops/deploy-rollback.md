# 배포 · 롤백 (D18)

D·팀원용. 코드가 어떻게 클러스터까지 가는지, 잘못 나갔을 때 어떻게 되돌리는지. 클러스터 올리고 내리기는 `infra/README.md`, 팀원용 kubectl 안내는 `dev-cluster.md`.

## 승인 기록

| 버전 | 날짜 | 작성 | 리뷰·승인 | 비고 |
|---|---|---|---|---|
| v1 | 2026-11-03 | D | _(팀 리뷰 후 기입: 날짜·승인자)_ | 최초 작성 |

---

## 1. 환경 현황

| 환경 | 클러스터 · 네임스페이스 · 릴리스 | values | 배포 방식 | 상태 |
|---|---|---|---|---|
| dev | EKS `nesume-dev` · `dev` · `nesume` | `values-dev.yaml` | main 머지 시 CI 자동 | **운영 중**(상시 가동, 2026-11-02~) |
| staging | — | `values-staging.yaml` | (설계) main 머지 시 자동 + B16 러너 게이트 | 클러스터 없음 |
| production | — | `values-prod.yaml` | (설계) 같은 sha 승격 + 수동 승인 | 클러스터 없음 |

지금 실제로 도는 것은 dev 하나다. 2~4장의 staging·prod 규칙은 환경이 생기면 그대로 적용할 기준이다.

---

## 2. 배포 흐름 (dev, 지금)

```
PR ──▶ ci.yml: changes · lint · test · security(gitleaks·의존성·Trivy config·LLM 직접호출 grep)
 │       리뷰 승인(CODEOWNERS: infra/ deploy/ .github/ core/ auth/ policy/ 는 D)
 ▼
main 머지 ──▶ build-deploy (OIDC, 저장소에 AWS 키 없음, concurrency 그룹 infra)
               1. 이미지 태그 = 커밋 sha 앞 7자리. ECR nesume/{app,web}:<sha> (IMMUTABLE, 있으면 건너뜀)
               2. Trivy 이미지 스캔 HIGH/CRITICAL → 걸리면 배포 중단(이미지는 ECR 에 남음)
               3. 클러스터 꺼져 있으면 여기서 끝(다음 up 이 이 sha 를 집는다)
               4. helm upgrade --install nesume -f values-dev.yaml --set-string image.*.tag=<sha> --wait
                    ├ pre-upgrade hook: migrate Job (alembic upgrade head) — 실패하면 앱은 안 바뀐다
                    ├ app·web 롤링 업데이트 (app 2개, PDB minAvailable 1)
                    └ post hook: canary-seed Job (멱등)
               5. /api/health 가 <sha> 를 돌려줄 때까지 3분 확인. 아니면 실패
```

수동 배포(CI 고장·재시도): D 가 `infra/scripts/deploy.ps1`. 로컬 체크아웃 상태와 무관하게 origin/main 기준이며, ECR 에 main sha 가 없으면 CI 가 올릴 때까지 기다린다.

```powershell
$env:AWS_PROFILE = "nesume"
.\infra\scripts\deploy.ps1
```

팀원은 `helm upgrade` 권한이 없다(ClusterSecretStore 가 클러스터 스코프). 배포는 main 머지로만 한다.

---

## 3. 승인 규칙

| 환경 | 누가 승인 | 무엇을 근거로 |
|---|---|---|
| dev | PR 리뷰어 1명 이상(CODEOWNERS 경로는 D) | CI 녹색 |
| staging (설계) | 자동 | main 머지 + CI 녹색 |
| production (설계) | D + 해당 기능 파트 1명. GitHub Environment `production` 의 required reviewers | staging 에서 **같은 sha** 로 B16 러너 통과(차단율 ≥ 95%, 과차단율 ≤ 5%), 미해결 SEV1·SEV2 없음 |

배포를 멈추는 경우: 사고 대응 중 격리 상태(`incident-response.md` 3.2)일 때는 스레드에 "main 머지 중지" 를 걸고, 해제될 때까지 머지하지 않는다. CI 가 values 기준으로 다시 배포하면서 임시 조치(예: `LLM_PROVIDER=none`)를 덮어쓰기 때문이다.

---

## 4. 이미지 승격 규칙

- 태그는 **git sha 하나**. `latest`·`stable` 같은 움직이는 태그는 쓰지 않는다.
- ECR 은 **IMMUTABLE**. 같은 sha 를 다시 빌드해 덮어쓸 수 없다. 재실행은 이미 있는 이미지를 그대로 쓴다.
- staging → production 은 **다시 빌드하지 않고 같은 sha 를 그대로** 올린다(빌드 시점 의존성 차이로 "staging 에서 검증한 것과 다른 바이너리" 가 나가는 것을 막는다). 바뀌는 것은 values 파일뿐이다.
- 승격 대상은 Trivy 게이트를 통과한 sha 만. 스캔에 걸린 sha 는 ECR 에 남아도 배포하지 않는다.
- embedder 는 `embedder.yml` 이 `embedder/` 변경 때만 빌드해 app 과 sha 가 다르다. 배포 때 ECR 최신 embedder 태그를 집는다.

배포된 sha 확인:

```bash
kubectl -n dev get deploy nesume-app nesume-web -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'
curl -sS "http://$(kubectl -n dev get ingress nesume -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/api/health"
```

---

## 5. 롤백

### 5.1 언제

- 배포 직후 5xx·p95 알람, `/api/ready` 실패, 기능 회귀가 **이번 배포 이후 시작**됐다.
- 고칠 수 있는 PR 이 30분 안에 안 나온다. 바로 고칠 수 있으면 전진 수정(5.4)이 낫다.
- 원인이 마이그레이션이면 5.3 을 먼저 읽는다.

### 5.2 helm rollback (D)

```bash
export AWS_PROFILE=nesume              # PowerShell 이면 $env:AWS_PROFILE = "nesume"
aws eks update-kubeconfig --name nesume-dev --region ap-northeast-2

helm -n dev history nesume --max 10    # REVISION·UPDATED·STATUS·DESCRIPTION. 직전 정상 리비전을 고른다
helm -n dev get values nesume --revision <REVISION>   # image.app.tag / image.web.tag = 그 리비전의 sha
helm -n dev rollback nesume <REVISION> --wait --timeout 10m
```

**확인**

```bash
helm -n dev history nesume --max 3                      # 맨 위 STATUS deployed, DESCRIPTION "Rollback to <REVISION>"
kubectl -n dev rollout status deploy/nesume-app
curl -sS "http://<ALB>/api/health"                       # 되돌린 sha
curl -sS "http://<ALB>/api/ready"                        # db·pgvector·s3 ok
```

**그다음 반드시**: main 에서 원인 커밋을 `git revert` 하는 PR 을 올려 머지한다. 안 하면 **다음 main 머지 때 CI 가 문제의 코드를 다시 배포**한다. revert 머지 전까지는 3장 "main 머지 중지" 를 건다.

롤백이 하지 않는 것
- **마이그레이션을 되돌리지 않는다.** migrate Job 은 `pre-upgrade` hook 이라 rollback 때는 돌지 않는다. DB 는 최신 스키마 그대로, 앱만 이전 코드다.
- canary-seed 도 돌지 않는다(미끼는 이미 있으므로 문제없음).
- Secrets Manager 값·ConfigMap 외부 변경은 되돌리지 않는다.

### 5.3 DB 마이그레이션이 얽힌 경우

| 상황 | 할 일 |
|---|---|
| migrate Job 이 **실패**해 배포가 멈췄다 | 앱은 이전 버전 그대로 돌고 있다. `kubectl -n dev logs job/nesume-migrate` 로 원인 → 수정 PR. 롤백 불필요 |
| 마이그레이션은 성공, 새 앱이 문제 | 이전 앱이 새 스키마에서 도는지 B 와 확인 후 5.2. **추가형**(컬럼·테이블 추가, nullable)이면 대개 된다 |
| 마이그레이션 자체가 문제(데이터 변형·컬럼 삭제·NOT NULL 추가) | **되돌리지 않고 전진 수정**(5.4). `alembic downgrade` 는 dev 에서도 D + B 합의 없이는 실행하지 않는다 |

마이그레이션 작성 원칙(B 와 합의, `docs/dev/backend-guide.md`)
- 한 배포에서 **추가 → 다음 배포에서 사용 → 그다음 배포에서 옛것 제거**(expand → migrate → contract). 그러면 어느 단계에서 앱을 롤백해도 스키마와 맞는다.
- 컬럼 삭제·이름 변경·타입 축소는 비가역으로 본다. PR 설명에 "비가역" 표시 + D 리뷰.
- 비가역 마이그레이션 배포 전에 수동 스냅샷:

  ```bash
  aws rds create-db-snapshot --db-instance-identifier nesume-dev --db-snapshot-identifier nesume-dev-pre-<sha>
  aws rds wait db-snapshot-available --db-snapshot-identifier nesume-dev-pre-<sha>
  ```

  dev RDS 자동 백업 보존은 **1일**이다(비용). 스냅샷 복원은 새 인스턴스가 생기고 주소가 바뀌므로 D 가 compute apply(`snapshot_identifier`)로 한다 — 마지막 수단.

### 5.4 전진 수정 (forward fix)

비가역 마이그레이션 뒤, 또는 고치는 게 더 빠를 때.

1. 원인 수정 PR(새 마이그레이션이 필요하면 **새 리비전**으로. 이미 적용된 리비전 파일을 고치지 않는다).
2. 리뷰는 평소대로, CI 녹색.
3. 머지 → CI 배포 → 4장 확인 명령으로 새 sha 확인.

### 5.5 D 가 없을 때 (긴급)

dev 네임스페이스 수정 권한이 있는 팀원은 Deployment 만 직전으로 되돌릴 수 있다.

```bash
kubectl -n dev rollout history deploy/nesume-app
kubectl -n dev rollout undo deploy/nesume-app            # web 도 필요하면 deploy/nesume-web
kubectl -n dev rollout status deploy/nesume-app
```

helm 이 모르는 변경이라 다음 배포 때 덮어써진다. 스레드에 남기고 D 가 5.2 로 정리한다.

---

## 6. 리허설 기록

완료 기준: 신규 팀원이 이 문서만 보고 5.2 를 dev 에서 한 번 수행한다(직전 리비전으로 rollback → 확인 → 다시 최신 리비전으로 rollback).

| 날짜 | 수행자 | 내용 | 걸린 시간 | 문서에서 막힌 곳 |
|---|---|---|---|---|
| | | | | |
