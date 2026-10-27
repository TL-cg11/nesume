# compute apply -> kubeconfig -> ESO 대기 -> ClusterSecretStore -> ECR 최신 sha -> helm -> /api/health
# 실행: $env:AWS_PROFILE = "nesume"; .\infra\scripts\up.ps1      (15~20분)
$ErrorActionPreference = "Stop"
if (-not $env:AWS_PROFILE) { throw "AWS_PROFILE is not set. Run: `$env:AWS_PROFILE = 'nesume'" }
$Account = "852138520969"; $Region = "ap-northeast-2"; $Cluster = "nesume-dev"
if ((aws sts get-caller-identity --query Account --output text) -ne $Account) { throw "wrong AWS account (expected $Account)" }

$Repo    = (Resolve-Path "$PSScriptRoot\..\..").Path
$Compute = Join-Path $Repo "infra\envs\dev\compute"

terraform -chdir="$Compute" init -input=false
terraform -chdir="$Compute" apply -auto-approve -input=false
$DbHost = terraform -chdir="$Compute" output -raw rds_address

aws eks update-kubeconfig --name $Cluster --region $Region
kubectl -n external-secrets rollout status deploy/external-secrets-webhook --timeout=5m
kubectl -n external-secrets rollout status deploy/external-secrets --timeout=5m
kubectl apply -f (Join-Path $Repo "deploy\clustersecretstore-dev.yaml")   # D9에서 차트로 옮기면 삭제

$Sha = aws ecr describe-images --repository-name nesume/app --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]' --output text
if (-not $Sha -or $Sha -eq "None") { throw "no image in ECR nesume/app. Push one first." }
$WebTags = aws ecr describe-images --repository-name nesume/web --query 'imageDetails[].imageTags[]' --output text
if ($WebTags -notmatch $Sha) { throw "ECR nesume/web has no tag $Sha (app has it). Push web image first." }

helm upgrade --install nesume (Join-Path $Repo "deploy\nesume") -n dev -f (Join-Path $Repo "deploy\nesume\values-dev.yaml") `
  --set config.DB_HOST=$DbHost --set image.app.tag=$Sha --set image.web.tag=$Sha --wait --timeout 10m

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
Write-Host "`nUP: http://$Alb  (image $Sha, db $DbHost)"
