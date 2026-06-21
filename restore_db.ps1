# Antigravity Shield - Database Restore Tool for Windows
# Usage: .\restore_db.ps1

$ErrorActionPreference = "Stop"

# Default configuration
$dbUser = "postgres"
$dbName = "rule_db"
$containerName = "postgres_vector"

if (-not (Test-Path "rule_db_backup.sql")) {
    Write-Host "Error: rule_db_backup.sql not found in current directory!" -ForegroundColor Red
    Write-Host "Please place your backup file 'rule_db_backup.sql' in this folder." -ForegroundColor Yellow
    exit 1
}

# Try to read credentials from local .env
if (Test-Path ".env") {
    $envContent = Get-Content ".env"
    foreach ($line in $envContent) {
        $line = $line.Trim()
        if ($line -match "^DB_USER=(.*)") { $dbUser = $Matches[1].Trim() }
        if ($line -match "^DB_NAME=(.*)") { $dbName = $Matches[1].Trim() }
    }
}

# Verify Docker container is running
$containerStatus = docker inspect --format="{{.State.Running}}" $containerName 2>$null

if ($containerStatus -ne "true") {
    Write-Host "Error: Docker container '$containerName' is not running!" -ForegroundColor Red
    Write-Host "Please start the database container first by running 'docker compose up -d'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Restoring database '$dbName' in container '$containerName' from 'rule_db_backup.sql'..." -ForegroundColor Yellow
try {
    # Pipe database backup to container's psql utility
    Get-Content "rule_db_backup.sql" -Raw | docker exec -i $containerName psql -U $dbUser -d $dbName
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Database restored successfully!" -ForegroundColor Green
    } else {
        Write-Host "Database restore failed. Check psql logs above." -ForegroundColor Red
    }
} catch {
    Write-Host "Error during database restore: $_" -ForegroundColor Red
}
