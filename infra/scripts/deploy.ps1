# main 최신본을 dev 에 배포: git pull -> 이미지 빌드·푸시(app·web, 태그 = git sha) -> 클러스터가 켜져 있으면 helm upgrade -> /api/health
# 실행: $env:AWS_PROFILE = "nesume"; .\infra\scripts\deploy.ps1            (빌드 포함 약 10분)
#       .\infra\scripts\deploy.ps1 -SkipPull     현재 체크아웃 그대로(브랜치 테스트용). 커밋 안 된 변경은 이미지에 안 들어간다.
#       .\infra\scripts\deploy.ps1 -SkipBuild    ECR 에 이미 sha 태그가 있을 때 helm 만
# 클러스터가 꺼져 있으면 푸시까지만 하고 끝난다. 다음 up.ps1 이 ECR 최신 태그를 집어 올린다.
param([switch]$SkipPull, [switch]$SkipBuild)
$ErrorActionPreference = "Stop"
function Check($step) { if ($LASTEXITCODE) { throw "$step failed (exit $LASTEXITCODE)" } }
if (-not $env:AWS_PROFILE) { throw "AWS_PROFILE is not set. Run: `$env:AWS_PROFILE = 'nesume'" }
$Account = "852138520969"; $Region = "ap-northeast-2"; $Cluster = "nesume-dev"
$Ecr = "$Account.dkr.ecr.$Region.amazonaws.com"
if ((aws sts get-caller-identity --query Account --output text) -ne $Account) { throw "wrong AWS account (expected $Account)" }

$Repo    = (Resolve-Path "$PSScriptRoot\..\..").Path
$Compute = Join-Path $Repo "infra\envs\dev\compute"
Set-Location $Repo

if (-not $SkipPull) {
  $branch = git rev-parse --abbrev-ref HEAD
  if ($branch -ne "main") { throw "on branch '$branch'. Switch to main, or pass -SkipPull to deploy this branch as-is." }
  if (git status --porcelain) { throw "working tree is dirty. Commit or stash first (uncommitted changes would not be in the image anyway)." }
  git pull --ff-only origin main; Check "git pull"
}
$Sha = git rev-parse --short HEAD
Write-Host "deploying $Sha ($(git log -1 --format=%s))"

# ECR 태그는 IMMUTABLE. 같은 sha 를 다시 push 하면 거부되므로(재실행·부분 실패 뒤) 이미 있는 저장소는 건너뛴다.
function Has-EcrTag($repo, $tag) {
  $tags = aws ecr describe-images --repository-name "nesume/$repo" --query 'imageDetails[].imageTags[]' --output text 2>$null
  return ($tags -split '\s+') -contains $tag
}
$Builds = @(
  @{ repo = "app"; args = @("-f", "app/Dockerfile", "--target", "runtime", "--build-arg", "APP_VERSION=$Sha", "./app") },
  @{ repo = "web"; args = @("-f", "web/Dockerfile", "./web") }
)
$needBuild = @($Builds | Where-Object { -not (Has-EcrTag $_.repo $Sha) })
if ($SkipBuild -and $needBuild) { throw "ECR nesume/$($needBuild[0].repo) has no tag $Sha. Run without -SkipBuild." }
if ($needBuild) {
  # PS 5.1 + $ErrorActionPreference=Stop 에서는 네이티브 명령의 stderr 리다이렉트가 예외로 바뀐다. cmd 로 감싼다.
  cmd /c "docker info >nul 2>&1"
  if ($LASTEXITCODE) { throw "docker daemon is not reachable. Start Docker Desktop, wait until the whale icon says Running (30s~1m), then re-run." }
  # PS 5.1: --password-stdin 파이프는 토큰을 깨뜨려 400. 이 PC 는 ARM64 라 그대로 arm64 이미지(x86 이면 --platform linux/arm64).
  docker login --username AWS --password (aws ecr get-login-password --region $Region) $Ecr; Check "docker login"
  foreach ($b in $needBuild) {
    $image = "$Ecr/nesume/$($b.repo):$Sha"
    docker build @($b.args) -t $image; Check "docker build $($b.repo)"
    docker push $image; Check "docker push $($b.repo)"
  }
} else {
  Write-Host "ECR already has nesume/app:$Sha and nesume/web:$Sha. Skipping build."
}

$clusters = aws eks list-clusters --query clusters --output text
if ($clusters -notmatch $Cluster) {
  Write-Host "`nPUSHED $Sha. Cluster $Cluster is down; the next up.ps1 will deploy this tag."
  return
}

aws eks update-kubeconfig --name $Cluster --region $Region | Out-Null; Check "update-kubeconfig"
$DbHost = terraform -chdir="$Compute" output -raw rds_address; Check "terraform output rds_address"
# D20 embedder 이미지는 embedder/ 가 바뀔 때만 올라오므로 app 과 태그가 다르다. ECR 최신 태그를 쓰고, 저장소가 비면 끈다.
# cmd 로 감싼다: PS 5.1 + Stop 에서 네이티브 stderr(저장소 없음 등)가 예외로 바뀐다(deploy.ps1 docker 체크와 같은 이유).
$EmbTag = (cmd /c "aws ecr describe-images --repository-name nesume/embedder --query ""sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]"" --output text 2>nul" | Out-String).Trim()
if ($EmbTag -and $EmbTag -ne "None") { $EmbSet = @("--set-string", "image.embedder.tag=$EmbTag") }
else { Write-Warning "ECR nesume/embedder is empty. Deploying with embedder.enabled=false (no embeddings until an image is pushed; see embedder/README.md)"; $EmbSet = @("--set", "embedder.enabled=false") }
# --set-string: sha 가 숫자로만 되면(예: 6462796) --set 은 int 로 읽어 이미지 이름이 %!s(int64=...) 로 깨진다(10-27 실측).
helm upgrade --install nesume (Join-Path $Repo "deploy\nesume") -n dev -f (Join-Path $Repo "deploy\nesume\values-dev.yaml") `
  --set-string config.DB_HOST=$DbHost --set-string image.app.tag=$Sha --set-string image.web.tag=$Sha @EmbSet --wait --timeout 10m
Check "helm upgrade --install"

$Alb = kubectl -n dev get ingress nesume -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
$ok = $false
for ($i = 0; $i -lt 18 -and -not $ok; $i++) {
  try {
    $body = (Invoke-WebRequest -UseBasicParsing "http://$Alb/api/health" -TimeoutSec 5).Content
    $ok = $body -match $Sha
  } catch {}
  if (-not $ok) { Start-Sleep 10 }
}
if (-not $ok) { throw "/api/health at http://$Alb does not report version $Sha yet. Check: kubectl -n dev get pods; helm -n dev history nesume" }
kubectl -n dev get pods
Write-Host "`nDEPLOYED $Sha -> http://$Alb  ($body)"
