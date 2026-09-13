[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,
    [string]$EnvFile = ".env.production",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if (-not $Force) { throw "Restore replaces the current database and application data. Re-run with -Force." }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path $EnvFile)) { throw "Production environment file not found: $EnvFile" }
$source = (Resolve-Path $BackupDirectory).Path
$sql = Get-ChildItem -LiteralPath $source -Filter "postgres-*.sql" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$data = Get-ChildItem -LiteralPath $source -Filter "data-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $sql -or -not $data) { throw "Backup directory must contain postgres-*.sql and data-*.zip files." }
$env:AIOS_ENV_FILE = $EnvFile
$compose = @("compose", "--env-file", $EnvFile)

& docker @compose stop nginx app worker scheduler monitoring
if ($LASTEXITCODE -ne 0) { throw "Could not stop application services." }
& docker @compose cp $sql.FullName "postgres:/tmp/aios-restore.sql"
if ($LASTEXITCODE -ne 0) { throw "Could not copy PostgreSQL restore file." }
& docker @compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /tmp/aios-restore.sql'
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed; application services remain stopped." }
& docker @compose exec -T postgres rm -f /tmp/aios-restore.sql

$restoreMount = "${source}:/restore:ro"
& docker @compose run --rm --no-deps --volume $restoreMount app python -m app.deployment_backup restore "/restore/$($data.Name)" --data-dir /app/data --force
if ($LASTEXITCODE -ne 0) { throw "Application data restore failed; application services remain stopped." }

& docker @compose up -d app worker scheduler monitoring nginx
if ($LASTEXITCODE -ne 0) { throw "Restore succeeded, but services did not restart cleanly." }
Write-Host "Restore completed from $source"