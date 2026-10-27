# infra — nesume AWS 인프라 (Terraform)

계정 `852138520969`(프로필 `nesume`), 리전 `ap-northeast-2`. 콘솔은 확인용으로만 쓰고 모든 변경은 Terraform·CLI로 한다.

## 1. 레이어

```
infra/
├─ bootstrap/            tfstate 버킷·ECR 2개. 로컬 state(백업: s3://nesume-tfstate-852138520969/bootstrap/)
├─ envs/dev/base/        한 번 올리고 안 내린다
├─ envs/dev/compute/     평일 낮만. 매일 내린다
├─ modules/              network storage secrets logs iam cognito | eks rds addons
└─ scripts/              up.ps1 down.ps1
```

| | base (`envs/dev/base`) | compute (`envs/dev/compute`) |
|---|---|---|
| 들어가는 것 | VPC·서브넷·라우트 테이블(NAT 경로 없음)·S3 게이트웨이 엔드포인트, S3 문서 버킷, KMS 키, Secrets Manager 껍데기 2개, CloudWatch 로그 그룹 2개, GitHub OIDC 공급자, IAM 역할 7개, Cognito | NAT+EIP+프라이빗 기본 경로, EKS 1.36(STANDARD), 관리형 애드온 5개, arm64 스팟 노드 2대, 액세스 엔트리, Pod Identity 연결 4개, RDS PostgreSQL 16, Helm(ALB 컨트롤러·External Secrets), `dev` 네임스페이스 |
| state | `s3://nesume-tfstate-852138520969/envs/dev/base.tfstate` | `.../envs/dev/compute.tfstate` |
| 수명 | 상시 (월 5달러 미만) | 올리기 15~20분, 내리기 10분. 켜 두면 시간당 약 0.3달러 |
| 누가 | D (로컬) | D (로컬 `up.ps1`/`down.ps1`) 또는 GitHub Actions (D11) |

의존은 compute → base 한 방향. compute는 `terraform_remote_state`로 base 출력을 읽는다. IAM 역할이 전부 base에 있는 이유: EKS Pod Identity는 신뢰 정책이 `pods.eks.amazonaws.com` 고정이라 클러스터 OIDC id가 필요 없고, 클러스터를 매일 새로 만들어도 역할 ARN이 안 바뀐다.

잠금은 S3 네이티브 lockfile(`use_lockfile = true`, Terraform 1.10+). DynamoDB 테이블은 없다.

## 2. 준비

```powershell
winget install Hashicorp.Terraform TerraformLinters.tflint AquaSecurity.Trivy
$env:AWS_PROFILE = "nesume"
aws sts get-caller-identity --query Account --output text   # 852138520969
```

맥·리눅스는 `brew install terraform tflint trivy helm awscli`, PowerShell 7(`brew install powershell`)로 스크립트를 그대로 실행한다. 이미지는 노드가 arm64라 x86 머신에서는 `docker buildx build --platform linux/arm64`.

## 3. 올리기 · 내리기 (compute)

```powershell
$env:AWS_PROFILE = "nesume"; .\infra\scripts\up.ps1     # 15~20분
$env:AWS_PROFILE = "nesume"; .\infra\scripts\down.ps1   # 10분
```

`up.ps1`: compute apply → kubeconfig → External Secrets 대기 → ClusterSecretStore → ECR 최신 태그 확인(app·web 둘 다 있어야 함) → `helm upgrade --install` → ALB 주소 출력 → `/api/health` 200.

`down.ps1`: `helm uninstall --wait` → Ingress finalizer 삭제 대기 → ALB 소멸 대기 → `terraform destroy` → NAT·EIP·EKS·RDS·ALB 잔존 확인. 마지막 다섯 줄이 전부 `none`이어야 끝난 것이다.

둘 다 `AWS_PROFILE`이 비어 있거나 계정이 다르면 바로 중단한다. 긴 apply 중 콘솔 창을 클릭하면 QuickEdit 선택 모드가 출력을 막는다. Esc 또는 Enter. 절대 Ctrl+C 하지 않는다.

팀원(PowerUserAccess)은 `iam:PassRole`이 없어 compute를 올리고 내릴 수 없다. 클러스터가 필요하면 D 또는 Actions `infra-up`(D11). kubectl은 클러스터 조회 + `dev` 네임스페이스 수정만 된다.

base·bootstrap은 수동으로만 다룬다:

```powershell
terraform -chdir="infra/envs/dev/base" plan     # No changes 여야 정상
terraform -chdir="infra/envs/dev/base" apply
```

## 4. 품질 게이트

```powershell
terraform fmt -recursive -check infra
terraform -chdir="infra/envs/dev/base" validate; terraform -chdir="infra/envs/dev/compute" validate
tflint --chdir infra --init          # 처음 한 번
tflint --recursive --chdir infra
trivy config --severity MEDIUM,HIGH,CRITICAL --exit-code 1 --skip-files "**/tfplan" infra/
terraform -chdir="infra/envs/dev/base" plan      # No changes
```

- tflint는 `infra/.tflint.hcl`(terraform recommended + aws 룰셋).
- trivy MEDIUM 이상은 dev 의도(퍼블릭 EKS 엔드포인트, 퍼블릭 서브넷, 매일 destroy하는 RDS, Flow Logs 비용)라 해당 리소스 위에 `#trivy:ignore:AVD-AWS-xxxx`와 사유 주석을 둔다. 새 예외를 추가할 때도 사유를 같이 적는다. LOW는 참고만.
- `tfplan` 파일을 남겨 두면 trivy가 plan 시점의 옛 코드를 검사하므로 제외한다(`.gitignore`에 있음).

