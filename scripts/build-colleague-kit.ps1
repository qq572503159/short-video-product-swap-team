param(
  [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root $OutputDirectory
$resolvedRoot = [IO.Path]::GetFullPath($root).TrimEnd("\")
$resolvedDist = [IO.Path]::GetFullPath($dist)
if (-not $resolvedDist.StartsWith("$resolvedRoot\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDirectory 必须位于仓库根目录内，拒绝递归删除: $OutputDirectory"
}
$stage = Join-Path $dist "short-video-product-swap-team"
$zip = "$stage.zip"

if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

foreach ($directory in @("video_replicator", "tests", "scripts", "skills", "docs", "config", "templates")) {
  Copy-Item -LiteralPath (Join-Path $root $directory) -Destination $stage -Recurse -Force
}

Get-ChildItem -LiteralPath $stage -Directory -Recurse -Filter "__pycache__" |
  Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $stage -File -Recurse -Filter "*.pyc" |
  Remove-Item -Force

$providerStage = Join-Path $stage "packages\provider-newapi-video"
New-Item -ItemType Directory -Force -Path $providerStage | Out-Null
Copy-Item -LiteralPath (Join-Path $root "packages\provider-newapi-video\src") -Destination $providerStage -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root "packages\provider-newapi-video\package.json") -Destination $providerStage
Copy-Item -LiteralPath (Join-Path $root "packages\provider-newapi-video\tsconfig.json") -Destination $providerStage
if (Test-Path -LiteralPath (Join-Path $root "packages\provider-newapi-video\package-lock.json")) {
  Copy-Item -LiteralPath (Join-Path $root "packages\provider-newapi-video\package-lock.json") -Destination $providerStage
}

foreach ($file in @(
  "README.md",
  "pyproject.toml",
  "package.json",
  "package-lock.json",
  "hypit.runtime.example.json"
)) {
  Copy-Item -LiteralPath (Join-Path $root $file) -Destination $stage
}

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Output $zip
