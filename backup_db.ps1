# Antigravity Shield - Database Backup Tool for Windows
# Usage: .\backup_db.ps1

$ErrorActionPreference = "Stop"

# Default configuration
$dbUser = "postgres"
$dbName = "rule_db"

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
$containerName = "postgres_vector"
$containerStatus = docker inspect --format="{{.State.Running}}" $containerName 2>$null

if ($containerStatus -ne "true") {
    Write-Host "Error: Docker container '$containerName' is not running!" -ForegroundColor Red
    Write-Host "Please start the database container first by running 'docker compose up -d'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Backing up database '$dbName' from container '$containerName'..." -ForegroundColor Yellow
try {
    # Run pg_dump inside container and redirect output to host file
    docker exec -t $containerName pg_dump -U $dbUser -d $dbName > rule_db_backup.sql
    
    if (Test-Path "rule_db_backup.sql") {
        $fileSize = (Get-Item "rule_db_backup.sql").Length
        if ($fileSize -gt 100) {
            Write-Host "Database backup completed successfully!" -ForegroundColor Green
            Write-Host "Backup file saved to: $(Resolve-Path rule_db_backup.sql) ($($fileSize.ToString('N0')) bytes)" -ForegroundColor Green
        } else {
            Write-Host "Warning: Backup file is empty or too small. Check for postgres errors." -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "Error during database backup: $_" -ForegroundColor Red
}
