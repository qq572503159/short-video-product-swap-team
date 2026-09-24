param(
  [string]$GeneratedVideo = ".\generated-silent.mp4",
  [string]$OriginalAudio = ".\original-audio.m4a",
  [string]$Output = ".\final-with-original-audio.mp4"
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "未找到 ffmpeg。" }
if (-not (Test-Path -LiteralPath $GeneratedVideo)) { throw "找不到生成视频: $GeneratedVideo" }
if (-not (Test-Path -LiteralPath $OriginalAudio)) { throw "找不到原音轨: $OriginalAudio" }
& ffmpeg -y -hide_banner -loglevel error -i $GeneratedVideo -i $OriginalAudio `
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart $Output
if ($LASTEXITCODE -ne 0) { throw "音视频合并失败" }
Write-Output "已生成: $Output"
