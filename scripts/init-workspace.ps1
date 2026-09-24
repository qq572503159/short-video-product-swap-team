param(
  [switch]$InstallNodeDependencies,
  [switch]$InstallPython,
  [switch]$SkipBuild,
  [Alias("SkipPython")]
  [switch]$SkipPythonCheck
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$provider = Join-Path $root "packages\provider-newapi-video"
$runtime = Join-Path $root "hypit.runtime.json"
$runtimeExample = Join-Path $root "hypit.runtime.example.json"
$envDir = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\secrets"
$envFile = Join-Path $envDir "newapi.env"

function Require-Command {
  param([string]$Name)
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command) {
    throw "未找到命令 $Name。请先安装对应运行时并确保它在 PATH 中。"
  }
  Write-Host "[OK] $Name -> $($command.Source)"
}

function Invoke-Checked {
  param(
    [string]$Label,
    [scriptblock]$Action
  )
  Write-Host "[RUN] $Label"
  & $Action
  if ($LASTEXITCODE -ne 0) {
    throw "$Label 失败，退出码 $LASTEXITCODE"
  }
}

function Require-PythonVersion {
  try {
    $versionText = (& python -c "import sys; print('%d.%d' % (sys.version_info.major, sys.version_info.minor))" 2>$null | Select-Object -First 1).Trim()
    $version = [version]$versionText
  }
  catch {
    throw "无法读取 Python 版本。"
  }
  if ($version -lt [version]"3.10") {
    throw "Python $versionText 不满足项目要求（需要 >= 3.10）。当前机器可尝试使用 'py -3.12'，或调整 PATH 后重新运行。"
  }
  Write-Host "[OK] python $versionText"
}

Push-Location $root
try {
  Require-Command "node"
  Require-Command "npm"
  Require-Command "npx"
  if (-not $SkipPythonCheck) {
    Require-Command "python"
    Require-PythonVersion
  }

  $ffmpeg = Get-Command "ffmpeg" -ErrorAction SilentlyContinue
  if ($ffmpeg) {
    Write-Host "[OK] ffmpeg -> $($ffmpeg.Source)"
  }
  else {
    Write-Warning "未找到 ffmpeg；抽帧、音频提取和手动生成包会不可用。"
  }

  if ($InstallNodeDependencies) {
    Invoke-Checked "安装根目录 npm 依赖" { npm install }
    Push-Location $provider
    try {
      Invoke-Checked "安装 provider npm 依赖" { npm install }
    }
    finally {
      Pop-Location
    }
  }

  if (-not $SkipBuild) {
    if (-not (Test-Path -LiteralPath (Join-Path $provider "node_modules"))) {
      throw "provider 依赖尚未安装。请先使用 -InstallNodeDependencies。"
    }
    Push-Location $provider
    try {
      Invoke-Checked "构建 provider-newapi-video" { npm run build }
    }
    finally {
      Pop-Location
    }
  }

  if ($InstallPython) {
    if ($SkipPythonCheck) {
      throw "-InstallPython 不能与 -SkipPythonCheck 同时使用。"
    }
    Invoke-Checked "安装本地 Python 包" { python -m pip install -e $root }
  }

  New-Item -ItemType Directory -Force -Path $envDir | Out-Null
  if (-not (Test-Path -LiteralPath $runtime)) {
    if (-not (Test-Path -LiteralPath $runtimeExample)) {
      throw "缺少运行时模板: $runtimeExample"
    }
    Copy-Item -LiteralPath $runtimeExample -Destination $runtime
    Write-Host "[CREATED] 已从脱敏模板创建 hypit.runtime.json；直连生成前还需配置审核后的 assetUrls。"
  }
  if (Test-Path -LiteralPath $envFile) {
    Write-Host "[OK] New API 环境文件已存在（内容不读取、不显示）：$envFile"
  }
  else {
    @"
# 本文件只保存在本机，不要提交到 Git。
NEW_API_URL=https://newapi.megabyai.cc
NEW_API_TOKEN=
NEW_API_MODEL=minimax-h3-f
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
    Write-Host "[CREATED] 已创建空的 New API 配置模板：$envFile"
    Write-Warning "请在本机手动填写 NEW_API_TOKEN；脚本不会代填或打印 token。"
  }

  Write-Host "初始化完成。下一步可运行 scripts\diagnose-workspace.ps1。"
}
finally {
  Pop-Location
}
