param(
  [string]$Project = "projects/demo-9-16",
  [string]$Video = "",
  [int]$SegmentMax = 15,
  [string]$TranscriptionLanguage = "",
  [string]$TranscriptionModel = "small",
  [string]$ProductName = "",
  [ValidateSet("original_audio", "new_tts", "new_human_voice")][string]$VoiceMode = "new_tts",
  [ValidateSet("silent", "ambient", "music", "voiceover", "full")][string]$AudioMode = "voiceover",
  [string]$Runtime = "hypit.runtime.json",
  [switch]$Submit,
  [switch]$ConfirmBilling
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $root $Project
if (-not $Video) { $Video = Join-Path $projectPath "inputs/reference.mp4" }
if (-not (Test-Path -LiteralPath $Video)) { throw "找不到参考视频: $Video" }
$productFile = Join-Path $projectPath "inputs/product.json"
if (-not $ProductName -and (Test-Path -LiteralPath $productFile)) {
  $ProductName = [string]((Get-Content -LiteralPath $productFile -Raw | ConvertFrom-Json).name)
}
if (-not $ProductName) { $ProductName = "目标产品" }
if ($SegmentMax -notin @(15, 30)) { throw "SegmentMax 只能是 15 或 30" }
if ($Submit -and -not $ConfirmBilling) {
  throw "提交外部生成会产生费用。请在确认模型、素材和预算后同时传入 -Submit -ConfirmBilling。"
}
if ($Submit -and $AudioMode -in @("voiceover", "full")) {
  throw "当前 Hypit New API provider 不支持原生音频。需要模型直接生成声音时，请使用 Python New API 路线并先通过 QA/费用审批。"
}

$logs = Join-Path $projectPath "outputs/team-logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$pythonCommand = "python"
$pythonPrefix = @()
try {
  $pythonVersion = [version]((& python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim())
}
catch {
  $pythonVersion = [version]"0.0"
}
if ($pythonVersion -lt [version]"3.10") {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonPrefix = @("-3.12")
  }
  else {
    throw "项目需要 Python >= 3.10；当前 python 为 $pythonVersion，且未找到 py launcher。"
  }
}

Push-Location $root
try {
  Write-Host "[总导演] 启动中文多智能体本地流程"
  $teamArgs = @("-m", "video_replicator.cli", "team-run", $Video, "--project", $Project, "--segment-max", "$SegmentMax", "--aspect-ratio", "9:16", "--transcription-model", $TranscriptionModel)
  if ($TranscriptionLanguage) { $teamArgs += @("--transcription-language", $TranscriptionLanguage) }
  & $pythonCommand @pythonPrefix @teamArgs |
    Tee-Object -FilePath (Join-Path $logs "01-team-run.json")
  if ($LASTEXITCODE -ne 0) { throw "本地多智能体流程失败" }

  Write-Host "[深度拆解师] 生成逐时间片深度拆解 JSON 和 Markdown"
  & $pythonCommand @pythonPrefix -m video_replicator.cli deep-analyze --project $Project --segment-seconds 1 |
    Tee-Object -FilePath (Join-Path $logs "01b-deep-analysis.json")
  if ($LASTEXITCODE -ne 0) { throw "深度视频拆解失败" }

  Write-Host "[文案导演] 生成可编辑文案和字幕时间轴"
  & $pythonCommand @pythonPrefix -m video_replicator.cli script-timeline --project $Project --product-name $ProductName --voice-mode $VoiceMode |
    Tee-Object -FilePath (Join-Path $logs "01c-script-timeline.json")
  if ($LASTEXITCODE -ne 0) { throw "文案时间轴生成失败" }

  $framework = Join-Path $projectPath "analysis/replication-framework.json"
  $compiledPrompt = Join-Path $projectPath "outputs/final_product_swap_prompt.md"
  if (Test-Path -LiteralPath $framework) {
    Write-Host "[提示词导演] 编译审核后的逐镜复刻提示词"
    & $pythonCommand @pythonPrefix -m video_replicator.cli replication-prompt --framework $framework --timeline (Join-Path $projectPath "analysis/script-timeline.json") --output $compiledPrompt --audio-mode $AudioMode |
      Tee-Object -FilePath (Join-Path $logs "01d-replication-prompt.json")
    if ($LASTEXITCODE -ne 0) { throw "逐镜复刻提示词编译失败" }
  } else {
    Write-Warning "未找到 $framework；当前仅完成基础拆解，真实提交前必须补充并审核 replication-framework.json。"
  }

  Write-Host "[交付打包师] 生成可供其他平台使用的素材包"
  & powershell -ExecutionPolicy Bypass -File scripts/export-manual-generation-package.ps1 -Project $Project -AudioMode $AudioMode |
    Tee-Object -FilePath (Join-Path $logs "02-manual-package.txt")
  if ($LASTEXITCODE -ne 0) { throw "手动生成素材包创建失败" }

  $run = Join-Path $projectPath "hypit/product-swap.svrun"
  $author = Join-Path $projectPath "hypit/product-swap.svml"
  if ($Submit) {
    $qaFile = Join-Path $projectPath "outputs/qa.json"
    if (-not (Test-Path -LiteralPath $qaFile)) { throw "缺少 QA 文件，禁止提交: $qaFile" }
    $qa = Get-Content -LiteralPath $qaFile -Raw | ConvertFrom-Json
    if ($qa.status -ne "ready") { throw "QA 状态为 $($qa.status)，禁止付费提交；只有 ready 可以提交" }
    $scopeApproval = Join-Path $projectPath "outputs/scope-approval.json"
    if (-not (Test-Path -LiteralPath $scopeApproval)) { throw "缺少人工审核文件，禁止提交: $scopeApproval" }
    $approval = Get-Content -LiteralPath $scopeApproval -Raw | ConvertFrom-Json
    if ($approval.status -ne "approved" -or -not $approval.reviewer -or -not $approval.approved_at) {
      throw "人工审核文件无效，禁止提交: $scopeApproval"
    }
    if (-not (Test-Path -LiteralPath $compiledPrompt)) { throw "缺少已编译逐镜提示词，禁止提交: $compiledPrompt" }
    if (-not ((Test-Path -LiteralPath $run) -and (Test-Path -LiteralPath $author))) {
      throw "缺少 Hypit 运行文件，禁止提交: $run / $author"
    }
  }
  if ((Test-Path -LiteralPath $run) -and (Test-Path -LiteralPath $author)) {
    Write-Host "[生成执行师] 执行 Hypit 只读检查、计划和费用入口检查"
    & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 check $author --json |
      Tee-Object -FilePath (Join-Path $logs "03-hypit-check-author.json")
    if ($LASTEXITCODE -ne 0) { throw "Hypit Author 检查失败" }
    & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 check $run --json |
      Tee-Object -FilePath (Join-Path $logs "04-hypit-check-run.json")
    if ($LASTEXITCODE -ne 0) { throw "Hypit Run 检查失败" }
    & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 doctor --runtime $Runtime --json |
      Tee-Object -FilePath (Join-Path $logs "05-hypit-doctor.json")
    if ($LASTEXITCODE -ne 0) { throw "Hypit Runtime 检查失败" }
    & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 plan $run --runtime $Runtime --json |
      Tee-Object -FilePath (Join-Path $logs "06-hypit-plan.json")
    if ($LASTEXITCODE -ne 0) { throw "Hypit Plan 检查失败" }
    & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 pricing $run --runtime $Runtime --json |
      Tee-Object -FilePath (Join-Path $logs "07-hypit-pricing.json")
    if ($LASTEXITCODE -ne 0) { throw "Hypit Pricing 检查失败" }

    if ($Submit) {
      Write-Host "[生成执行师] 已获得费用确认，提交真实 Build"
      & powershell -ExecutionPolicy Bypass -File scripts/hypit-newapi.ps1 build $run --runtime $Runtime --follow --json |
        Tee-Object -FilePath (Join-Path $logs "08-hypit-build.json")
      if ($LASTEXITCODE -ne 0) { throw "Hypit Build 失败，请查看 08-hypit-build.json" }
    }
  }

  $teamReport = Get-Content -LiteralPath (Join-Path $projectPath "outputs/team-run-report.json") -Raw | ConvertFrom-Json
  $summary = [ordered]@{
    workflow_status = [string]$teamReport.status
    status = if ($Submit) { "submitted" } else { [string]$teamReport.status }
    project = (Resolve-Path $projectPath).Path
    manual_package = "$projectPath\outputs\manual-generation-package.zip"
    logs = $logs
    submitted = [bool]$Submit
  }
  $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logs "summary.json") -Encoding UTF8
  $summary | ConvertTo-Json
}
finally {
  Pop-Location
}
