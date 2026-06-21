# Antigravity Shield - Scheduled Rule Update Script for Windows
# This script is triggered daily by Windows Task Scheduler at 2:00 AM.
# It only runs the full ingestion if 14 days have passed since the last sync.

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$lastSyncFile = Join-Path $projectDir ".last_sync"
$shouldSync = $false

if (Test-Path $lastSyncFile) {
    $lastSyncStr = Get-Content $lastSyncFile -Raw
    if ([DateTime]::TryParse($lastSyncStr.Trim(), [ref]$lastSyncDate)) {
        $daysPassed = ((Get-Date) - $lastSyncDate).TotalDays
        if ($daysPassed -ge 14) {
            $shouldSync = $true
        }
    } else {
        $shouldSync = $true
    }
} else {
    $shouldSync = $true
}

if (-not $shouldSync) {
    # Exit silently, not enough days passed
    exit 0
}

Write-Output "=== 14 days passed since last sync. Starting Scheduled Rule Update ==="

# 1. Read .env port configuration
$dbPort = 5432
if (Test-Path ".env") {
    $envContent = Get-Content ".env"
    foreach ($line in $envContent) {
        if ($line -match "^DB_PORT=(.*)") { $dbPort = $Matches[1].Trim() }
    }
}

# 2. Check and start Docker Daemon
$dockerRunning = $false
try {
    docker info >$null 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}

if (-not $dockerRunning) {
    $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerPath) {
        Start-Process $dockerPath -WindowStyle Minimized -ErrorAction SilentlyContinue
        # Wait up to 45s
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 3
            try {
                docker info >$null 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $dockerRunning = $true
                    break
                }
            } catch {}
        }
    }
}

if (-not $dockerRunning) {
    Write-Error "Scheduled Update Failed: Docker is not running!"
    exit 1
}

# 3. Check and start Ollama service
$ollamaRunning = $false
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($response) { $ollamaRunning = $true }
} catch {}

if (-not $ollamaRunning) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        $env:OLLAMA_HOST = "0.0.0.0"
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    }
}

# 4. Pull embeddings model to be safe
try {
    ollama pull all-minilm
} catch {}

# 5. Run docker-compose to make sure PG is up
docker compose up -d
Start-Sleep -Seconds 5

# 6. Run ingest
$env:DB_PORT = $dbPort
$env:DB_HOST = "localhost"
$env:DB_NAME = "rule_db"
$env:DB_USER = "postgres"
$env:DB_PASS = "postgres"

Write-Output "Running rule ingestion..."
$ingestResult = & .venv\Scripts\python.exe backend/ingest.py 2>&1

# 7. Update last sync time if successful (already done inside ingest.py, but we write it here as fallback too)
if ($LASTEXITCODE -eq 0) {
    (Get-Date).ToString("o") | Out-File $lastSyncFile -Encoding utf8
    Write-Output "Scheduled update complete. Last sync timestamp updated."
} else {
    Write-Error "Scheduled Rule Update Ingestion failed: $ingestResult"
    exit 1
}
