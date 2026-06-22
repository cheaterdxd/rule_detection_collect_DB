# Antigravity Shield - Rule Database Automated Setup Script (Windows)
# Run this script in PowerShell as Administrator if package installation (winget) is required.

$ErrorActionPreference = "Stop"

function Write-Header([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Success([string]$text) { Write-Host "[+] $text" -ForegroundColor Green }
function Write-WarningMsg([string]$text) { Write-Host "[!] $text" -ForegroundColor Yellow }
function Write-ErrorMsg([string]$text) { Write-Host "[ERROR] $text" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# 0. Platform guard
# ---------------------------------------------------------------------------
Write-Header "Detecting Host Environment"
if ([Environment]::OSVersion.Platform -ne "Win32NT") {
    Write-ErrorMsg "This script is for Windows. For Linux/WSL, run setup.sh instead."
    exit 1
}
Write-Success "Windows Host detected."

# ---------------------------------------------------------------------------
# 1. Dependencies
# ---------------------------------------------------------------------------
Write-Header "Checking System Dependencies"

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Git not found — installing via winget..."
    winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
    Write-Success "Git installed."
} else {
    Write-Success "Git: $((git --version).Trim())"
}

if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Python not found — installing Python 3.11 via winget..."
    winget install --id Python.Python.3.11 -e --silent --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Success "Python 3.11 installed."
} else {
    Write-Success "Python: $((python --version 2>&1).Trim())"
}

if (!(Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Ollama not found — installing via winget..."
    winget install --id Ollama.Ollama -e --silent --accept-source-agreements --accept-package-agreements
    Write-Success "Ollama installed."
} else {
    Write-Success "Ollama is installed."
}

$dockerInstalled = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerInstalled = $true
    Write-Success "Docker is installed."
} else {
    Write-WarningMsg "Docker not found — installing Docker Desktop via winget..."
    try {
        winget install --id Docker.DockerDesktop -e --silent --accept-source-agreements --accept-package-agreements
        $dockerInstalled = $true
        Write-Success "Docker Desktop installed. Please start it once manually."
    } catch {
        Write-ErrorMsg "Could not install Docker Desktop automatically. Install manually: https://www.docker.com/products/docker-desktop/"
    }
}

# ---------------------------------------------------------------------------
# 2. Ollama — ensure service is running and model is reachable
# ---------------------------------------------------------------------------
Write-Header "Checking Ollama Service"

# Candidate addresses to probe (in priority order)
$ollamaCandidates = @("http://127.0.0.1:11434", "http://localhost:11434", "http://0.0.0.0:11434")

function Test-OllamaAt([string]$url) {
    try {
        $r = Invoke-RestMethod -Uri "$url/api/tags" -Method Get -TimeoutSec 3 -ErrorAction Stop
        return $r -ne $null
    } catch { return $false }
}

function Find-OllamaUrl {
    foreach ($url in $ollamaCandidates) {
        if (Test-OllamaAt $url) { return $url }
    }
    return $null
}

$ollamaUrl = Find-OllamaUrl

if (-not $ollamaUrl) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-WarningMsg "Ollama not responding. Setting OLLAMA_HOST=0.0.0.0 and starting service..."
        [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "User")
        $env:OLLAMA_HOST = "0.0.0.0"
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
        Write-Host "Waiting for Ollama to start (up to 20 seconds)..." -ForegroundColor Yellow
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 2
            $ollamaUrl = Find-OllamaUrl
            if ($ollamaUrl) { break }
        }
    }
}

if ($ollamaUrl) {
    Write-Success "Ollama is responding at $ollamaUrl"
} else {
    Write-WarningMsg "Ollama did not respond on any candidate address. The app will attempt auto-discovery at runtime."
    Write-WarningMsg "If semantic search fails, open Ollama Desktop manually and re-run this script."
}

# ---------------------------------------------------------------------------
# 3. Ollama model — pull if not present
# ---------------------------------------------------------------------------
Write-Header "Pulling AI Embedding Model (all-minilm)"
if ($ollamaUrl -and (Get-Command ollama -ErrorAction SilentlyContinue)) {
    try {
        # Check if model is already pulled
        $tags = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -Method Get -TimeoutSec 5 -ErrorAction SilentlyContinue
        $modelReady = $tags.models | Where-Object { $_.name -like "all-minilm*" }
        if ($modelReady) {
            Write-Success "Model 'all-minilm' is already downloaded."
        } else {
            Write-Host "Downloading 'all-minilm' model..." -ForegroundColor Yellow
            ollama pull all-minilm
            Write-Success "Model 'all-minilm' downloaded."
        }
    } catch {
        Write-WarningMsg "Could not pull model automatically. Run: ollama pull all-minilm"
    }
} else {
    Write-WarningMsg "Skipping model pull (Ollama unavailable). Run: ollama pull all-minilm"
}

