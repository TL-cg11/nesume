# kind 로컬 검증. 저장소 루트에서 실행: .\deploy\kind\up.ps1
# 순서: cluster -> build -> load -> lint -> install -> rollout -> port-forward -> /api/health
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root      = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Cluster   = "nesume"
$Namespace = "dev"
$Release   = "nesume"
$Chart     = Join-Path $Root "deploy\nesume"
$Values    = Join-Path $Chart "values-kind.yaml"
$KindCfg   = Join-Path $PSScriptRoot "kind-config.yaml"
$LocalPort = 8080

Push-Location $Root
try {
    $Sha = (git rev-parse --short HEAD).Trim()
    Write-Host "== APP_VERSION=$Sha"

    # 1. 클러스터
    $clusters = kind get clusters 2>$null
    if ($clusters -contains $Cluster) {
        Write-Host "== kind cluster '$Cluster' already exists, skipping create"
    } else {
        Write-Host "== kind create cluster"
        kind create cluster --name $Cluster --config $KindCfg
        if ($LASTEXITCODE -ne 0) { throw "kind create cluster failed" }
    }
    kubectl config use-context "kind-$Cluster" | Out-Null

    # 2. 이미지 빌드 (컨텍스트 ./app, ./web). 태그는 차트의 ECR 경로 규칙(nesume/app)을 따른다.
    Write-Host "== docker build app"
    docker build -f app/Dockerfile --target runtime --build-arg "APP_VERSION=$Sha" -t nesume/app:local ./app
    if ($LASTEXITCODE -ne 0) { throw "docker build app failed" }
    Write-Host "== docker build web"
    docker build -f web/Dockerfile -t nesume/web:local ./web
    if ($LASTEXITCODE -ne 0) { throw "docker build web failed" }

    # 3. 클러스터로 이미지 복사 (pullPolicy: Never)
    Write-Host "== kind load docker-image"
    kind load docker-image nesume/app:local nesume/web:local --name $Cluster
    if ($LASTEXITCODE -ne 0) { throw "kind load failed" }

    # 4. lint
    Write-Host "== helm lint"
    helm lint $Chart -f $Values
    if ($LASTEXITCODE -ne 0) { throw "helm lint failed" }

    # 5. install / upgrade
    Write-Host "== helm upgrade --install"
    helm upgrade --install $Release $Chart -n $Namespace --create-namespace -f $Values
    if ($LASTEXITCODE -ne 0) { throw "helm upgrade failed" }

    # 6. rollout
    Write-Host "== rollout status"
    kubectl -n $Namespace rollout status "deploy/$Release-app" --timeout=180s
    if ($LASTEXITCODE -ne 0) { throw "app rollout failed" }
    kubectl -n $Namespace rollout status "deploy/$Release-web" --timeout=120s
    if ($LASTEXITCODE -ne 0) { throw "web rollout failed" }
    kubectl -n $Namespace wait --for=condition=complete "job/$Release-migrate" --timeout=180s
    if ($LASTEXITCODE -ne 0) { throw "migrate job did not complete" }

    kubectl -n $Namespace get pods,jobs,svc,cm,secret

    # 7. port-forward (백그라운드) + health
    Write-Host "== port-forward svc/$Release-web $LocalPort:8080"
    $pf = Start-Process -FilePath kubectl -ArgumentList "-n", $Namespace, "port-forward", "svc/$Release-web", "${LocalPort}:8080" -PassThru -WindowStyle Hidden
    try {
        $ok = $false
        for ($i = 0; $i -lt 15 -and -not $ok; $i++) {
            Start-Sleep -Seconds 1
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:$LocalPort/api/health" -UseBasicParsing -TimeoutSec 3
                $ok = $true
            } catch { }
        }
        if (-not $ok) { throw "/api/health did not respond" }

        Write-Host "== /api/health"
        Write-Host "HTTP $($resp.StatusCode)"
        Write-Host "X-Request-ID: $($resp.Headers['X-Request-ID'])"
        Write-Host $resp.Content
        $body = $resp.Content | ConvertFrom-Json
        if ($body.version -ne $Sha) { throw "version mismatch: got '$($body.version)', expected '$Sha'" }

        Write-Host "== /ready (inside pod; S3 error is expected on kind)"
        kubectl -n $Namespace exec "deploy/$Release-app" -- python -c "import urllib.request,urllib.error`ntry:`n    print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())`nexcept urllib.error.HTTPError as e:`n    print(e.code, e.read().decode())"
    } finally {
        if ($pf -and -not $pf.HasExited) { Stop-Process -Id $pf.Id -Force }
    }

    Write-Host ""
    Write-Host "OK. To browse: kubectl -n $Namespace port-forward svc/$Release-web ${LocalPort}:8080"
} finally {
    Pop-Location
}
