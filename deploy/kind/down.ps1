# kind 검증 환경 정리: helm uninstall + kind delete cluster
$Cluster   = "nesume"
$Namespace = "dev"
$Release   = "nesume"

$clusters = kind get clusters 2>$null
if ($clusters -contains $Cluster) {
    kubectl config use-context "kind-$Cluster" | Out-Null
    helm -n $Namespace uninstall $Release 2>$null
    kind delete cluster --name $Cluster
} else {
    Write-Host "kind cluster '$Cluster' not found"
}
