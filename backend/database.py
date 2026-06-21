import os
import psycopg2
import requests
import subprocess
from psycopg2.extras import RealDictCursor

def get_windows_host_ip():
    """Fetches the IP address of the Windows Host from inside WSL to connect to Windows services."""
    try:
        # Check default route in Linux to find the Hyper-V network gateway IP
        result = subprocess.run(
            ["ip", "route"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if "default" in line:
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
    except Exception as e:
        print(f"Could not determine Windows host IP from WSL: {e}")
    return "localhost"

# Resolve Ollama configuration
OLLAMA_HOST = os.getenv("OLLAMA_HOST") or get_windows_host_ip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "all-minilm")

def get_ollama_embedding(text, model=OLLAMA_MODEL, host=OLLAMA_HOST):
    """Generates a 384-dimensional vector embedding using the local Ollama service on Windows."""
    # Truncate prompt to 500 characters to prevent context window overflow (HTTP 500 errors) in Ollama
    truncated_text = text[:500] if text else ""
    url = f"http://{host}:11434/api/embeddings"
    payload = {
        "model": model,
        "prompt": truncated_text
    }
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"\n[ERROR] Failed to query Ollama API at {url}")
        print("Please ensure:")
        print("1. Ollama is running on your Windows machine.")
        print("2. You downloaded the model using: 'ollama pull all-minilm'")
        print("3. Ollama is configured to accept network connections by setting the environment variable")
        print("   OLLAMA_HOST=0.0.0.0 on Windows before launching Ollama Desktop.")
        raise e

def load_env():
    """Loads environment variables from a local .env file if it exists."""
    for path in [".env", "backend/.env", "../.env"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            k, v = parts
                            k = k.strip()
                            v = v.strip().strip('"').strip("'").strip()
                            if k not in os.environ:
                                os.environ[k] = v
            break

load_env()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "rule_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Enable pgvector extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # Create rules table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                level VARCHAR(50),
                author VARCHAR(255),
                detection_query TEXT,
                raw_content TEXT,
                tags JSONB,
                source_repo VARCHAR(255),
                normalized_text TEXT,
                embedding VECTOR(384),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create generated tsvector column for Full-Text Search
        # We do this conditionally in case it already exists
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_name='rules' AND column_name='search_vector'
                ) THEN
                    ALTER TABLE rules ADD COLUMN search_vector tsvector 
                    GENERATED ALWAYS AS (
                        to_tsvector('english', 
                            coalesce(title, '') || ' ' || 
                            coalesce(description, '') || ' ' || 
                            coalesce(normalized_text, '')
                        )
                    ) STORED;
                END IF;
            END
            $$;
        """)
        
        # Create GIN index for full-text search
        cur.execute("CREATE INDEX IF NOT EXISTS rules_search_idx ON rules USING gin(search_vector);")
        
        # Create HNSW index for pgvector (uses cosine distance)
        cur.execute("CREATE INDEX IF NOT EXISTS rules_embedding_hnsw_idx ON rules USING hnsw (embedding vector_cosine_ops);")
        
        conn.commit()
        print("Database initialized successfully with FTS and HNSW Vector indexes.")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    init_db()
