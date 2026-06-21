# Antigravity Shield - Rule Database Automated Setup Script
# Run this script in PowerShell as Administrator if package installation (winget) is required.

$ErrorActionPreference = "Stop"

# Helper for colorful output
function Write-Header([string]$text) {
    Write-Host "`n=== $text ===" -ForegroundColor Cyan
}

function Write-Success([string]$text) {
    Write-Host "[+] $text" -ForegroundColor Green
}

function Write-WarningMsg([string]$text) {
    Write-Host "[!] $text" -ForegroundColor Yellow
}

function Write-ErrorMsg([string]$text) {
    Write-Host "[ERROR] $text" -ForegroundColor Red
}

Write-Header "Detecting Host Environment"
$isWindows = [Environment]::OSVersion.Platform -eq "Win32NT"
if (-not $isWindows) {
    Write-ErrorMsg "This script is designed to run natively on a Windows Host. For Linux/WSL, please configure manually."
    exit 1
}
Write-Success "Windows Host detected."

# Check for WSL availability
$wslInstalled = $false
try {
    $wslCheck = wsl --list 2>$null
    if ($lastExitCode -eq 0) {
        $wslInstalled = $true
        Write-Success "WSL2 environment detected."
    }
} catch {}

# 1. Verify Dependencies and Install via winget if missing
Write-Header "Checking System Dependencies"

# Git
if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Git is not installed. Attempting to install via winget..."
    try {
        winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
        Write-Success "Git installed successfully. Please restart terminal if path is not refreshed."
    } catch {
        Write-ErrorMsg "Failed to install Git automatically. Please install Git manually: https://git-scm.com/"
    }
} else {
    Write-Success "Git is installed: $((git --version).Trim())"
}

# Python
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Python is not installed. Attempting to install Python 3.11 via winget..."
    try {
        winget install --id Python.Python.3.11 -e --silent --accept-source-agreements --accept-package-agreements
        # Attempt to refresh path env
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Success "Python 3.11 installed successfully."
    } catch {
        Write-ErrorMsg "Failed to install Python automatically. Please install Python 3.11+ manually: https://www.python.org/"
    }
} else {
    Write-Success "Python is installed: $((python --version 2>&1).Trim())"
}

# Ollama
if (!(Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-WarningMsg "Ollama is not installed. Attempting to install via winget..."
    try {
        winget install --id Ollama.Ollama -e --silent --accept-source-agreements --accept-package-agreements
        Write-Success "Ollama installed successfully."
    } catch {
        Write-ErrorMsg "Failed to install Ollama automatically. Please install Ollama manually: https://ollama.com/"
    }
} else {
    Write-Success "Ollama is installed."
}

# Docker
$dockerInstalled = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerInstalled = $true
    Write-Success "Docker is installed."
} else {
    Write-WarningMsg "Docker is not installed. You will need Docker Desktop to run the PostgreSQL database."
    Write-WarningMsg "Attempting to install Docker Desktop via winget..."
    try {
        winget install --id Docker.DockerDesktop -e --silent --accept-source-agreements --accept-package-agreements
        $dockerInstalled = $true
        Write-Success "Docker Desktop installed successfully. Please start Docker Desktop manually."
    } catch {
        Write-ErrorMsg "Failed to install Docker Desktop automatically. Please install Docker Desktop manually: https://www.docker.com/products/docker-desktop/"
    }
}

# Ensure Ollama is running with network exposure (OLLAMA_HOST=0.0.0.0) so WSL can access it
Write-Header "Checking Ollama Service"
$ollamaRunning = $false
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($response) {
        $ollamaRunning = $true
        Write-Success "Ollama service is active and responding."
    }
} catch {}

if (-not $ollamaRunning) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-WarningMsg "Ollama is not running. Configuring OLLAMA_HOST=0.0.0.0 and starting service..."
        # Persist env variable for future runs
        [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "User")
        $env:OLLAMA_HOST = "0.0.0.0"
        
        # Start Ollama service in background
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
        
        # Verify again
        try {
            $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
            if ($response) {
                Write-Success "Ollama service started successfully."
            } else {
                Write-WarningMsg "Ollama started, but endpoint didn't respond. We will proceed anyway."
            }
        } catch {
            Write-WarningMsg "Could not verify Ollama start. Please ensure it is running manually."
        }
    }
}

