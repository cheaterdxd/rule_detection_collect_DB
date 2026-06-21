#!/bin/bash

# Antigravity Shield - Database Restore Tool for Linux/macOS
# Usage: chmod +x restore_db.sh && ./restore_db.sh

set -e

# Default configuration
DB_USER="postgres"
DB_NAME="rule_db"
CONTAINER_NAME="postgres_vector"

if [ ! -f rule_db_backup.sql ]; then
    echo -e "\033[0;31mError: rule_db_backup.sql not found in current directory!\033[0m"
    echo -e "\033[0;33mPlease place your backup file 'rule_db_backup.sql' in this folder.\033[0m"
    exit 1
fi

# Read credentials from .env if exists
if [ -f .env ]; then
    DB_USER=$(grep -E "^DB_USER=" .env | cut -d'=' -f2 | tr -d '"'\'' ' || echo "postgres")
    DB_NAME=$(grep -E "^DB_NAME=" .env | cut -d'=' -f2 | tr -d '"'\'' ' || echo "rule_db")
fi

# Verify container is running
if [ "$(docker inspect --format='{{.State.Running}}' $CONTAINER_NAME 2>/dev/null)" != "true" ]; then
    echo -e "\033[0;31mError: Docker container '$CONTAINER_NAME' is not running!\033[0m"
    echo -e "\033[0;33mPlease start the database container first by running 'docker compose up -d'\033[0m"
    exit 1
fi

echo -e "\033[0;33mRestoring database '$DB_NAME' in container '$CONTAINER_NAME' from 'rule_db_backup.sql'...\033[0m"

# Pipe backup to container's psql
cat rule_db_backup.sql | docker exec -i $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME

echo -e "\033[0;32mDatabase restored successfully!\033[0m"
