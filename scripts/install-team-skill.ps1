param(
  [string]$Destination = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "skills\short-video-product-swap-team"
if (-not $Destination) {
  $profile = [Environment]::GetFolderPath("UserProfile")
  $preferredRoot = Join-Path $profile ".codex\skills"
  if (-not (Test-Path -LiteralPath $preferredRoot)) {
    $preferredRoot = Join-Path $profile ".agents\skills"
  }
  $Destination = Join-Path $preferredRoot "short-video-product-swap-team"
}
if (-not (Test-Path -LiteralPath $source)) { throw "找不到 Skill 源目录: $source" }
if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
  throw "目标 Skill 已存在: $Destination。确认覆盖时使用 -Force。"
}
if (Test-Path -LiteralPath $Destination) {
  $allowedRoots = @(
    (Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\skills"),
    (Join-Path ([Environment]::GetFolderPath("UserProfile")) ".agents\skills")
  ) | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd("\") }
  $resolvedDestination = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Destination).Path)
  if (-not ($allowedRoots | Where-Object { $resolvedDestination.StartsWith("$_\", [StringComparison]::OrdinalIgnoreCase) })) {
    throw "-Force 只允许覆盖用户 Skill 目录下的目标: $Destination"
  }
  Remove-Item -LiteralPath $Destination -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
Copy-Item -LiteralPath $source -Destination $Destination -Recurse -Force
Write-Output "已安装 Skill: $Destination"