# Ensure Docker Daemon is running
if ($dockerInstalled) {
    Write-Header "Checking Docker Service"
    $dockerRunning = $false
    try {
        $info = docker info 2>$null
        if ($lastExitCode -eq 0) {
            $dockerRunning = $true
            Write-Success "Docker daemon is active."
        }
    } catch {}

    if (-not $dockerRunning) {
        Write-WarningMsg "Docker daemon is not running. Attempting to launch Docker Desktop..."
        $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $dockerPath) {
            Start-Process $dockerPath -WindowStyle Minimized -ErrorAction SilentlyContinue
            Write-Host "Waiting up to 45 seconds for Docker daemon to initialize..." -ForegroundColor Yellow
            for ($i = 0; $i -lt 15; $i++) {
                Start-Sleep -Seconds 3
                try {
                    docker info >$null 2>&1
                    if ($lastExitCode -eq 0) {
                        $dockerRunning = $true
                        Write-Success "Docker daemon started successfully."
                        break
                    }
                } catch {}
            }
        }
        if (-not $dockerRunning) {
            Write-ErrorMsg "Could not start Docker automatically. Please launch Docker Desktop manually and re-run this script."
            exit 1
        }
    }
}

# 2. Port Detection & Conflict Resolution
Write-Header "Scanning for Port Conflicts"

function Get-NextFreePort([int]$startPort) {
    $port = $startPort
    while ($true) {
        # Check active TCP listeners in Windows
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        $occupied = $listeners | Where-Object { $_.Port -eq $port }
        if ($null -eq $occupied) {
            return $port
        }
        $port++
    }
}

# Default Ports
$defaultDbPort = 5432
$defaultAppPort = 8000

# Check if PostgreSQL port is in use
$dbPort = $defaultDbPort
# Double check if the current occupier is our own container
$containerExists = $false
try {
    $existingContainer = docker ps --filter "name=postgres_vector" --format "{{.Ports}}" 2>$null
    if ($existingContainer -and $existingContainer -like "*:$defaultDbPort->*") {
        $containerExists = $true
    }
} catch {}

if (([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $defaultDbPort }) -and -not $containerExists) {
    Write-WarningMsg "Port $defaultDbPort is in use by another service."
    $dbPort = Get-NextFreePort ($defaultDbPort + 1)
    Write-Success "Allocated free port $dbPort for PostgreSQL."
} else {
    Write-Success "Port $defaultDbPort is available (or occupied by our own container). Using port $defaultDbPort."
}

# Check if FastAPI port is in use
$appPort = $defaultAppPort
if ([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $defaultAppPort }) {
    Write-WarningMsg "Port $defaultAppPort is in use by another service."
    $appPort = Get-NextFreePort ($defaultAppPort + 1)
    Write-Success "Allocated free port $appPort for Web Dashboard."
} else {
    Write-Success "Port $defaultAppPort is available. Using port $defaultAppPort."
}

# 3. Create .env config file
Write-Header "Generating Environment Configuration (.env)"
$envFile = ".env"
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

[System.IO.File]::WriteAllText((Join-Path (Get-Location) $envFile), $envContent)
Write-Success "Configuration saved to [$(Resolve-Path $envFile)]."

# 4. Create and Configure Python Virtual Environment
Write-Header "Configuring Python Virtual Environment"
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment in .venv..." -ForegroundColor Yellow
    python -m venv .venv
}
Write-Success "Virtual environment directory ready."

Write-Host "Upgrading pip and installing python packages from requirements.txt..." -ForegroundColor Yellow
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Success "Python packages installed successfully."

# 5. Pull Ollama Embedding model
Write-Header "Pulling AI Embedding Model"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    try {
        Write-Host "Pulling 'all-minilm' model inside Ollama (this will skip if already downloaded)..." -ForegroundColor Yellow
        ollama pull all-minilm
        Write-Success "Model 'all-minilm' is ready."
    } catch {
        Write-WarningMsg "Failed to pull 'all-minilm' automatically. Please ensure Ollama Desktop app is open and run: ollama pull all-minilm"
    }
}

