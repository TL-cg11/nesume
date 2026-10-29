# helm uninstall -> Ingress/ALB 삭제 대기 -> compute destroy -> NAT·EIP·EKS·RDS·ALB 잔존 확인
# 실행: $env:AWS_PROFILE = "nesume"; .\infra\scripts\down.ps1    (10분)
$ErrorActionPreference = "Stop"
if (-not $env:AWS_PROFILE) { throw "AWS_PROFILE is not set" }
$Account = "852138520969"; $Region = "ap-northeast-2"; $Cluster = "nesume-dev"
if ((aws sts get-caller-identity --query Account --output text) -ne $Account) { throw "wrong AWS account (expected $Account)" }

# Terraform 은 origin/main worktree 에서 읽는다(원격 state. 로컬 체크아웃이 다른 브랜치여도 main 의 리소스 정의로 destroy).
. "$PSScriptRoot\_main-src.ps1"
$Src = Get-MainSource
$Compute = Join-Path $Src "infra\envs\dev\compute"
try {

$clusters = aws eks list-clusters --query clusters --output text
if ($clusters -match $Cluster) {
  aws eks update-kubeconfig --name $Cluster --region $Region | Out-Null
  helm -n dev uninstall nesume --ignore-not-found --wait --timeout 5m
  # Ingress 는 ALB 컨트롤러 finalizer 때문에 uninstall 이 돌아온 뒤에도 10~20초 더 남는다(10-27 실측).
  # 안 기다리고 install 하면 Helm 이 삭제 중인 옛 Ingress 를 자기 것으로 보고 넘어가 Ingress NotFound 로 실패한다.
  kubectl -n dev wait --for=delete ingress/nesume --timeout=3m 2>$null
  # ALB 컨트롤러가 ALB·타깃 그룹·SG를 지울 때까지 기다린다. 남으면 destroy가 VPC/서브넷에서 멈춘다.
  for ($i = 0; $i -lt 30; $i++) {
    $lbs = aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
    if (-not $lbs) { break }
    Start-Sleep 10
  }
  if ($lbs) { Write-Warning "ALB still present: $lbs (destroy may hang; see infra/README.md)" }
}

terraform -chdir="$Compute" init -input=false
terraform -chdir="$Compute" destroy -auto-approve -input=false

# 과금 누수 확인. 전부 비어 있어야 한다.
$nat = aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query 'NatGateways[].NatGatewayId' --output text
$eip = aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].PublicIp' --output text
$eks = aws eks list-clusters --query clusters --output text
$rds = aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
$alb = aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
foreach ($p in @(@("NAT", $nat), @("EIP(unassociated)", $eip), @("EKS", $eks), @("RDS", $rds), @("ALB", $alb))) {
  if ($p[1]) { Write-Warning "$($p[0]) still exists: $($p[1])" } else { Write-Host "$($p[0]): none" }
}
Write-Host "`nDOWN complete"
} finally { Remove-MainSource $Src }
