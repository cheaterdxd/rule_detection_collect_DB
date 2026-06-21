#!/bin/bash

# Antigravity Shield - Rule Database Automated Setup Script for Linux/macOS
# Usage: chmod +x setup.sh && ./setup.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

write_header() {
    echo -e "\n${CYAN}=== $1 ===${NC}"
}

write_success() {
    echo -e "${GREEN}[+] $1${NC}"
}

write_warning() {
    echo -e "${YELLOW}[!] $1${NC}"
}

write_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# 1. Detect OS
write_header "Detecting OS Environment"
OS_TYPE="Unknown"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_TYPE=$ID
elif [ "$(uname)" = "Darwin" ]; then
    OS_TYPE="macos"
fi
write_success "Operating System detected: $OS_TYPE"

# Detect Package Manager
PKG_MANAGER=""
if [ "$OS_TYPE" = "ubuntu" ] || [ "$OS_TYPE" = "debian" ] || [ "$OS_TYPE" = "pop" ] || [ "$OS_TYPE" = "kali" ]; then
    PKG_MANAGER="apt"
elif [ "$OS_TYPE" = "centos" ] || [ "$OS_TYPE" = "rhel" ] || [ "$OS_TYPE" = "fedora" ]; then
    PKG_MANAGER="yum"
elif [ "$OS_TYPE" = "macos" ]; then
    PKG_MANAGER="brew"
fi

# 2. Check and Install Dependencies
write_header "Checking System Dependencies"

# Git
if ! command -v git &> /dev/null; then
    write_warning "Git is not installed. Installing..."
    if [ "$PKG_MANAGER" = "apt" ]; then
        sudo apt-get update && sudo apt-get install -y git
    elif [ "$PKG_MANAGER" = "yum" ]; then
        sudo yum install -y git
    elif [ "$PKG_MANAGER" = "brew" ]; then
        brew install git
    else
        write_error "Package manager not supported. Please install Git manually."
        exit 1
    fi
else
    write_success "Git is installed: $(git --version)"
fi

# Python3
if ! command -v python3 &> /dev/null; then
    write_warning "Python3 is not installed. Installing..."
    if [ "$PKG_MANAGER" = "apt" ]; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
    elif [ "$PKG_MANAGER" = "yum" ]; then
        sudo yum install -y python3 python3-pip
    elif [ "$PKG_MANAGER" = "brew" ]; then
        brew install python
    else
        write_error "Package manager not supported. Please install Python3 manually."
        exit 1
    fi
else
    write_success "Python3 is installed: $(python3 --version)"
fi

# Strict check for python3-venv package on Debian/Ubuntu systems
if [ "$PKG_MANAGER" = "apt" ]; then
    if ! python3 -c "import venv" &> /dev/null; then
        write_warning "python3-venv module is missing. Installing python3-venv..."
        sudo apt-get update && sudo apt-get install -y python3-venv
        write_success "python3-venv installed successfully."
    fi
fi

# Ollama
if ! command -v ollama &> /dev/null; then
    write_warning "Ollama is not installed. Installing via official script..."
    if [ "$PKG_MANAGER" = "brew" ]; then
        brew install ollama
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    write_success "Ollama installed successfully."
else
    write_success "Ollama is installed."
fi

# Docker
if ! command -v docker &> /dev/null; then
    write_warning "Docker is not installed. Installing via official Docker script..."
    if [ "$PKG_MANAGER" = "brew" ]; then
        brew install --cask docker
    else
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker $USER || true
    fi
    write_success "Docker installed successfully. Please start Docker service if it's not active."
else
    write_success "Docker is installed."
fi

# 3. Check and Start Services
write_header "Checking Services Status"

# Start Docker daemon if not active (Linux only)
if [ "$OS_TYPE" != "macos" ]; then
    if ! sudo systemctl is-active --quiet docker; then
        write_warning "Docker daemon is inactive. Starting Docker service..."
        sudo systemctl start docker
        write_success "Docker service started."
    fi
fi

# Verify Docker functionality
if ! docker info &> /dev/null; then
    write_warning "Unable to talk to Docker daemon without sudo. Running remaining docker commands with sudo fallback."
    SUDO_DOCKER="sudo"
else
    SUDO_DOCKER=""
fi

# Resolve Docker Compose command
DOCKER_COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif docker-compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    write_warning "Docker Compose is not installed. Installing docker-compose-v2..."
    if [ "$PKG_MANAGER" = "apt" ]; then
        sudo apt-get update && sudo apt-get install -y docker-compose-v2
        DOCKER_COMPOSE_CMD="docker compose"
    elif [ "$PKG_MANAGER" = "brew" ]; then
        brew install docker-compose
        DOCKER_COMPOSE_CMD="docker compose"
    else
        write_error "Docker Compose not found. Please install it manually."
        exit 1
    fi
fi
write_success "Using Docker Compose command: $DOCKER_COMPOSE_CMD"

# Start Ollama service if not active
ollama_running=false
if curl -s -m 2 http://localhost:11434/api/tags &> /dev/null; then
    ollama_running=true
    write_success "Ollama service is active."
fi

if [ "$ollama_running" = false ]; then
    write_warning "Ollama is not running. Starting Ollama service in background..."
    if systemctl list-unit-files | grep -q ollama &> /dev/null; then
        sudo systemctl start ollama
    else
        # Start inline background process bound to 0.0.0.0
        OLLAMA_HOST=0.0.0.0 ollama serve > /dev/null 2>&1 &
        sleep 4
    fi
    
    if curl -s -m 2 http://localhost:11434/api/tags &> /dev/null; then
        write_success "Ollama service started successfully."
    else
        write_warning "Ollama service launched, but did not respond. We will proceed anyway."
    fi
