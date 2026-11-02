# dev 클러스터 사용 안내 (D9)

팀원용. EKS `nesume-dev`에 배포된 dev 환경을 쓰고, 보고, 고치는 법. 올리고 내리는 쪽(Terraform)은 `infra/README.md`가 기준이고 D가 한다.

## 1. 언제 켜져 있나

- 평일 낮에만. 매일 00:00 KST 에 Actions `infra` 워크플로가 자동으로 내린다(스케줄은 수십 분 늦을 수 있다). 올리는 데 15~20분, 내리는 데 10분.
- 올리기: 저장소 **Actions → infra → Run workflow → `up`**. 저장소 write 권한이면 누구나 누를 수 있다. 끝나면 그 run 의 Summary 에 ALB 주소가 나온다. 같은 화면에서 `down` 을 고르면 바로 내린다. 안 되면 D에게 요청.
- 내리면 **dev DB도 같이 사라진다.** 다음 날은 빈 DB에서 마이그레이션만 적용된 상태. 테스트 데이터는 시드(D6)로 다시 만든다.
- 노드는 스팟이라 가끔 회수된다. 파드가 재시작되는 건 정상이다. app은 2개라 서비스는 끊기지 않는다.

## 2. 주소

`http://<ALB DNS>/`. **HTTP이고 올릴 때마다 바뀐다.** 공지 채널 고정 메시지가 기준이고, 직접 확인하려면:

```powershell
kubectl -n dev get ingress nesume -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

- 프론트 `/`, API `/api/...`. 프론트 API 베이스는 상대 경로 `/api`라 주소가 바뀌어도 코드 변경 없음.
- `/api/health`는 app 버전(git sha), `/api/ready`는 DB·pgvector·S3 상태.

## 3. 접속 준비 (처음 한 번)

1. 콘솔 우측 상단 이름 → 보안 자격 증명에서 본인 액세스 키 생성(`nesume-self-manage` 정책으로 본인 키만 가능).
2. `aws configure --profile nesume` 에 키 입력. 리전 `ap-northeast-2`.
3. kubeconfig:

```powershell
$env:AWS_PROFILE = "nesume"
aws eks update-kubeconfig --name nesume-dev --region ap-northeast-2
kubectl -n dev get pods
```

클러스터가 내려간 날은 `update-kubeconfig`가 `ResourceNotFoundException`을 낸다. 켜진 뒤 다시 하면 되고 kubeconfig는 그대로 쓸 수 있다(클러스터 이름이 같다. 인증서만 갱신되므로 매일 올라올 때마다 한 번 다시 실행).

## 4. 권한 범위

액세스 엔트리(Terraform)로 IAM 사용자마다 붙는다. CLI로 추가하면 다음 날 사라지니 D에게 요청한다.

| 할 수 있음 | 할 수 없음 |
|---|---|
| 클러스터 전체 조회(`get`, `describe`, `logs`) | `kube-system`·`external-secrets` 등 다른 네임스페이스 수정·삭제 |
| `dev` 네임스페이스 리소스 수정·삭제(`rollout restart`, `delete pod`, `scale`) | 노드·클러스터·CRD·ClusterSecretStore 변경 |
| `exec`로 파드 안 들어가기 | `helm upgrade`(ClusterSecretStore가 클러스터 스코프라 거부됨. 배포는 D 또는 CI) |

확인:

```powershell
kubectl auth can-i delete deploy -n dev          # yes
kubectl auth can-i delete deploy -n kube-system  # no
```

## 5. 자주 쓰는 명령

```powershell
kubectl -n dev get pods                                   # app 2/2, web 1/1, migrate Completed
kubectl -n dev logs deploy/nesume-app -f                  # app 로그(json). --since=10m
kubectl -n dev logs deploy/nesume-web --tail=100          # nginx 접근 로그
kubectl -n dev logs job/nesume-migrate                    # 마이그레이션 실패 원인
kubectl -n dev rollout restart deploy/nesume-app          # 재시작
kubectl -n dev exec deploy/nesume-app -- python -c "..."  # 파드 안에서 한 줄 실행
kubectl -n dev describe pod <이름>                         # Pending·CrashLoop 원인은 Events
kubectl top pods -n dev                                   # CPU·메모리
helm -n dev history nesume                                # 배포 이력
kubectl -n dev get externalsecret,secret                  # 비밀값 동기화 상태
kubectl -n dev get pods -l app.kubernetes.io/component=embedder   # D20 임베딩 서비스(1/1). 전용 노드가 뜨고 모델 로드까지 3~5분
kubectl -n dev port-forward svc/nesume-embedder 8081:8080         # 로컬에서 POST :8081/embed 로 직접 확인
```

DB에 직접 붙어야 하면 app 파드를 통한다(RDS는 클러스터 SG에서만 열려 있다):

```powershell
kubectl -n dev exec -it deploy/nesume-app -- python -c "from app.db import engine; print(engine.url)"
```

## 6. 설정과 비밀값

- 비밀 아닌 설정은 `deploy/nesume/values-dev.yaml`의 `config.*` → ConfigMap → 환경변수. 바꾸려면 PR + D 리뷰.
- 비밀값은 Secrets Manager `nesume/dev/app`. **JSON 키 이름이 곧 환경변수 이름.** 새 비밀값이 필요하면 D에게 키 이름을 알려 주면 시크릿에 추가하고 ExternalSecret이 1시간 안에 가져온다. 바로 반영하려면:

```powershell
kubectl -n dev annotate externalsecret nesume-secret force-sync=$(Get-Date -UFormat %s) --overwrite
kubectl -n dev rollout restart deploy/nesume-app
```

- 배치 파드(`nesume-batch` SA)는 Secrets Manager만 접근 가능하다. S3가 필요하면 D에게 역할 정책 추가 요청.
- 임베딩(D20): `EMBEDDING_URL`(`http://nesume-embedder:8080`)·`EMBEDDING_MODEL`(`bge-m3`)이 ConfigMap으로 들어간다. 서비스는 클러스터 안에서만 열려 있고 `POST /embed {"inputs":[...]}`로 1024차원 벡터를 준다. 전용 노드(`nesume-dev-embedding`, 온디맨드 1대)에서만 돌며 다른 파드는 그 노드에 올라가지 않는다. 자세한 것은 `embedder/README.md`.
- 로그는 D14 전까지 `kubectl logs`. 이후 CloudWatch `/nesume/dev/app`.

