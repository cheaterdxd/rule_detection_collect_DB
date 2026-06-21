#!/bin/bash
echo "=== Installing python3-venv and python3-pip inside WSL ==="
apt-get update
apt-get install -y python3-venv python3-pip

echo "=== Creating Linux Virtual Environment (.venv_linux) ==="
cd /mnt/d/Code/ruleDetectionPublicDatabase
python3 -m venv .venv_linux

echo "=== Upgrading pip inside WSL venv ==="
.venv_linux/bin/pip install --upgrade pip

echo "=== Installing requirements inside WSL venv ==="
.venv_linux/bin/pip install -r requirements.txt

echo "=== WSL Python Setup Complete ==="