# ---------------------------------------------------------------------------
# 4. Docker daemon
# ---------------------------------------------------------------------------
if ($dockerInstalled) {
    Write-Header "Checking Docker Service"
    $dockerRunning = $false
    try {
        docker info > $null 2>&1
        if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
    } catch {}

    if (-not $dockerRunning) {
        Write-WarningMsg "Docker daemon is not running. Attempting to launch Docker Desktop..."
        $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $dockerPath) {
            Start-Process $dockerPath -WindowStyle Minimized -ErrorAction SilentlyContinue
            Write-Host "Waiting up to 60 seconds for Docker daemon to initialize..." -ForegroundColor Yellow
            for ($i = 0; $i -lt 20; $i++) {
                Start-Sleep -Seconds 3
                docker info > $null 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $dockerRunning = $true
                    Write-Success "Docker daemon started."
                    break
                }
            }
        }
        if (-not $dockerRunning) {
            Write-ErrorMsg "Could not start Docker. Launch Docker Desktop manually and re-run this script."
            exit 1
        }
    } else {
        Write-Success "Docker daemon is active."
    }
}

# ---------------------------------------------------------------------------
# 5. Port detection
# ---------------------------------------------------------------------------
Write-Header "Scanning for Port Conflicts"

function Get-NextFreePort([int]$startPort) {
    $port = $startPort
    while ($true) {
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        if (-not ($listeners | Where-Object { $_.Port -eq $port })) { return $port }
        $port++
    }
}

$defaultDbPort = 5432
$defaultAppPort = 8000

# Check if the occupied DB port is already our own container
$containerHoldsPort = $false
try {
    $existing = docker ps --filter "name=postgres_vector" --format "{{.Ports}}" 2>$null
    if ($existing -and $existing -like "*:$defaultDbPort->*") { $containerHoldsPort = $true }
} catch {}

$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if (($listeners | Where-Object { $_.Port -eq $defaultDbPort }) -and -not $containerHoldsPort) {
    Write-WarningMsg "Port $defaultDbPort is in use by another service."
    $dbPort = Get-NextFreePort ($defaultDbPort + 1)
    Write-Success "Allocated port $dbPort for PostgreSQL."
} else {
    $dbPort = $defaultDbPort
    Write-Success "Port $defaultDbPort available (or occupied by our container)."
}

if ($listeners | Where-Object { $_.Port -eq $defaultAppPort }) {
    Write-WarningMsg "Port $defaultAppPort is in use by another service."
    $appPort = Get-NextFreePort ($defaultAppPort + 1)
    Write-Success "Allocated port $appPort for Web Dashboard."
} else {
    $appPort = $defaultAppPort
    Write-Success "Port $defaultAppPort available."
}

# ---------------------------------------------------------------------------
# 6. Generate .env
# ---------------------------------------------------------------------------
Write-Header "Generating Environment Configuration (.env)"
$envContent = @"
# Auto-generated by setup.ps1 on $(Get-Date)
DB_PORT=$dbPort
APP_PORT=$appPort
DB_HOST=localhost
DB_NAME=rule_db
DB_USER=postgres
DB_PASS=postgres
OLLAMA_MODEL=all-minilm
"@
[System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), $envContent)
Write-Success "Configuration saved to .env"

# ---------------------------------------------------------------------------
# 7. Python virtual environment & packages
# ---------------------------------------------------------------------------
Write-Header "Configuring Python Virtual Environment"
if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv..." -ForegroundColor Yellow
    python -m venv .venv
}
Write-Host "Installing Python packages..." -ForegroundColor Yellow
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Success "Python packages installed."

# ---------------------------------------------------------------------------
# 8. Database container + health check
# ---------------------------------------------------------------------------
Write-Header "Launching PostgreSQL Container"

# Set env vars for Python scripts
$env:DB_PORT = $dbPort
$env:DB_HOST = "localhost"
$env:DB_NAME = "rule_db"
$env:DB_USER = "postgres"
$env:DB_PASS = "postgres"

try {
    docker compose down --remove-orphans > $null 2>&1
    docker compose up -d
    Write-Success "PostgreSQL pgvector container started."
} catch {
    Write-ErrorMsg "Failed to start database container: $_"
    exit 1
}

