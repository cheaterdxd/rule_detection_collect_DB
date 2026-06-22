import os
import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor
import ollama


def _load_env():
    """Loads environment variables from a local .env file if it exists."""
    for path in [".env", "backend/.env", "../.env"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'").strip()
                        if k not in os.environ:
                            os.environ[k] = v
            break


_load_env()


def _get_wsl_gateway_ip() -> str:
    """Returns the Windows host IP as seen from WSL2 via the default route."""
    try:
        result = subprocess.run(
            ["ip", "route"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for line in result.stdout.splitlines():
            if "default" in line:
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
    except Exception:
        pass
    return ""


def _candidate_hosts() -> list[str]:
    """
    Returns a priority-ordered list of Ollama host addresses to try.
    Handles the common case where OLLAMA_HOST=0.0.0.0 is set (bind address,
    not a routable destination).
    """
    raw = os.getenv("OLLAMA_HOST", "").strip().strip('"').strip("'")

    # Strip protocol if present
    for prefix in ("http://", "https://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]

    # If empty, wildcard, or localhost — use the standard fallback chain
    if not raw or raw.startswith("0.0.0.0"):
        candidates = ["127.0.0.1", "localhost"]
        gw = _get_wsl_gateway_ip()
        if gw:
            candidates.append(gw)
        return candidates

    # If a specific host:port was given, use it first then fall back
    base = raw.split(":")[0]
    return [base, "127.0.0.1", "localhost"]


def _build_host_url(addr: str) -> str:
    """Ensures the address has a port suffix for the Ollama SDK."""
    if ":" in addr:
        return f"http://{addr}"
    return f"http://{addr}:11434"


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "all-minilm")

# Resolved at startup — first reachable host wins
_OLLAMA_HOST_URL: str | None = None


def _resolve_ollama_host() -> str:
    """
    Tries each candidate address in order and returns the first one that
    responds to a lightweight /api/tags call via the official SDK.
    Raises RuntimeError if none succeed.
    """
    global _OLLAMA_HOST_URL
    if _OLLAMA_HOST_URL is not None:
        return _OLLAMA_HOST_URL

    candidates = _candidate_hosts()
    for addr in candidates:
        url = _build_host_url(addr)
        try:
            client = ollama.Client(host=url)
            client.list()  # lightweight ping — returns installed model list
            _OLLAMA_HOST_URL = url
            print(f"[Ollama] Connected at {url}")
            return url
        except Exception:
            pass

    tried = ", ".join(_build_host_url(a) for a in candidates)
    raise RuntimeError(
        f"\n[ERROR] Could not connect to Ollama at any of: {tried}\n"
        "Please ensure:\n"
        "  1. Ollama Desktop is running (or `ollama serve` is active).\n"
        "  2. The model is downloaded: ollama pull all-minilm\n"
        "  3. On Windows, OLLAMA_HOST should be set to 0.0.0.0 so WSL can reach it.\n"
    )


def get_ollama_embedding(text: str) -> list[float]:
    """
    Returns a 384-dimensional embedding vector using the official Ollama SDK.
    Automatically discovers the correct host via fallback chain.
    """
    truncated = text[:500] if text else ""
    host_url = _resolve_ollama_host()
    client = ollama.Client(host=host_url)
    response = client.embeddings(model=OLLAMA_MODEL, prompt=truncated)
    return response["embedding"]


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "rule_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

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

        cur.execute("CREATE INDEX IF NOT EXISTS rules_search_idx ON rules USING gin(search_vector);")
        cur.execute("CREATE INDEX IF NOT EXISTS rules_embedding_hnsw_idx ON rules USING hnsw (embedding vector_cosine_ops);")

        conn.commit()
        print("Database initialized successfully with FTS and HNSW Vector indexes.")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    init_db()
