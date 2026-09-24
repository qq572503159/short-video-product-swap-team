param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$HypitArgs
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\secrets\newapi.env"

if (-not (Test-Path -LiteralPath $envFile)) {
  throw "New API environment file not found: $envFile"
}

Get-Content -LiteralPath $envFile | ForEach-Object {
  $line = $_.Trim()
  if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name) {
      Set-Item -Path "Env:$name" -Value $value
    }
  }
}

Push-Location $projectRoot
try {
  & hypit @HypitArgs
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