# 6. Spin up Docker Postgres & Run database.py migrations/restores
Write-Header "Launching Infrastructure Containers"
try {
    Write-Host "Starting PostgreSQL database container..." -ForegroundColor Yellow
    docker compose down --remove-orphans >$null 2>&1
    docker compose up -d
    Write-Success "PostgreSQL pgvector container started."
    
    # Wait for database startup
    Write-Host "Waiting 6 seconds for PostgreSQL to initialize database cluster..." -ForegroundColor Yellow
    Start-Sleep -Seconds 6
    
    # Explicitly pass DB_PORT and env variables to make sure Python script connects to the right port immediately
    $env:DB_PORT = $dbPort
    $env:DB_HOST = "localhost"
    $env:DB_NAME = "rule_db"
    $env:DB_USER = "postgres"
    $env:DB_PASS = "postgres"

    # Check for backup file to restore
    if (Test-Path "rule_db_backup.sql") {
        Write-Host "=== Found database backup rule_db_backup.sql ===" -ForegroundColor Cyan
        Write-Host "Restoring database from backup..." -ForegroundColor Yellow
        Get-Content "rule_db_backup.sql" -Raw | docker exec -i postgres_vector psql -U postgres -d rule_db
        Write-Success "Database restore complete. Skipped schema creation & rule ingestion."
    } else {
        Write-Host "Initializing database schema & vector indexes..." -ForegroundColor Yellow
        & .venv\Scripts\python.exe backend/database.py
        Write-Success "Database schema initialization complete."

        Write-Host "=== Starting automatic rule ingestion (this may take a few minutes) ===" -ForegroundColor Cyan
        & .venv\Scripts\python.exe backend/ingest.py
        Write-Success "Rule ingestion complete."
    }
} catch {
    Write-ErrorMsg "Failed to spin up database container or run migrations: $_"
    exit 1
}

# 7. Register Scheduled Task in Windows Task Scheduler
Write-Header "Registering Scheduled Rule Update Task (2:00 AM daily check)"
try {
    $taskName = "RuleDatabaseAutoUpdate"
    $cronScriptPath = Resolve-Path "cron_sync.ps1"
    
    # Trigger daily at 2:00 AM
    $trigger = New-ScheduledTaskTrigger -Daily -At "2:00 AM"
    
    # Action executes powershell with hidden window running our cron script
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$cronScriptPath`""
    
    # Settings: wake computer, run as soon as possible after missed start
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun
    
    # Register the task
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction SilentlyContinue | Out-Null
    Write-Success "Task Scheduler registered successfully: '$taskName' (runs cron_sync.ps1 daily at 2:00 AM)."
} catch {
    Write-WarningMsg "Could not register Task Scheduler automatically. You can register cron_sync.ps1 manually if desired."
}

# Final Summary instructions
Write-Header "Setup Completed Successfully!"
Write-Host "The application has been configured with the following settings:" -ForegroundColor Green
Write-Host "  - PostgreSQL Port: $dbPort" -ForegroundColor Green
Write-Host "  - Web Dashboard Port: $appPort" -ForegroundColor Green
Write-Host "  - Ollama Model: all-minilm" -ForegroundColor Green
Write-Host ""
Write-Host "=== HOW TO RUN THE APPLICATION ===" -ForegroundColor Cyan
Write-Host "1. Ingest/Sync Threat Detection Rules (First-time only, takes a few minutes):" -ForegroundColor Yellow
Write-Host "   .venv\Scripts\python.exe backend/ingest.py" -ForegroundColor White
Write-Host ""
Write-Host "2. Start the Web Dashboard server:" -ForegroundColor Yellow
Write-Host "   .venv\Scripts\python.exe backend/main.py" -ForegroundColor White
Write-Host "   Once started, open: http://localhost:$appPort" -ForegroundColor White
Write-Host ""
Write-Host "3. Alternatively, if you want to run inside WSL2 Linux:" -ForegroundColor Yellow
Write-Host "   WSL will automatically read the same dynamic ports from the generated .env file!" -ForegroundColor White
Write-Host "   Run backend in WSL:" -ForegroundColor White
Write-Host "     .venv_linux/bin/python backend/main.py" -ForegroundColor White
Write-Host ""
Write-Host "Enjoy your offline Detection-as-Code semantic database! - Antigravity Agent" -ForegroundColor Magenta
