# Rule Detection Database

Rule Detection Database is a localized, high-performance aggregator and search engine for security detection rules (Sigma, YARA, Elastic Security, and Microsoft Sentinel KQL). It selective-syncs rules via Git sparse-checkout, normalizes metadata, generates vector embeddings offline using local AI, and indexing them inside a **PostgreSQL (pgvector)** database.

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

*Note: The setup script automatically configures a `.env` file, initializes a python `.venv`, pulls the AI model in Ollama, and launches the PostgreSQL container.
- **If `rule_db_backup.sql` exists** in the root directory: The script automatically restores the database from it in a few seconds (skipping schema creation and rule ingestion).
- **If no backup exists**: The script automatically triggers `backend/ingest.py` to sync rules from repositories and generate vector embeddings on the fly.*

---

## 💾 Database Backup & Restore (Transferring Data)

Since generating embeddings offline for 9,000+ rules is computationally heavy, you can export the database with pre-computed embeddings from your current machine and restore it on a new machine instantly.

### 1. Exporting Backup from Current Machine
Run the backup script to dump the active database to `rule_db_backup.sql` in the project root:
* **Windows**: `.\backup_db.ps1`
* **Linux/macOS**: `chmod +x backup_db.sh && ./backup_db.sh`

### 2. Importing Backup to a New Machine
Simply copy the generated `rule_db_backup.sql` file into the root of the project on the new machine, then run the Quick Installation script (`setup.ps1` or `setup.sh`). The installation script will detect the file and restore it automatically!

Alternatively, you can manually restore at any time by running:
* **Windows**: `.\restore_db.ps1`
* **Linux/macOS**: `chmod +x restore_db.sh && ./restore_db.sh`

---

## ⚙️ How to Run the Application

Once installation completes successfully:

### 1. Start Web Server & UI Dashboard
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

## ⏰ Automated Rule Updates (OS Scheduler)

To keep threat detection rules up-to-date automatically, the installation scripts configure a daily background checker task in your operating system scheduler:
* **Windows**: Registers a task named `RuleDatabaseAutoUpdate` in **Windows Task Scheduler** to run `cron_sync.ps1` daily at 2:00 AM.
* **Linux/macOS**: Registers a cron job in **crontab** to run `cron_sync.sh` daily at 2:00 AM.

### How it works:
1. Every day at 2:00 AM, the scheduler runs the checker script.
2. The script checks the timestamp in `.last_sync` to see when the last successful rule ingestion occurred.
3. If less than 14 days have passed, the script exits immediately (zero compute overhead).
4. If 14 days or more have passed (or `.last_sync` is missing):
   - It automatically boots up the Docker daemon and Ollama service (if stopped).
   - It triggers the rule pulling and vector embedding generation pipeline (`backend/ingest.py`).
   - It writes a new ISO timestamp to `.last_sync`.
5. On Windows, the task is configured to **wake the computer** from sleep to perform the update, and to run as soon as possible if a scheduled run was missed because the machine was powered off.

---

## 🔍 Dashboard Search Modes

1. **Hybrid Search (Default)**: Leverages FTS keyword match (30% weight) and AI Semantic cosine similarity (70% weight) for the most relevant results.
2. **AI Semantic (RAG-Ready)**: Uses sentence embeddings to understand conceptual queries. E.g. *"detecting lsass memory dumping"* or *"registry run key persistence"*.
3. **Keyword Match (FTS)**: Native PostgreSQL FTS. Supports exact phrase double-quotes (e.g. `"lsass.exe"`), wildcards (e.g. `mimik*`), and boolean operators (e.g. `mimikatz AND process`).
4. **Raw Code Search**: Strict case-insensitive substring search matching raw code. E.g. searching for a binary string `"stdole2.tlb"` in YARA rules.
