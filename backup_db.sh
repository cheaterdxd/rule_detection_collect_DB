#!/bin/bash

# Antigravity Shield - Database Backup Tool for Linux/macOS
# Usage: chmod +x backup_db.sh && ./backup_db.sh

set -e

# Default configuration
DB_USER="postgres"
DB_NAME="rule_db"
CONTAINER_NAME="postgres_vector"

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

echo -e "\033[0;33mBacking up database '$DB_NAME' from container '$CONTAINER_NAME'...\033[0m"

# Execute pg_dump and dump to file
docker exec -t $CONTAINER_NAME pg_dump -U $DB_USER -d $DB_NAME > rule_db_backup.sql

if [ -f rule_db_backup.sql ] && [ -s rule_db_backup.sql ]; then
    file_size=$(wc -c < "rule_db_backup.sql")
    echo -e "\033[0;32mDatabase backup completed successfully!\033[0m"
    echo -e "\033[0;32mBackup file saved to: $(pwd)/rule_db_backup.sql ($file_size bytes)\033[0m"
else
    echo -e "\033[0;31mError: Database backup file is empty or missing!\033[0m"
    exit 1
fi
