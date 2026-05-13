param(
  [string]$ProjectId = "project-c6c8a787-a2c7-48b7-8b0",
  [string]$Region = "us-central1",
  [string]$Bucket = "$ProjectId-market-research-artifacts",
  [string]$ArtifactRepo = "market-research",
  [string]$ServiceAccountName = "market-research-runner",
  [string]$TasksQueue = "market-research-runs",
  [string]$SqlInstance = "market-research-db",
  [string]$Database = "market_research",
  [string]$DbUser = "market_research_app"
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

$services = @(
  "run.googleapis.com",
  "cloudbuild.googleapis.com",
  "artifactregistry.googleapis.com",
  "secretmanager.googleapis.com",
  "sqladmin.googleapis.com",
  "storage.googleapis.com",
  "cloudtasks.googleapis.com",
  "workflows.googleapis.com",
  "iamcredentials.googleapis.com"
)
$enabledServices = @(gcloud services list --enabled --project $ProjectId --format "value(config.name)")
$missingServices = @($services | Where-Object { $enabledServices -notcontains $_ })
if ($missingServices.Count -gt 0) {
  gcloud services enable $missingServices --project $ProjectId
}

$saEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$saExists = Test-GcloudCommand { gcloud iam service-accounts describe $saEmail --project $ProjectId }
if (-not $saExists) {
  gcloud iam service-accounts create $ServiceAccountName --display-name "Market Research Portal Runner" --project $ProjectId
}

$roles = @(
  "roles/cloudsql.client",
  "roles/storage.objectAdmin",
  "roles/secretmanager.secretAccessor",
  "roles/logging.logWriter",
  "roles/monitoring.metricWriter",
  "roles/cloudtasks.enqueuer",
  "roles/workflows.invoker"
)
foreach ($role in $roles) {
  try {
    gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$saEmail" --role $role --quiet | Out-Null
  } catch {
    Write-Warning "Could not bind $role to $saEmail. You may need Project IAM Admin permissions."
  }
}

$artifactRepoExists = Test-GcloudCommand { gcloud artifacts repositories describe $ArtifactRepo --location $Region --project $ProjectId }
if (-not $artifactRepoExists) {
  gcloud artifacts repositories create $ArtifactRepo --repository-format docker --location $Region --description "Market research portal containers" --project $ProjectId
}

$bucketExists = Test-GcloudCommand { gcloud storage buckets describe "gs://$Bucket" --project $ProjectId }
if (-not $bucketExists) {
  gcloud storage buckets create "gs://$Bucket" --project $ProjectId --location $Region --uniform-bucket-level-access
}

$queueExists = Test-GcloudCommand { gcloud tasks queues describe $TasksQueue --location $Region --project $ProjectId }
if (-not $queueExists) {
  gcloud tasks queues create $TasksQueue `
    --location $Region `
    --max-concurrent-dispatches 2 `
    --max-dispatches-per-second 0.2 `
    --max-attempts 10 `
    --min-backoff 60s `
    --max-backoff 900s `
    --project $ProjectId
}

$sqlExists = Test-GcloudCommand { gcloud sql instances describe $SqlInstance --project $ProjectId }
if (-not $sqlExists) {
  gcloud sql instances create $SqlInstance `
    --database-version POSTGRES_16 `
    --edition ENTERPRISE `
    --tier db-f1-micro `
    --region $Region `
    --storage-size 20GB `
    --availability-type ZONAL `
    --project $ProjectId
}

$databaseExists = Test-GcloudCommand { gcloud sql databases describe $Database --instance $SqlInstance --project $ProjectId }
if (-not $databaseExists) {
  gcloud sql databases create $Database --instance $SqlInstance --project $ProjectId
}

$passwordSecret = "DATABASE_PASSWORD"
$taskTokenSecret = "TASK_DISPATCH_TOKEN"
$existingPassword = $null
try {
  $existingPassword = gcloud secrets versions access latest --secret $passwordSecret --project $ProjectId 2>$null
} catch {
  $existingPassword = $null
}
$dbPassword = $existingPassword
if (-not $existingPassword) {
  $bytes = New-Object byte[] 24
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  $dbPassword = [Convert]::ToBase64String($bytes).TrimEnd("=") -replace "[+/]", "A"
  $temp = New-TemporaryFile
  Set-Content -LiteralPath $temp -Value $dbPassword -NoNewline
  $secretExists = Test-GcloudCommand { gcloud secrets describe $passwordSecret --project $ProjectId }
  if (-not $secretExists) {
    gcloud secrets create $passwordSecret --replication-policy automatic --data-file $temp --project $ProjectId
  } else {
    gcloud secrets versions add $passwordSecret --data-file $temp --project $ProjectId
  }
  Remove-Item -LiteralPath $temp -Force
}

$userExists = $false
try {
  $users = @(gcloud sql users list --instance $SqlInstance --project $ProjectId --format "value(name)")
  $userExists = $users -contains $DbUser
} catch {
  $userExists = $false
}
if (-not $userExists -and $dbPassword) {
  gcloud sql users create $DbUser --instance $SqlInstance --password $dbPassword --project $ProjectId
}

$existingTaskToken = $null
try {
  $existingTaskToken = gcloud secrets versions access latest --secret $taskTokenSecret --project $ProjectId 2>$null
} catch {
  $existingTaskToken = $null
}
if (-not $existingTaskToken) {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  $taskToken = [Convert]::ToBase64String($bytes).TrimEnd("=") -replace "[+/]", "T"
  $temp = New-TemporaryFile
  Set-Content -LiteralPath $temp -Value $taskToken -NoNewline
  $taskSecretExists = Test-GcloudCommand { gcloud secrets describe $taskTokenSecret --project $ProjectId }
  if (-not $taskSecretExists) {
    gcloud secrets create $taskTokenSecret --replication-policy automatic --data-file $temp --project $ProjectId
  } else {
    gcloud secrets versions add $taskTokenSecret --data-file $temp --project $ProjectId
  }
  Remove-Item -LiteralPath $temp -Force
}

Write-Host "GCP baseline ready."
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host "Service account: $saEmail"
Write-Host "Bucket: gs://$Bucket"
Write-Host "Cloud SQL: $ProjectId`:$Region`:$SqlInstance"
Write-Host "Cloud Tasks queue: $TasksQueue"
