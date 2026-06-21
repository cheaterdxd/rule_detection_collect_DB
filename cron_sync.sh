#!/bin/bash

# Antigravity Shield - Scheduled Rule Update Script for Linux/macOS
# Triggered daily by Cron at 2:00 AM.
# Only runs full ingestion if 14 days have passed.

# Resolve project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

LAST_SYNC_FILE="$PROJECT_DIR/.last_sync"
SHOULD_SYNC=false

if [ -f "$LAST_SYNC_FILE" ]; then
    LAST_SYNC_STR=$(cat "$LAST_SYNC_FILE" | tr -d '\n\r ')
    # Calculate days passed
    if command -v date >/dev/null 2>&1; then
        # Parse date
        if [[ "$OSTYPE" == "darwin"* ]]; then
            LAST_SYNC_SEC=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${LAST_SYNC_STR:0:19}" "+%s" 2>/dev/null || date -j -f "%s" "$LAST_SYNC_STR" "+%s" 2>/dev/null || echo 0)
        else
            LAST_SYNC_SEC=$(date -d "$LAST_SYNC_STR" "+%s" 2>/dev/null || echo 0)
        fi
        CURRENT_SEC=$(date "+%s")
        DIFF_SEC=$((CURRENT_SEC - LAST_SYNC_SEC))
        DIFF_DAYS=$((DIFF_SEC / 86400))
        
        if [ "$DIFF_DAYS" -ge 14 ]; then
            SHOULD_SYNC=true
        fi
    else
        SHOULD_SYNC=true
    fi
else
    SHOULD_SYNC=true
fi

if [ "$SHOULD_SYNC" = false ]; then
    exit 0
fi

echo "=== 14 days passed since last sync. Starting Scheduled Rule Update ==="

# Read .env
DB_PORT=5432
if [ -f .env ]; then
    DB_PORT=$(grep -E "^DB_PORT=" .env | cut -d'=' -f2 | tr -d '"'\'' ' || echo "5432")
fi

# Ensure Docker Daemon is active
if [ "$(uname)" != "Darwin" ]; then
    if ! sudo systemctl is-active --quiet docker 2>/dev/null; then
        sudo systemctl start docker || true
        sleep 3
    fi
fi

if docker info &>/dev/null; then
    SUDO_DOCKER=""
else
    SUDO_DOCKER="sudo"
fi

# Resolve docker compose command
DOCKER_COMPOSE_CMD="docker compose"
if ! docker compose version &>/dev/null; then
    if docker-compose version &>/dev/null; then
        DOCKER_COMPOSE_CMD="docker-compose"
    fi
fi

# Start Ollama service if not active
if ! curl -s -m 2 http://localhost:11434/api/tags &> /dev/null; then
    if systemctl list-unit-files 2>/dev/null | grep -q ollama &> /dev/null; then
        sudo systemctl start ollama || true
    else
        OLLAMA_HOST=0.0.0.0 ollama serve > /dev/null 2>&1 &
        sleep 4
    fi
fi

# Pull embedding model
ollama pull all-minilm || true

# Start DB container
$SUDO_DOCKER $DOCKER_COMPOSE_CMD up -d
sleep 5

# Run ingestion script
DB_PORT=$DB_PORT DB_HOST=localhost DB_NAME=rule_db DB_USER=postgres DB_PASS=postgres .venv/bin/python3 backend/ingest.py

# Update last sync timestamp (fallback, ingest.py already does this)
if [ $? -eq 0 ]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$LAST_SYNC_FILE"
    echo "Scheduled update complete. Last sync timestamp updated."
else
    echo "Scheduled Rule Update Ingestion failed."
    exit 1
fi
