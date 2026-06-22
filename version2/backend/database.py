import os
import json
import sqlite3
import sqlite_vec
from fastembed import TextEmbedding


def _load_env():
    """Loads environment variables from a local .env file if it exists."""
    for path in [".env", "version2/.env", "../.env"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
            break


_load_env()

DB_PATH = os.getenv("DB_PATH", "rule_db.db")
EMBEDDING_MODEL = os.getenv("OLLAMA_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Embedding — fastembed (ONNX, no external service required)
# ---------------------------------------------------------------------------

_embed_model: TextEmbedding | None = None


def _get_embed_model() -> TextEmbedding:
    global _embed_model
    if _embed_model is None:
        print(f"[fastembed] Loading model '{EMBEDDING_MODEL}' (first run downloads ~46 MB)...")
        _embed_model = TextEmbedding(EMBEDDING_MODEL)
        print("[fastembed] Model ready.")
    return _embed_model


def get_fastembed_embedding(text: str) -> list[float]:
    """Returns a 384-dim embedding vector using fastembed (ONNX, embedded in-process)."""
    truncated = text[:500] if text else ""
    model = _get_embed_model()
    return list(model.embed([truncated]))[0].tolist()


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def _load_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def get_db_connection() -> sqlite3.Connection:
    return _load_db(DB_PATH)


def init_db():
    conn = _load_db(DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                level TEXT,
                author TEXT,
                detection_query TEXT,
                raw_content TEXT,
                tags TEXT,
                source_repo TEXT,
                normalized_text TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
                id UNINDEXED,
                title,
                description,
                normalized_text,
                content='rules',
                content_rowid='rowid'
            );
        """)

        # vec0 virtual table must use execute (not executescript) because it's
        # loaded by an extension and executescript may not see it.
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS rule_embeddings USING vec0(
                rule_id TEXT PRIMARY KEY,
                embedding FLOAT[384]
            );
        """)

        # FTS sync triggers (keep FTS in sync with rules table)
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS rules_ai AFTER INSERT ON rules BEGIN
                INSERT INTO rules_fts(rowid, id, title, description, normalized_text)
                VALUES (new.rowid, new.id, new.title, new.description, new.normalized_text);
            END;

            CREATE TRIGGER IF NOT EXISTS rules_ad AFTER DELETE ON rules BEGIN
                INSERT INTO rules_fts(rules_fts, rowid, id, title, description, normalized_text)
                VALUES ('delete', old.rowid, old.id, old.title, old.description, old.normalized_text);
            END;

            CREATE TRIGGER IF NOT EXISTS rules_au AFTER UPDATE ON rules BEGIN
                INSERT INTO rules_fts(rules_fts, rowid, id, title, description, normalized_text)
                VALUES ('delete', old.rowid, old.id, old.title, old.description, old.normalized_text);
                INSERT INTO rules_fts(rowid, id, title, description, normalized_text)
                VALUES (new.rowid, new.id, new.title, new.description, new.normalized_text);
            END;
        """)

        conn.commit()
        print("Database initialized: SQLite + sqlite-vec + FTS5.")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
