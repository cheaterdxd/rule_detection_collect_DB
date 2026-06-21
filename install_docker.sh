#!/bin/bash
echo "=== Updating apt-get ==="
apt-get update

echo "=== Installing dependencies ==="
apt-get install -y ca-certificates curl gnupg

echo "=== Setting up GPG keyrings ==="
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "=== Adding Docker repository ==="
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "=== Updating package index ==="
apt-get update

echo "=== Installing Docker Ce & Compose Plugin ==="
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== Starting Docker service ==="
service docker start

echo "=== Docker Installation Complete ==="
