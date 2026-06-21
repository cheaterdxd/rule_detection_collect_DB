# Antigravity Shield - Detection Rule Database Walkthrough

This project is a localized threat detection rules aggregator. It downloads rules selectively via Git sparse-checkout, normalizes them, generates AI semantic embeddings, and stores them in PostgreSQL with FTS (Full-Text Search) and `pgvector` index.

---

## Technical Stack & Ports
- **Backend & Web Server**: FastAPI on port `8000` (forwarded automatically to Windows).
- **Database**: PostgreSQL with `pgvector` extension on port `5432`.
- **AI Embedding Factory**: Ollama service on Windows host (port `11434`), running model `all-minilm` locally on your GPU/CPU.

---

## 1. Initial Infrastructure Setup

Make sure your Docker engine is active in WSL2. If you need to spin up the database container manually, navigate to this project directory and run:

```bash
# Start PostgreSQL container in background
wsl -d Ubuntu-24.04 -u root bash -c "cd /mnt/d/Code/ruleDetectionPublicDatabase && docker compose up -d"
```

To configure Ollama on your Windows host to accept connections from the WSL2 container, run this inside Windows PowerShell:
```powershell
# 1. Quit the Ollama Desktop App from the Taskbar System Tray first.
# 2. Open PowerShell and configure host binding:
$env:OLLAMA_HOST="0.0.0.0"

# 3. Start Ollama service:
ollama serve

# 4. In another terminal, download the embedding model if you haven't:
ollama pull all-minilm
```

---

## 2. Syncing & Indexing Rules (Ingestion)

The rules aggregator fetches the official detection rules from:
1. **SigmaHQ** (`Sigma`)
2. **mdecrevoisier Advanced Rules** (`Sigma`)
3. **YARA Forge** (`Yara`)
4. **Elastic Security** (`Elastic`)
5. **Bert-JanP Microsoft Sentinel** (`KQL`)

To update rules via Git and re-index the database with new embeddings, run:
```bash
wsl -d Ubuntu-24.04 -u root bash -c "cd /mnt/d/Code/ruleDetectionPublicDatabase && .venv_linux/bin/python backend/ingest.py"
```
*Note: This script uses **Git Sparse-Checkout** to selectively download **only the rules** folder of each repo, keeping your workspace extremely lightweight and clean.*

---

## 3. Running the Web Application

To start the FastAPI server and launch the Web Dashboard:
```bash
wsl -d Ubuntu-24.04 -u root bash -c "cd /mnt/d/Code/ruleDetectionPublicDatabase && .venv_linux/bin/python backend/main.py"
```

Once running:
- Open your Windows web browser.
- Navigate to: **[http://localhost:8000](http://localhost:8000)**

---

## 4. Dashboard Search Features

The UI supports three powerful query mechanisms:

### A. Hybrid Search (Default - Recommended)
Combines **Lexical search** (FTS5 keyword score) and **Semantic search** (Ollama vector cosine similarity score) to rank rules. This gives the best of both worlds: high keyword accuracy and conceptual understanding.

### B. AI Semantic Search (RAG-Ready)
Generates vector embeddings for your query and matches the conceptual meaning. You can search using natural sentences, such as:
- *“detecting mimikatz command execution on domain controllers”*
- *“look for proxy modifications in registry”*
- *“CVE-2021-44228 log4j execution patterns”*

### C. Keyword Match (FTS)
Exact token search using PostgreSQL native `tsvector`. It supports:
- **Exact phrases** inside double quotes (e.g. `"lsass.exe"` or `"powershell -enc"`).
- **Boolean syntax** (e.g. `mimikatz AND process`).
- **Wildcard prefixes** (e.g. `mimik*`).

### D. SIEM Conversion (For Sigma Rules)
When inspecting a Sigma rule, click on the **Splunk SPL**, **Elastic Query**, or **Sentinel KQL** tabs inside the modal. The backend uses `pySigma` to translate the raw YAML rule into vendor-specific query dialects on the fly!