# Wait for PostgreSQL to be truly ready (pg_isready loop)
Write-Host "Waiting for PostgreSQL to accept connections..." -ForegroundColor Yellow
$pgReady = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    try {
        $result = docker exec postgres_vector pg_isready -U postgres 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pgReady = $true
            Write-Success "PostgreSQL is ready to accept connections."
            break
        }
    } catch {}
}
if (-not $pgReady) {
    Write-ErrorMsg "PostgreSQL did not become ready in time. Check: docker logs postgres_vector"
    exit 1
}

# Restore from backup or initialize schema
if (Test-Path "rule_db_backup.sql") {
    Write-Header "Restoring Database from Backup"
    Get-Content "rule_db_backup.sql" -Raw | docker exec -i postgres_vector psql -U postgres -d rule_db
    Write-Success "Database restored from rule_db_backup.sql."
} else {
    Write-Header "Initializing Database Schema"
    & .venv\Scripts\python.exe backend/database.py
    Write-Success "Schema and vector indexes created."

    Write-Header "Starting Rule Ingestion"
    Write-Host "This pulls rules from GitHub and generates embeddings. May take several minutes..." -ForegroundColor Yellow
    & .venv\Scripts\python.exe backend/ingest.py
    Write-Success "Rule ingestion complete."
}

# Post-install database health check — verify schema and a basic query work
Write-Header "Post-Install Database Health Check"
$healthScript = @'
import sys
sys.path.insert(0, "backend")
from database import get_db_connection
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rules;")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"OK:{count}")
except Exception as e:
    print(f"FAIL:{e}")
    sys.exit(1)
'@

$healthResult = & .venv\Scripts\python.exe -c $healthScript 2>&1
if ($healthResult -like "OK:*") {
    $ruleCount = ($healthResult -split ":")[1].Trim()
    Write-Success "Database health check passed — $ruleCount rules found in database."
} else {
    Write-ErrorMsg "Database health check FAILED: $healthResult"
    Write-ErrorMsg "The app may not function correctly. Check docker logs postgres_vector"
    exit 1
}

# Verify Ollama embedding works end-to-end (non-fatal)
Write-Header "Verifying Ollama Embedding (end-to-end)"
$ollamaScript = @'
import sys
sys.path.insert(0, "backend")
from database import get_ollama_embedding, _resolve_ollama_host
try:
    host = _resolve_ollama_host()
    emb = get_ollama_embedding("test connectivity")
    print(f"OK:{host}:{len(emb)}")
except Exception as e:
    print(f"FAIL:{e}")
    sys.exit(1)
'@

$ollamaResult = & .venv\Scripts\python.exe -c $ollamaScript 2>&1
if ($ollamaResult -like "OK:*") {
    $parts = $ollamaResult -split ":"
    Write-Success "Ollama embedding OK — host=$($parts[1]), vector dimensions=$($parts[2])"
} else {
    Write-WarningMsg "Ollama embedding check failed: $ollamaResult"
    Write-WarningMsg "Semantic search will be unavailable. Keyword search still works."
    Write-WarningMsg "Fix: Open Ollama Desktop, run `ollama pull all-minilm`, then restart the app."
}

# ---------------------------------------------------------------------------
# 9. Register Windows Task Scheduler (daily sync at 2 AM)
# ---------------------------------------------------------------------------
Write-Header "Registering Scheduled Rule Update Task (2:00 AM daily)"
try {
    $taskName = "RuleDatabaseAutoUpdate"
    $cronScriptPath = Resolve-Path "cron_sync.ps1"
    $trigger = New-ScheduledTaskTrigger -Daily -At "2:00 AM"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$cronScriptPath`""
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction SilentlyContinue | Out-Null
    Write-Success "Task Scheduler registered: '$taskName' (runs cron_sync.ps1 daily at 2:00 AM)."
} catch {
    Write-WarningMsg "Could not register Task Scheduler. You can register cron_sync.ps1 manually if desired."
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Header "Setup Completed Successfully!"
Write-Host ""
Write-Host "  PostgreSQL Port : $dbPort" -ForegroundColor Green
Write-Host "  Web Server Port : $appPort" -ForegroundColor Green
Write-Host "  Ollama Model    : all-minilm" -ForegroundColor Green
Write-Host ""
Write-Host "=== HOW TO START THE APPLICATION ===" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe backend/main.py" -ForegroundColor White
Write-Host "  Then open: http://localhost:$appPort" -ForegroundColor White
Write-Host ""
Write-Host "Enjoy your offline Detection-as-Code semantic database! — Antigravity Agent" -ForegroundColor Magenta
