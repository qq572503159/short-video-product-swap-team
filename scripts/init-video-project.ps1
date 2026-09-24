param(
  [Parameter(Mandatory = $true)][ValidatePattern("^[a-zA-Z0-9_-]+$")][string]$Name,
  [Parameter(Mandatory = $true)][string]$ReferenceVideo,
  [Parameter(Mandatory = $true)][string]$ProductFrontBack,
  [Parameter(Mandatory = $true)][string]$ProductMultiAngle,
  [Parameter(Mandatory = $true)][string]$ProductName,
  [string]$ProductDescription = "由产品参考图确定瓶型、包装、标签、颜色和文字"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
foreach ($path in @($ReferenceVideo, $ProductFrontBack, $ProductMultiAngle)) {
  if (-not (Test-Path -LiteralPath $path)) { throw "找不到输入文件: $path" }
}
$project = Join-Path $root "projects\$Name"
if (Test-Path -LiteralPath $project) { throw "项目已存在: $project" }

$productRefs = Join-Path $project "inputs\product_refs"
New-Item -ItemType Directory -Force -Path $productRefs | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $project "analysis") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $project "outputs") | Out-Null
Copy-Item -LiteralPath $ReferenceVideo -Destination (Join-Path $project "inputs\reference.mp4")
$frontExt = [IO.Path]::GetExtension($ProductFrontBack).ToLowerInvariant()
$multiExt = [IO.Path]::GetExtension($ProductMultiAngle).ToLowerInvariant()
if (-not $frontExt) { $frontExt = ".bin" }
if (-not $multiExt) { $multiExt = ".bin" }
$frontName = "product-front-back$frontExt"
$multiName = "product-multi-angle$multiExt"
Copy-Item -LiteralPath $ProductFrontBack -Destination (Join-Path $productRefs $frontName)
Copy-Item -LiteralPath $ProductMultiAngle -Destination (Join-Path $productRefs $multiName)

[ordered]@{
  name = $ProductName
  description = $ProductDescription
  references = @("inputs/product_refs/$frontName", "inputs/product_refs/$multiName")
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $project "inputs\product.json") -Encoding UTF8

[ordered]@{
  mode = "replicate_product_only"
  reference_video = "inputs/reference.mp4"
  product = $ProductName
  preserve = @("人物身份与脸部", "发型和服装", "动作和口型", "场景、光线、机位和构图", "原视频节奏")
  replace_only = @("原产品")
  forbid = @("改变人物或场景", "新增人物或道具", "错误品牌、包装或标签")
  segment_max_sec = 15
  aspect_ratio = "9:16"
  audio_strategy = "待需求确认：原音、模型原生音频或新配音"
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $project "replication_manifest.json") -Encoding UTF8

Write-Output "已创建项目: $project"
Write-Output "下一步: powershell -ExecutionPolicy Bypass -File .\scripts\run-video-team.ps1 -Project projects/$Name"
