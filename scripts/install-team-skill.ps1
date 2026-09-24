param(
  [string]$Destination = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "skills\short-video-product-swap-team"
if (-not $Destination) {
  $Destination = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\skills\short-video-product-swap-team"
}
if (-not (Test-Path -LiteralPath $source)) { throw "找不到 Skill 源目录: $source" }
if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
  throw "目标 Skill 已存在: $Destination。确认覆盖时使用 -Force。"
}
if (Test-Path -LiteralPath $Destination) {
  Remove-Item -LiteralPath $Destination -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
Copy-Item -LiteralPath $source -Destination $Destination -Recurse -Force
Write-Output "已安装 Skill: $Destination"
