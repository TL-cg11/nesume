# origin/main 최신본으로 dev 전체 기동: compute apply -> kubeconfig -> ESO 대기 -> 이미지 태그 결정 -> helm -> /api/health
# 실행: $env:AWS_PROFILE = "nesume"; .\infra\scripts\up.ps1      (15~20분)
# 로컬 체크아웃의 브랜치·미커밋 상태와 무관하다. 차트·Terraform 은 origin/main 임시 worktree(_main-src.ps1)에서 읽는다.
$ErrorActionPreference = "Stop"
# PS 5.1은 외부 명령(terraform/kubectl/helm)의 실패를 Stop으로 잡지 않는다. 매 단계 exit code를 본다.
function Check($step) { if ($LASTEXITCODE) { throw "$step failed (exit $LASTEXITCODE)" } }
if (-not $env:AWS_PROFILE) { throw "AWS_PROFILE is not set. Run: `$env:AWS_PROFILE = 'nesume'" }
$Account = "852138520969"; $Region = "ap-northeast-2"; $Cluster = "nesume-dev"
if ((aws sts get-caller-identity --query Account --output text) -ne $Account) { throw "wrong AWS account (expected $Account)" }

. "$PSScriptRoot\_main-src.ps1"
$MainSha = Get-MainSha
$Src = Get-MainSource
Write-Host "source: origin/main $MainSha -> $Src"
try {
$Compute = Join-Path $Src "infra\envs\dev\compute"

terraform -chdir="$Compute" init -input=false; Check "terraform init"
# apply 는 최대 3회. 실패하면 helm 릴리스(ALB 컨트롤러·ESO) 중 failed/pending 인 것을 지우고 다시 돈다.
# 10-28 실측: 막 올라온 컨트롤플레인이 ESO 의 큰 CRD 생성 요청을 타임아웃시켜 릴리스가 failed 로 남고,
# 그 상태에서는 다음 apply 도 같은 릴리스에서 막힌다. 실패한 릴리스를 지워야 provider 가 새로 만든다.
$Releases = @(@("kube-system", "aws-load-balancer-controller"), @("external-secrets", "external-secrets"))
$applied = $false
for ($try = 1; $try -le 3 -and -not $applied; $try++) {
  terraform -chdir="$Compute" apply -auto-approve -input=false
  if (-not $LASTEXITCODE) { $applied = $true; break }
  Write-Warning "terraform apply failed (attempt $try/3). Checking helm releases..."
  $clusters = aws eks list-clusters --query clusters --output text
  if ($clusters -notmatch $Cluster) { throw "terraform apply failed before the cluster existed. See the error above." }
  aws eks update-kubeconfig --name $Cluster --region $Region | Out-Null
  $cleaned = $false
  foreach ($r in $Releases) {
    $status = helm -n $r[0] status $r[1] -o json 2>$null | ConvertFrom-Json
    if ($status -and $status.info.status -ne "deployed") {
      Write-Warning "helm release $($r[0])/$($r[1]) is '$($status.info.status)'. Uninstalling so apply can recreate it."
      helm -n $r[0] uninstall $r[1] --wait --timeout 3m
      $cleaned = $true
    }
  }
  if (-not $cleaned) { throw "terraform apply failed and no helm release is in a failed state. See the error above." }
  Start-Sleep 30   # 컨트롤플레인이 숨 돌릴 시간
}
if (-not $applied) { throw "terraform apply failed 3 times" }
$DbHost = terraform -chdir="$Compute" output -raw rds_address

aws eks update-kubeconfig --name $Cluster --region $Region; Check "update-kubeconfig"
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller --timeout=5m; Check "alb controller rollout"
kubectl -n external-secrets rollout status deploy/external-secrets-webhook --timeout=5m
kubectl -n external-secrets rollout status deploy/external-secrets --timeout=5m; Check "eso rollout"

# app·web 태그 = origin/main sha(CI 가 main 푸시마다 올린다). 아직 없으면(CI 진행 중) ECR 최신 태그로 내려가고 경고.
function Ecr-Tags($repo) { return ((cmd /c "aws ecr describe-images --repository-name nesume/$repo --query ""imageDetails[].imageTags[]"" --output text 2>nul" | Out-String) -split '\s+') }
function Ecr-Latest($repo) { return (cmd /c "aws ecr describe-images --repository-name nesume/$repo --query ""sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]"" --output text 2>nul" | Out-String).Trim() }
if ((Ecr-Tags "app") -contains $MainSha -and (Ecr-Tags "web") -contains $MainSha) { $Sha = $MainSha }
else {
  $Sha = Ecr-Latest "app"
  if (-not $Sha -or $Sha -eq "None") { throw "no image in ECR nesume/app. Push one first (CI on main, or deploy.ps1)." }
  if ((Ecr-Tags "web") -notcontains $Sha) { throw "ECR nesume/web has no tag $Sha (app has it). Push web image first." }
  Write-Warning "ECR has no nesume/app:$MainSha yet (CI still building?). Deploying latest ECR tag $Sha instead; re-run up.ps1 or deploy.ps1 later to catch up."
}

# D20 embedder 이미지는 embedder/ 가 바뀔 때만 올라오므로 app 과 태그가 다르다. ECR 최신 태그를 쓰고, 저장소가 비면 끈다.
# cmd 로 감싼다: PS 5.1 + Stop 에서 네이티브 stderr(저장소 없음 등)가 예외로 바뀐다(deploy.ps1 docker 체크와 같은 이유).
$EmbTag = Ecr-Latest "embedder"
if ($EmbTag -and $EmbTag -ne "None") { $EmbSet = @("--set-string", "image.embedder.tag=$EmbTag") }
else { Write-Warning "ECR nesume/embedder is empty. Deploying with embedder.enabled=false (no embeddings until an image is pushed; see embedder/README.md)"; $EmbSet = @("--set", "embedder.enabled=false") }
# --set-string: sha 가 숫자로만 되면(예: 6462796) --set 은 int 로 읽어 이미지 이름이 %!s(int64=...) 로 깨진다(10-27 실측).
helm upgrade --install nesume (Join-Path $Src "deploy\nesume") -n dev -f (Join-Path $Src "deploy\nesume\values-dev.yaml") `
  --set-string config.DB_HOST=$DbHost --set-string image.app.tag=$Sha --set-string image.web.tag=$Sha @EmbSet --wait --timeout 10m
Check "helm upgrade --install"

$Alb = $null
for ($i = 0; $i -lt 30 -and -not $Alb; $i++) {
  Start-Sleep 10
  $Alb = kubectl -n dev get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}'
}
if (-not $Alb) { throw "ingress has no ALB address after 5 minutes" }

$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
  Start-Sleep 10
  try { $ok = (Invoke-WebRequest -UseBasicParsing "http://$Alb/api/health" -TimeoutSec 5).StatusCode -eq 200 } catch {}
}
if (-not $ok) { throw "/api/health is not 200 at http://$Alb" }
kubectl -n dev get pods
Write-Host "`nUP: http://$Alb  (chart origin/main $MainSha, app/web image $Sha, embedder $EmbTag, db $DbHost)"
} finally { Remove-MainSource $Src }
