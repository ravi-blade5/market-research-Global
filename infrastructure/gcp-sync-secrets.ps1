param(
  [string]$ProjectId = "project-c6c8a787-a2c7-48b7-8b0",
  [string]$EnvPath = ".\backend\.env"
)

$ErrorActionPreference = "Stop"

function Test-GcloudCommand {
  param([scriptblock]$Command)
  try {
    & $Command 1>$null 2>$null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

if (-not (Test-Path -LiteralPath $EnvPath)) {
  throw "Env file not found: $EnvPath"
}

gcloud config set project $ProjectId | Out-Null

$secretNames = @("OPENAI_API_KEY", "FIRECRAWL_API_KEY", "APIFY_API_TOKEN")
$values = @{}
foreach ($line in Get-Content -LiteralPath $EnvPath) {
  $trimmed = $line.Trim()
  if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
    continue
  }
  $name, $value = $trimmed.Split("=", 2)
  $name = $name.Trim()
  if ($secretNames -contains $name) {
    $values[$name] = $value.Trim().Trim('"').Trim("'")
  }
}

foreach ($name in $secretNames) {
  if (-not $values.ContainsKey($name) -or -not $values[$name]) {
    Write-Warning "Skipping $name because it was not found in $EnvPath"
    continue
  }
  $temp = New-TemporaryFile
  Set-Content -LiteralPath $temp -Value $values[$name] -NoNewline
  $secretExists = Test-GcloudCommand { gcloud secrets describe $name --project $ProjectId }
  if (-not $secretExists) {
    gcloud secrets create $name --replication-policy automatic --data-file $temp --project $ProjectId
  } else {
    gcloud secrets versions add $name --data-file $temp --project $ProjectId
  }
  Remove-Item -LiteralPath $temp -Force
  Write-Host "Synced secret $name"
}
