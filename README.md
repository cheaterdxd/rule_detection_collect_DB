# Antigravity Shield - Cyber Security Detection Rule Semantic Database

Antigravity Shield is a localized, high-performance aggregator and search engine for security detection rules (Sigma, YARA, Elastic Security, and Microsoft Sentinel KQL). It selective-syncs rules via Git sparse-checkout, normalizes metadata, generates vector embeddings offline using local AI, and indexing them inside a **PostgreSQL (pgvector)** database.

---

## 🌟 Key Features

* **Hybrid Search (Lexical + Semantic)**: Ranks rules by combining SQL full-text keyword scores and Ollama embedding cosine similarity.
* **Raw Code Search**: Fast substring matches (`ILIKE`) directly on raw rule contents.
* **On-the-Fly SIEM Translation**: Translate Sigma rules to Splunk SPL, Elastic Query, or Sentinel KQL on the fly using `pySigma`.
* **Zero Configuration Setup**: Auto-detects dependencies, boots databases, and dynamically resolves occupied port conflicts.

---

## 🚀 One-Click Quick Installation

We provide automated setup scripts that check for dependencies (Git, Python 3.11, Docker, Ollama), auto-expose Ollama to WSL (`0.0.0.0`), resolve local port conflicts, configure virtual environments, and boot up database containers.

### A. On Windows Host (PowerShell)
1. Open PowerShell as **Administrator** (required if installing missing tools).
2. Navigate to this project directory and run:
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   .\setup.ps1
   ```

### B. On Linux / macOS Host (Bash)
1. Open your Terminal.
2. Navigate to this project directory and run:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

*Note: The installation script will automatically generate a `.env` file mapping open ports on your host, configure a python `.venv`, pull the embedding model `all-minilm` in Ollama, start the Docker database container, and configure DB tables and indexes.*

---

## ⚙️ How to Run the Application

Once installation completes successfully:

### 1. Ingest & Index Rules (First-time only)
This script performs a Git sparse-checkout to download rules folder from major repos, parses them, generates vector embeddings via Ollama, and loads them into PostgreSQL:
* **Windows**:
  ```powershell
  .venv\Scripts\python.exe backend/ingest.py
  ```
* **Linux/WSL/macOS**:
  ```bash
  .venv/bin/python3 backend/ingest.py
  ```

### 2. Start Web Server & UI Dashboard
Launch the FastAPI backend server:
* **Windows**:
  ```powershell
  .venv\Scripts\python.exe backend/main.py
  ```
* **Linux/WSL/macOS**:
  ```bash
  .venv/bin/python3 backend/main.py
  ```
Open your browser and navigate to the address outputted by the server (default: **[http://localhost:8000](http://localhost:8000)**).

---

## 🛡️ Custom Configuration (`.env`)

You can customize ports and connection settings in the auto-generated `.env` file in the root directory:

```env
DB_PORT=5432          # Database port on host (automatically changed by setup script if occupied)
APP_PORT=8000         # FastAPI port on host (automatically changed by setup script if occupied)
DB_HOST=localhost     # Database host
DB_NAME=rule_db       # PostgreSQL database name
DB_USER=postgres      # PostgreSQL username
DB_PASS=postgres      # PostgreSQL password
OLLAMA_MODEL=all-minilm
# OLLAMA_HOST=localhost # Optional: Override Ollama service host IP
```

---

## 🔍 Dashboard Search Modes

1. **Hybrid Search (Default)**: Leverages FTS keyword match (30% weight) and AI Semantic cosine similarity (70% weight) for the most relevant results.
2. **AI Semantic (RAG-Ready)**: Uses sentence embeddings to understand conceptual queries. E.g. *"detecting lsass memory dumping"* or *"registry run key persistence"*.
3. **Keyword Match (FTS)**: Native PostgreSQL FTS. Supports exact phrase double-quotes (e.g. `"lsass.exe"`), wildcards (e.g. `mimik*`), and boolean operators (e.g. `mimikatz AND process`).
4. **Raw Code Search**: Strict case-insensitive substring search matching raw code. E.g. searching for a binary string `"stdole2.tlb"` in YARA rules.
