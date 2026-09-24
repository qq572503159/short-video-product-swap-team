param(
  [string]$Project = "projects/demo-9-16",
  [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $root $Project
if (-not $Output) {
  $Output = Join-Path $projectPath "outputs/manual-generation-package"
}

$assets = Join-Path $Output "01-upload-assets"
New-Item -ItemType Directory -Force -Path $assets | Out-Null
Get-ChildItem -LiteralPath $assets -Filter "shot-sheet-*.jpg" -File -ErrorAction SilentlyContinue |
  Remove-Item -Force
Copy-Item (Join-Path $projectPath "outputs/reference_collages/shot-sheet-*.jpg") $assets -Force
$productRefs = @(Get-ChildItem -LiteralPath (Join-Path $projectPath "inputs/product_refs") -File -Include *.png,*.jpg,*.jpeg,*.webp -ErrorAction SilentlyContinue)
if ($productRefs.Count -eq 0) { throw "未找到产品参考图: $projectPath\inputs\product_refs" }
Copy-Item $productRefs.FullName $assets -Force

$tutorialTemplate = Join-Path $root "templates/manual-generation-package/README-中文教程.md"
$mergeTemplate = Join-Path $root "templates/manual-generation-package/merge-original-audio.ps1"
Copy-Item -LiteralPath $tutorialTemplate -Destination (Join-Path $Output "README-中文教程.md") -Force
Copy-Item -LiteralPath $mergeTemplate -Destination (Join-Path $Output "merge-original-audio.ps1") -Force

$promptOutput = Join-Path $Output "02-generation-prompt.txt"
$productFile = Join-Path $projectPath "inputs/product.json"
$product = if (Test-Path -LiteralPath $productFile) {
  Get-Content -LiteralPath $productFile -Raw | ConvertFrom-Json
} else {
  [pscustomobject]@{ name = "目标产品"; description = "严格以产品参考图为准" }
}
$productDescription = ([string]$product.description).TrimEnd("。")
@"
竖屏 9:16，生成连续单画面写实短视频，目标时长严格匹配参考视频。严格参考编号拼图的时间顺序，保留同一位人物的身份、脸部、发型、服装、坐姿、口型、手势、表情，以及原场景、光线、固定机位、构图、动作、镜头切换和节奏。拼图中的 Shot 编号只表示时间顺序，不是三分屏或六格布局。

只替换原产品为“$($product.name)”。产品外观严格依据产品参考图：$productDescription。保持原产品所在位置、尺寸、朝向、接触关系、遮挡关系、反光和画面占比，在每个镜头之间保持连续。

删除参考视频中已经烧录的字幕、价格、促销文字、贴纸、按钮、角标、水印和其他营销文案；不要生成任何新的字幕或画外文字。产品自身标签上的真实文字可以保留，但不得把标签文字扩展到画外。不要生成拼图边框、Shot 编号、额外人物、新场景、额外道具、产品旋转、产品放大、转场或背景音乐。生成无声视频，后期按照 script-timeline.json 使用改写后的 new_tts 配音，不合回原对白。
"@ | Set-Content -LiteralPath $promptOutput -Encoding UTF8

$sheetNames = @(Get-ChildItem -LiteralPath $assets -Filter "shot-sheet-*.jpg" | Sort-Object Name | ForEach-Object { "01-upload-assets/$($_.Name)" })
$productNames = @($productRefs | ForEach-Object { "01-upload-assets/$($_.Name)" })
$referenceImages = @($sheetNames) + $productNames
[ordered]@{
  mode = "multi-image-reference-to-video"
  duration_seconds = 12
  aspect_ratio = "9:16"
  resolution = "720p"
  generate_audio = $false
  reference_images = $referenceImages
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Output "03-parameters.json") -Encoding UTF8

$sourceVideo = Join-Path $projectPath "inputs/reference.mp4"
$audio = Join-Path $Output "original-audio.m4a"
if (Test-Path -LiteralPath $sourceVideo) {
  & ffmpeg -y -hide_banner -loglevel error -i $sourceVideo -vn -c:a aac -b:a 192k $audio
  if ($LASTEXITCODE -ne 0) { throw "提取原音轨失败" }
}

$timelineSource = Join-Path $projectPath "analysis/script-timeline.json"
if (Test-Path -LiteralPath $timelineSource) {
  Copy-Item -LiteralPath $timelineSource -Destination (Join-Path $Output "script-timeline.json") -Force
}
$adaptedScriptSource = Join-Path $projectPath "analysis/adapted_script.md"
if (Test-Path -LiteralPath $adaptedScriptSource) {
  Copy-Item -LiteralPath $adaptedScriptSource -Destination (Join-Path $Output "adapted_script.md") -Force
}

# Match the generation duration to the actual reference video instead of a stale default.
$durationSeconds = 12
if (Test-Path -LiteralPath $sourceVideo) {
  $durationText = & ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $sourceVideo
  if ($LASTEXITCODE -eq 0 -and $durationText) {
    $durationSeconds = [math]::Ceiling([double]$durationText)
  }
}
$parametersPath = Join-Path $Output "03-parameters.json"
if (Test-Path -LiteralPath $parametersPath) {
  $parameters = Get-Content -LiteralPath $parametersPath -Raw | ConvertFrom-Json
  $parameters.duration_seconds = $durationSeconds
  $parameters | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $parametersPath -Encoding UTF8
}

$zip = "$Output.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $Output "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Output $zip
