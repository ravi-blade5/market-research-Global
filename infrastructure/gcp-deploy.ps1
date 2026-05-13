param(
  [string]$ProjectId = "project-c6c8a787-a2c7-48b7-8b0",
  [string]$Region = "us-central1",
  [string]$Bucket = "$ProjectId-market-research-artifacts",
  [string]$ServiceAccountName = "market-research-runner",
  [string]$SqlInstance = "market-research-db",
  [string]$Database = "market_research",
  [string]$DbUser = "market_research_app",
  [string]$ApiService = "market-research-portal-api",
  [string]$WebService = "market-research-portal-web"
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

gcloud config set project $ProjectId | Out-Null

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$connectionName = "$ProjectId`:$Region`:$SqlInstance"
$dbPassword = gcloud secrets versions access latest --secret DATABASE_PASSWORD --project $ProjectId
$databaseUrl = "postgresql://$DbUser`:$dbPassword@/$Database`?host=/cloudsql/$connectionName"
$temp = New-TemporaryFile
Set-Content -LiteralPath $temp -Value $databaseUrl -NoNewline
$databaseUrlSecretExists = Test-GcloudCommand { gcloud secrets describe DATABASE_URL --project $ProjectId }
if (-not $databaseUrlSecretExists) {
  gcloud secrets create DATABASE_URL --replication-policy automatic --data-file $temp --project $ProjectId
} else {
  gcloud secrets versions add DATABASE_URL --data-file $temp --project $ProjectId
}
Remove-Item -LiteralPath $temp -Force

gcloud run deploy $ApiService `
  --source backend `
  --region $Region `
  --project $ProjectId `
  --service-account $saEmail `
  --allow-unauthenticated `
  --add-cloudsql-instances $connectionName `
  --memory 4Gi `
  --cpu 2 `
  --timeout 3600 `
  --concurrency 10 `
  --set-env-vars "APP_ENV=gcp,RUN_STORE_BACKEND=postgres,ARTIFACT_BACKEND=gcs,GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,GCS_ARTIFACT_BUCKET=$Bucket,DATA_DIR=/tmp/data,ALLOW_LIVE_PROVIDERS=true,AGENT_PARALLELISM=4" `
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,FIRECRAWL_API_KEY=FIRECRAWL_API_KEY:latest,APIFY_API_TOKEN=APIFY_API_TOKEN:latest"

$apiUrl = gcloud run services describe $ApiService --region $Region --project $ProjectId --format "value(status.url)"

gcloud run deploy $WebService `
  --source frontend `
  --region $Region `
  --project $ProjectId `
  --allow-unauthenticated `
  --memory 512Mi `
  --cpu 1 `
  --timeout 300 `
  --set-build-env-vars "VITE_API_BASE=$apiUrl"

$webUrl = gcloud run services describe $WebService --region $Region --project $ProjectId --format "value(status.url)"

Write-Host "Deployment complete."
Write-Host "API: $apiUrl"
Write-Host "Web: $webUrl"
