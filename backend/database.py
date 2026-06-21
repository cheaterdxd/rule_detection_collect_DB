import os
import psycopg2
from psycopg2.extras import RealDictCursor

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
