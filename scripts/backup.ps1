[CmdletBinding()]
param(
    [string]$EnvFile = ".env.production",
    [string]$OutputDirectory = "deployment-backups"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path $EnvFile)) { throw "Production environment file not found: $EnvFile" }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$output = (Resolve-Path $OutputDirectory).Path
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$sqlName = "postgres-$stamp.sql"
$dataName = "data-$stamp.zip"
$env:AIOS_ENV_FILE = $EnvFile
$compose = @("compose", "--env-file", $EnvFile)

& docker @compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges > /tmp/aios-backup.sql'
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed." }
& docker @compose cp "postgres:/tmp/aios-backup.sql" (Join-Path $output $sqlName)
if ($LASTEXITCODE -ne 0) { throw "Could not copy PostgreSQL backup." }
& docker @compose exec -T postgres rm -f /tmp/aios-backup.sql

$exportMount = "${output}:/exports"
& docker @compose run --rm --no-deps --volume $exportMount app python -m app.deployment_backup create --data-dir /app/data --output "/exports/$dataName"
if ($LASTEXITCODE -ne 0) { throw "Application data backup failed." }

Write-Host "Backup completed:"
Write-Host "  $(Join-Path $output $sqlName)"
Write-Host "  $(Join-Path $output $dataName)"
Write-Warning "Backups contain application data and secrets. Store them encrypted and restrict access."