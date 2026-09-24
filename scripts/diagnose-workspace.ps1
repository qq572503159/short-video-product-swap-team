param(
  [switch]$SkipNetwork
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$provider = Join-Path $root "packages\provider-newapi-video"
$envFile = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\secrets\newapi.env"
$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
  param(
    [string]$Name,
    [ValidateSet("PASS", "WARN", "FAIL")][string]$Status,
    [string]$Detail
  )
  $results.Add([pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail })
}

function Check-Command {
  param(
    [string]$Name,
    [switch]$Required
  )
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($command) {
    Add-Result "command:$Name" "PASS" $command.Source
  }
  elseif ($Required) {
    Add-Result "command:$Name" "FAIL" "未找到；请运行初始化或安装对应工具。"
  }
  else {
    Add-Result "command:$Name" "WARN" "未找到（可选）。"
  }
}

function Check-PythonVersion {
  $command = Get-Command "python" -ErrorAction SilentlyContinue
  if (-not $command) {
    Add-Result "python:version" "FAIL" "未找到 python；项目需要 Python >= 3.10。"
    return
  }
  try {
    $versionText = (& python -c "import sys; print('%d.%d' % (sys.version_info.major, sys.version_info.minor))" 2>$null | Select-Object -First 1).Trim()
    $version = [version]$versionText
    if ($version -lt [version]"3.10") {
      Add-Result "python:version" "FAIL" "当前为 $versionText；项目需要 >= 3.10，可尝试 'py -3.12'。"
    }
    else {
      Add-Result "python:version" "PASS" $versionText
    }
  }
  catch {
    Add-Result "python:version" "FAIL" "无法读取 Python 版本。"
  }
}

function Invoke-ReadOnlyCheck {
  param(
    [string]$Name,
    [string]$File,
    [string[]]$Arguments
  )
  if (-not (Test-Path -LiteralPath $File)) {
    Add-Result $Name "WARN" "本地命令入口不存在，跳过。"
    return
  }
  try {
    Push-Location $root
    try {
      $null = & $File @Arguments 2>&1
      $code = $LASTEXITCODE
    }
    finally {
      Pop-Location
    }
    if ($code -eq 0) {
      Add-Result $Name "PASS" "只读检查通过。"
    }
    else {
      Add-Result $Name "WARN" "命令退出码 $code；未发起视频生成。"
    }
  }
  catch {
    Add-Result $Name "WARN" $_.Exception.Message
  }
}

Push-Location $root
try {
  Check-Command "node" -Required
  Check-Command "npm" -Required
  Check-Command "npx" -Required
  Check-Command "python" -Required
  Check-PythonVersion
  Check-Command "ffmpeg"

  $requiredFiles = @(
    "README.md",
    "pyproject.toml",
    "hypit.runtime.json",
    "video_replicator\newapi_video.py",
    "scripts\run-video-team.ps1",
    "packages\provider-newapi-video\package.json"
  )
  foreach ($relative in $requiredFiles) {
    $path = Join-Path $root $relative
    if (Test-Path -LiteralPath $path) {
      Add-Result "file:$relative" "PASS" "存在。"
    }
    else {
      Add-Result "file:$relative" "FAIL" "缺失。"
    }
  }

  $providerDist = Join-Path $provider "dist"
  if (Test-Path -LiteralPath $providerDist) {
    Add-Result "provider:dist" "PASS" "已构建。"
  }
  else {
    Add-Result "provider:dist" "WARN" "尚未构建；运行 init-workspace.ps1。"
  }

  if (Test-Path -LiteralPath $envFile) {
    Add-Result "config:newapi.env" "PASS" "配置文件存在；内容不读取、不显示。"
  }
  else {
    Add-Result "config:newapi.env" "WARN" "配置文件不存在；运行 init-workspace.ps1 创建模板。"
  }

  $token = [Environment]::GetEnvironmentVariable("NEW_API_TOKEN", "Process")
  if ([string]::IsNullOrWhiteSpace($token)) {
    Add-Result "config:NEW_API_TOKEN" "WARN" "当前进程未设置；dry-run 不需要 token，真实提交需要。"
  }
  else {
    Add-Result "config:NEW_API_TOKEN" "PASS" "当前进程已设置（值不显示）。"
  }

  $hypit = Join-Path $root "node_modules\.bin\hypit.cmd"
  Invoke-ReadOnlyCheck "hypit:help" $hypit @("--help")

  $runtime = Join-Path $root "hypit.runtime.json"
  if (Test-Path -LiteralPath $runtime) {
    Invoke-ReadOnlyCheck "hypit:doctor" $hypit @("doctor", "--runtime", $runtime, "--json")
  }

  if ($SkipNetwork) {
    Add-Result "network:video-docs" "WARN" "按 -SkipNetwork 跳过。"
  }
  else {
    $baseUrl = [Environment]::GetEnvironmentVariable("NEW_API_URL", "Process")
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
      $baseUrl = "https://newapi.megabyai.cc"
    }
    $docsUrl = "$($baseUrl.TrimEnd('/'))/video-docs"
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $docsUrl -Method Get -MaximumRedirection 3 -TimeoutSec 15
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
        Add-Result "network:video-docs" "PASS" "文档站点可达（HTTP $($response.StatusCode)）。"
      }
      else {
        Add-Result "network:video-docs" "WARN" "文档站点返回 HTTP $($response.StatusCode)。"
      }
    }
    catch {
      Add-Result "network:video-docs" "WARN" "无法访问 $docsUrl；未发送 API 生成请求。"
    }
  }
}
finally {
  Pop-Location
}

$results | Format-Table -AutoSize
$failed = @($results | Where-Object Status -eq "FAIL")
if ($failed.Count -gt 0) {
  Write-Error "诊断发现 $($failed.Count) 个阻断项。"
  exit 1
}
Write-Host "诊断完成：未发现阻断项。WARN 仅表示可选依赖、配置或网络尚待补齐。"
