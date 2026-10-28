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

if (-not $SkipBuild) {
  docker info 2>$null | Out-Null
  if ($LASTEXITCODE) { throw "docker daemon is not running. Start Docker Desktop and wait until it says Running, then re-run." }
  # PS 5.1: --password-stdin 파이프는 토큰을 깨뜨려 400. 이 PC 는 ARM64 라 그대로 arm64 이미지(x86 이면 --platform linux/arm64).
  docker login --username AWS --password (aws ecr get-login-password --region $Region) $Ecr; Check "docker login"
  docker build -f app/Dockerfile --target runtime --build-arg APP_VERSION=$Sha -t "$Ecr/nesume/app:$Sha" ./app; Check "docker build app"
  docker build -f web/Dockerfile -t "$Ecr/nesume/web:$Sha" ./web; Check "docker build web"
  docker push "$Ecr/nesume/app:$Sha"; Check "docker push app"
  docker push "$Ecr/nesume/web:$Sha"; Check "docker push web"
} else {
  foreach ($r in "app", "web") {
    $tags = aws ecr describe-images --repository-name nesume/$r --query 'imageDetails[].imageTags[]' --output text
    if ($tags -notmatch $Sha) { throw "ECR nesume/$r has no tag $Sha. Run without -SkipBuild." }
  }
}

$clusters = aws eks list-clusters --query clusters --output text
if ($clusters -notmatch $Cluster) {
  Write-Host "`nPUSHED $Sha. Cluster $Cluster is down; the next up.ps1 will deploy this tag."
  return
}

aws eks update-kubeconfig --name $Cluster --region $Region | Out-Null; Check "update-kubeconfig"
$DbHost = terraform -chdir="$Compute" output -raw rds_address; Check "terraform output rds_address"
# --set-string: sha 가 숫자로만 되면(예: 6462796) --set 은 int 로 읽어 이미지 이름이 %!s(int64=...) 로 깨진다(10-27 실측).
helm upgrade --install nesume (Join-Path $Repo "deploy\nesume") -n dev -f (Join-Path $Repo "deploy\nesume\values-dev.yaml") `
  --set-string config.DB_HOST=$DbHost --set-string image.app.tag=$Sha --set-string image.web.tag=$Sha --wait --timeout 10m
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