fi

# 4. Port Conflict Resolution
write_header "Scanning for Port Conflicts"

is_port_in_use() {
    local port=$1
    # Check via bash /dev/tcp
    (echo >/dev/tcp/127.0.0.1/$port) &>/dev/null && return 0
    # Fallback to ss
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$port " && return 0
    fi
    # Fallback to lsof
    if command -v lsof &>/dev/null; then
        lsof -i :$port &>/dev/null && return 0
    fi
    return 1
}

get_next_free_port() {
    local port=$1
    while true; do
        if ! is_port_in_use $port; then
            echo $port
            return 0
        fi
        port=$((port + 1))
    done
}

DEFAULT_DB_PORT=5432
DEFAULT_APP_PORT=8000

# DB Port Conflict check (skip if port is occupied by our own container postgres_vector)
db_port=$DEFAULT_DB_PORT
own_container_running=false
if $SUDO_DOCKER docker ps --filter "name=postgres_vector" --format "{{.Ports}}" 2>/dev/null | grep -q ":$DEFAULT_DB_PORT->"; then
    own_container_running=true
fi

if is_port_in_use $DEFAULT_DB_PORT && [ "$own_container_running" = false ]; then
    write_warning "Port $DEFAULT_DB_PORT is occupied by another service."
    db_port=$(get_next_free_port $((DEFAULT_DB_PORT + 1)))
    write_success "Allocated free port $db_port for PostgreSQL."
else
    write_success "Port $DEFAULT_DB_PORT is available (or occupied by our own container). Using port $db_port."
fi

# App Port Conflict check
app_port=$DEFAULT_APP_PORT
if is_port_in_use $DEFAULT_APP_PORT; then
    write_warning "Port $DEFAULT_APP_PORT is occupied by another service."
    app_port=$(get_next_free_port $((DEFAULT_APP_PORT + 1)))
    write_success "Allocated free port $app_port for Web Dashboard."
else
    write_success "Port $DEFAULT_APP_PORT is available. Using port $app_port."
fi

# 5. Generate .env file
write_header "Generating Configuration File (.env)"
cat << EOF > .env
# Auto-generated by setup.sh on $(date)
DB_PORT=$db_port
APP_PORT=$app_port
DB_HOST=localhost
DB_NAME=rule_db
DB_USER=postgres
DB_PASS=postgres
OLLAMA_MODEL=all-minilm
EOF
write_success "Configuration saved to [$(pwd)/.env]."

# 6. Configure Python3 Virtual Environment
write_header "Configuring Python3 Virtual Environment"
if [ ! -d ".venv" ]; then
    write_warning "Creating Python3 virtual environment in .venv..."
    python3 -m venv .venv
fi
write_success "Virtual environment directory ready."

write_warning "Upgrading pip and installing dependencies..."
.venv/bin/python3 -m pip install --upgrade pip --quiet
.venv/bin/python3 -m pip install -r requirements.txt --quiet
write_success "Python dependencies installed successfully."

# 7. Pull Ollama Embedding Model
write_header "Preparing AI Embedding Model"
if command -v ollama &> /dev/null; then
    write_warning "Pulling 'all-minilm' embedding model (this will skip if already downloaded)..."
    ollama pull all-minilm || write_warning "Ollama pull failed. Please pull the model manually using: ollama pull all-minilm"
    write_success "AI Embedding model is ready."
fi

# 8. Spin up PostgreSQL container & run migrations
write_header "Launching Infrastructure Containers"
write_warning "Starting PostgreSQL database container..."
$SUDO_DOCKER $DOCKER_COMPOSE_CMD down --remove-orphans >/dev/null 2>&1 || true
$SUDO_DOCKER $DOCKER_COMPOSE_CMD up -d
write_success "PostgreSQL pgvector container started."

write_warning "Waiting 6 seconds for PostgreSQL to initialize..."
sleep 6

write_warning "Running database migrations..."
# Inject port directly for the migration process
DB_PORT=$db_port DB_HOST=localhost DB_NAME=rule_db DB_USER=postgres DB_PASS=postgres .venv/bin/python3 backend/database.py
write_success "Database schema initialized successfully."

# Final Summary Instructions
write_header "Setup Completed Successfully!"
echo -e "${GREEN}The application has been configured with:${NC}"
echo -e "  - PostgreSQL Port: ${GREEN}$db_port${NC}"
echo -e "  - Web Dashboard Port: ${GREEN}$app_port${NC}"
echo -e "  - Ollama Model: ${GREEN}all-minilm${NC}"
echo ""
echo -e "${CYAN}=== HOW TO RUN THE APPLICATION ===${NC}"
echo -e "1. Ingest/Sync Threat Detection Rules (First-time only, takes a few minutes):"
echo -e "   ${YELLOW}.venv/bin/python3 backend/ingest.py${NC}"
echo ""
echo -e "2. Start the Web Dashboard server:"
echo -e "   ${YELLOW}.venv/bin/python3 backend/main.py${NC}"
echo -e "   Once started, open: ${GREEN}http://localhost:$app_port${NC}"
echo ""
echo -e "Enjoy your offline Detection-as-Code semantic database! - Antigravity Agent"