## 5. 증상 → 원인

| 증상 | 원인·조치 |
|---|---|
| `UnauthorizedOperation`, 리전 오류 | `AWS_PROFILE` 미설정 또는 서울 외 리전. SCP가 서울만 허용 |
| compute plan `Unsupported attribute ... outputs` | base `output` 이름 불일치 또는 base apply 전 |
| 노드 `NotReady`·조인 안 됨 | 프라이빗 라우트 테이블에 NAT 경로 없음(`aws_route.private_nat`) |
| 노드그룹 `DEGRADED`, `UnfulfillableCapacity` | 스팟 타입이 하나뿐. `modules/eks`의 `instance_types`는 6개(배치 점수 9/10). `aws ec2 get-spot-placement-scores`로 확인 |
| 파드 `Pending`, `Too many pods` | `m6g/m7g.medium`은 ENI 한도로 노드당 파드 8개. 시스템 파드만 15개. 타입 목록에서 제외돼 있다 |
| 파드 `exec format error` | amd64 이미지. arm64로 빌드 |
| `ImagePullBackOff`, `no basic auth credentials` | 노드 역할에 `AmazonEC2ContainerRegistryPullOnly` 없음 |
| `web ImagePullBackOff ... not found` | ECR `nesume/web`에 그 태그가 없다. app·web 같은 태그로 push |
| `docker login` 400 Bad Request | PS 5.1 파이프 `--password-stdin`이 토큰을 깨뜨린다. `--password (aws ecr get-login-password --region ap-northeast-2)` |
| migrate Job `serviceaccount "nesume-app" not found` | pre-install hook이 release의 SA보다 먼저 돈다. 차트는 첫 설치에서 hook을 끈다(`.Release.IsInstall`) |
| helm install `Ingress ... NotFound` | uninstall 직후 재설치. `kubectl -n dev wait --for=delete ingress/nesume` 후 설치 |
| ESO release failed, `service "external-secrets-webhook" not found`, 이어서 ClusterSecretStore·ExternalSecret 생성 실패 | ALB 컨트롤러의 Service 뮤테이팅 웹훅이 엔드포인트도 없이 ESO의 webhook Service 생성을 막음(동시 설치 경쟁). `enableServiceMutatorWebhook = false`. 실패한 release는 `helm uninstall` 후 재apply |
| ClusterSecretStore webhook `no endpoints available` | 노드가 없다(스팟 미배치). `kubectl get nodes` 먼저 |
| ALB 컨트롤러·ESO `AccessDenied`/`NoCredentialProviders` | Pod Identity 연결의 namespace/SA 이름 불일치, `eks-pod-identity-agent` 없음, 또는 연결보다 파드가 먼저 뜸(파드 재시작) |
| `aws_eks_addon coredns` 타임아웃 | 노드 전에 생성. `depends_on = [aws_eks_node_group.default]` |
| app 로그에 `X-Amz-Security-Token` | `LOG_LEVEL=DEBUG`는 botocore가 자격 증명 헤더를 찍는다. dev도 INFO |
| Bedrock `AccessDeniedException` | IAM Resource에 `inference-profile/global.anthropic.*`와 `foundation-model/anthropic.*` 둘 다 필요. Anthropic 사용 사례 미제출. 모델 id는 `global.` 접두사 |
| RDS 뒤 앱 `password authentication failed` | 시크릿 `DB_PASSWORD`를 apply 뒤에 바꿈. compute를 내리고 다시 올린다 |
| `terraform destroy`가 VPC·서브넷에서 멈춤 | ALB·ENI 잔존. `helm uninstall` → ALB 삭제 확인 후 destroy. 끝까지 안 지워지면 Ingress finalizer 제거 후 로드 밸런서·대상 그룹·보안 그룹 수동 삭제 |
| 다음 날 비용이 0이 아님 | NAT 또는 EIP 잔존. `describe-nat-gateways`, `describe-addresses` |
| EKS 시간당 0.60달러 | 연장 지원 버전. `version = "1.36"`, `upgrade_policy STANDARD` 확인 |
| `Error acquiring the state lock` | 다른 사람이 apply 중. 기다린다. `force-unlock`은 상대가 진짜 끝났을 때만 |
| `explicit deny in a service control policy` | 조직에 미부착 상태의 차단 SCP가 있다. IAM으로는 못 푼다. 조직 관리자에게 문의 |
| kubernetes provider `connection refused localhost:80` | 클러스터가 없는데 state에 k8s 리소스가 남음. `terraform state rm module.addons.kubernetes_namespace.dev` 후 재시도 |
| PS에서 `InputObject[0]:` 프롬프트 | 인자 없는 `echo`는 입력 대기. `Write-Host ""` |
| 스크립트가 terraform 실패 뒤에도 계속 진행 | PS 5.1은 외부 명령 exit code를 Stop으로 안 잡는다. 단계마다 `$LASTEXITCODE` 확인(`Check`) |

## 6. 다른 팀에 알릴 것

- dev 클러스터는 평일 낮에만 켜져 있고 매일 00:00 KST 종료(D11). 필요하면 D에게 요청. 15~20분.
- ALB 주소는 올릴 때마다 바뀐다. 공지 채널 고정 메시지를 갱신한다.
- dev DB는 내릴 때 새로 만든다. 테스트 데이터는 시드 스크립트(D6)로 재생성 가능해야 한다.
- 콘솔·CLI로 EKS·RDS를 직접 만들거나 지우지 않는다(Terraform state 밖이 된다).