## 7. 자주 나는 오류

| 증상 | 원인·조치 |
|---|---|
| `kubectl` `Unauthorized` / `the server has asked for the client to provide credentials` | `AWS_PROFILE` 미설정, 또는 클러스터가 오늘 새로 올라와 kubeconfig 인증서가 옛것. `update-kubeconfig` 다시 |
| `kubectl` `connection refused` / `no such host` | 클러스터가 내려가 있다. 1절 |
| `forbidden: User ... cannot ...` | 권한 밖. 4절. `dev` 밖이거나 액세스 엔트리에 아직 없음(D에게) |
| 주소가 안 열림 | ALB 주소가 바뀌었다. 2절 명령으로 다시 확인. 올린 직후면 ADDRESS 채워지는 데 2~3분 |
| ALB 503 | web 파드가 아직 Ready 아님. `kubectl -n dev get pods` |
| `/api/ready` 500, `db: error` | migrate Job 실패 또는 RDS 아직 생성 중. `logs job/nesume-migrate` |
| app `CrashLoopBackOff` | `kubectl -n dev logs deploy/nesume-app --previous`. 설정 누락이면 `ValidationError`에 필드명이 나온다 |
| 파드 `Pending` 오래 | 스팟 노드 회수 뒤 재배치 중(1~3분). `kubectl get nodes`가 2대 미만이면 D에게 |
| 방금 넣은 비밀값이 안 보임 | ExternalSecret은 1시간 주기. 6절 force-sync 후 restart |
| `ImagePullBackOff` | ECR에 그 태그가 없다. 배포는 D/CI 몫이므로 D에게 |

## 8. 배포 흐름(참고)

- 클러스터 올리기·내리기 → `infra.yml`(D11). `up` 은 Terraform compute apply → 애드온 대기 → ECR 태그(main sha 우선, 없으면 최신) → `helm upgrade --install` → `/api/health` 확인. `down` 은 `helm uninstall` → ALB 소멸 대기 → `terraform destroy` → NAT·EIP·EKS·RDS·ALB 잔존 확인(남으면 실패로 표시). 매일 00:00 KST 자동 `down`.
- main push → `ci.yml`(D11)이 app·web 이미지를 ECR `nesume/{app,web}:<git sha>`로 올리고, 클러스터가 켜져 있으면 `helm upgrade`(꺼져 있으면 skip, 다음 `up` 이 그 태그를 집는다). `ci.yml` 과 `infra.yml` 은 concurrency 그룹 `infra` 를 공유해 동시에 클러스터를 만지지 않는다.
- `infra/scripts/up.ps1`·`deploy.ps1`·`down.ps1`은 **로컬 체크아웃 상태와 무관하게 origin/main 최신본**으로 동작한다(`_main-src.ps1`이 임시 worktree를 만들어 차트·Terraform·빌드 컨텍스트를 거기서 읽고 끝나면 지운다). 이미지 태그는 origin/main sha를 우선하고, CI가 아직 안 올렸으면 ECR 최신 태그로 내려가며 경고한다. `deploy.ps1`은 ECR에 main sha가 없으면 **CI가 올릴 때까지 기다린다**(기본 20분). 로컬 빌드·푸시는 CI가 고장났을 때 `-LocalBuild`로만 한다(집 회선에서 느리고 타임아웃이 났다, 10-29).
- 마이그레이션은 `pre-upgrade` hook으로 앱보다 먼저 돈다. 되돌릴 수 없는 마이그레이션은 사전에 B와 합의(`docs/dev/backend-guide.md`).
- 롤백은 `helm -n dev rollback nesume <REVISION>`. 마이그레이션은 되돌리지 않는다.
- embedder 이미지(D20)는 별도 워크플로 `embedder.yml`이 `embedder/` 변경 시에만 `nesume/embedder:<sha>`로 올린다. `up.ps1`/`deploy.ps1`은 ECR 최신 embedder 태그를 자동으로 집고, 저장소가 비어 있으면 `embedder.enabled=false`로 배포한다.
