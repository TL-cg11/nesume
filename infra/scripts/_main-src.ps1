# 공통: origin/main 최신본을 임시 worktree 로 받아 그 경로를 돌려준다. up/deploy/down 이 dot-source 한다.
#   . "$PSScriptRoot\_main-src.ps1"; $Src = Get-MainSource; try { ... } finally { Remove-MainSource $Src }
# 왜: 배포 재료(차트·Terraform)는 항상 origin/main 이어야 한다. 로컬 체크아웃은 다른 브랜치·미커밋 작업 중일 수 있고
# (10-28 실측: 다른 작업이 체크아웃을 쓰는 동안 deploy.ps1 이 "dirty/branch" 로 막혔다), 그 상태로 배포하면
# main 에 없는 차트가 올라간다. 이미지 태그도 origin/main 의 sha 를 우선한다(CI 가 main 에서만 빌드).
$script:MainRepo = (Resolve-Path "$PSScriptRoot\..\..").Path

function Get-MainSha {
  git -C $script:MainRepo fetch -q origin main; if ($LASTEXITCODE) { throw "git fetch origin main failed" }
  return (git -C $script:MainRepo rev-parse --short origin/main).Trim()
}

function Get-MainSource {
  $src = Join-Path $env:TEMP "nesume-main-src"
  git -C $script:MainRepo worktree prune
  if (Test-Path $src) { git -C $script:MainRepo worktree remove --force $src 2>$null; if (Test-Path $src) { Remove-Item -Recurse -Force $src } }
  git -C $script:MainRepo worktree add --detach -q $src origin/main; if ($LASTEXITCODE) { throw "git worktree add failed" }
  # Terraform provider 를 매번 내려받지 않게 플러그인 캐시를 둔다(한 번 받으면 재사용).
  $cache = Join-Path $env:LOCALAPPDATA "terraform-plugin-cache"
  if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Path $cache | Out-Null }
  $env:TF_PLUGIN_CACHE_DIR = $cache
  return $src
}

function Remove-MainSource($src) {
  if ($src -and (Test-Path $src)) { git -C $script:MainRepo worktree remove --force $src 2>$null }
}
