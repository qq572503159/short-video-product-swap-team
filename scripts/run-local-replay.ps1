param(
  [string]$Project = "projects/demo-9-16",
  [string]$GeneratedVideo = "",
  [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $root $Project
$reference = Join-Path $projectPath "inputs\reference.mp4"
if (-not $GeneratedVideo) {
  $GeneratedVideo = Join-Path $projectPath "outputs\newapi\generated.mp4"
}
if (-not $OutputDirectory) {
  $OutputDirectory = Join-Path $projectPath "outputs\local-replay"
}
if (-not (Test-Path -LiteralPath $reference)) { throw "找不到参考视频: $reference" }
if (-not (Test-Path -LiteralPath $GeneratedVideo)) { throw "找不到既有生成画面: $GeneratedVideo" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "未找到 ffmpeg" }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw "未找到 ffprobe" }

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$durationText = (& ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 $reference).Trim()
$duration = [double]::Parse($durationText, [Globalization.CultureInfo]::InvariantCulture)
$durationArg = $duration.ToString("0.######", [Globalization.CultureInfo]::InvariantCulture)
$audio = Join-Path $OutputDirectory "01-original-audio.m4a"
$silent = Join-Path $OutputDirectory "02-generated-picture-normalized.mp4"
$final = Join-Path $OutputDirectory "03-final-local-replay.mp4"
$sheet = Join-Path $OutputDirectory "04-final-contact-sheet.jpg"

& ffmpeg -y -hide_banner -loglevel error -i $reference -vn -map 0:a:0 -c:a copy -t $durationArg $audio
if ($LASTEXITCODE -ne 0) { throw "提取原音轨失败" }

& ffmpeg -y -hide_banner -loglevel error -i $GeneratedVideo `
  -vf "trim=duration=$durationArg,setpts=PTS-STARTPTS,fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black" `
  -an -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -movflags +faststart $silent
if ($LASTEXITCODE -ne 0) { throw "规范化生成画面失败" }

& ffmpeg -y -hide_banner -loglevel error -i $silent -i $audio `
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy -shortest -movflags +faststart $final
if ($LASTEXITCODE -ne 0) { throw "本地音视频合成失败" }

& ffmpeg -y -hide_banner -loglevel error -i $final `
  -vf "fps=1,scale=240:-1,tile=4x3" -frames:v 1 $sheet
if ($LASTEXITCODE -ne 0) { throw "生成质检联系表失败" }

$probe = & ffprobe -v error -show_entries format=duration:stream=codec_name,codec_type,width,height,r_frame_rate -of json $final
$summary = [ordered]@{
  status = "completed"
  source_reference = (Resolve-Path $reference).Path
  reused_generated_picture = (Resolve-Path $GeneratedVideo).Path
  target_duration_seconds = $duration
  original_audio = $audio
  normalized_picture = $silent
  final_video = $final
  contact_sheet = $sheet
  media_probe = $probe | ConvertFrom-Json
  external_generation_submitted = $false
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory "local-replay-report.json") -Encoding UTF8
$summary | ConvertTo-Json -Depth 8
