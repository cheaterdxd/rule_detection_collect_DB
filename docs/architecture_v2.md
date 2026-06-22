# Architecture V2 — Lightweight Rule Detection Database

## Tổng quan

Version 2 loại bỏ hoàn toàn hai dependency nặng nhất:
- ❌ **Docker + PostgreSQL + pgvector** → ✅ **SQLite + sqlite-vec + FTS5**
- ❌ **Ollama service** → ✅ **fastembed** (ONNX, embedded trong Python process)

Kết quả: từ **~1.5 GB** → **~400 MB**, không cần cài thêm phần mềm nào ngoài Python.

---

## So sánh V1 vs V2

| | V1 (hiện tại) | V2 (mới) |
|---|---|---|
| Database | PostgreSQL 16 + pgvector (Docker) | SQLite 3 + sqlite-vec |
| Vector index | HNSW (pgvector) | ANN (sqlite-vec) |
| Full-text search | tsvector + GIN index | FTS5 (built-in SQLite) |
| Embeddings | Ollama service + all-minilm | fastembed + all-MiniLM-L6-v2 (ONNX) |
| Setup | Docker compose + Ollama config | `pip install` duy nhất |
| Backup | `pg_dump` → 68MB SQL | Copy 1 file `rule_db.db` |
| RAM background | ~300MB (Docker daemon) | ~0MB |
| Cần Docker? | Có | Không |
| Cần Ollama? | Có | Không |

---

## Cấu trúc thư mục `version2/`

```
version2/
├── backend/
│   ├── main.py              # FastAPI app (API không đổi, SQL dialect thay đổi)
│   ├── database.py          # SQLite + sqlite-vec + fastembed
│   ├── ingest.py            # Rule ingestion (logic không đổi)
│   ├── sources.json         # Config repos (copy từ v1)
│   └── static/              # Frontend (copy nguyên từ v1)
│       ├── index.html
│       ├── app.js
│       └── style.css
├── rules_repositories/      # Gitignored, clone tự động khi ingest
├── requirements.txt
├── setup.ps1
└── setup.sh
```

---

## Stack kỹ thuật chi tiết

### 1. Database: SQLite + sqlite-vec + FTS5

```python
import sqlite3
import sqlite_vec

conn = sqlite3.connect("rule_db.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)
```

**Schema:**
```sql
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
    tags TEXT,           -- JSON string (thay JSONB)
    source_repo TEXT,
    normalized_text TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- FTS5 virtual table (thay tsvector + GIN index)
CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
    id UNINDEXED,
    title,
    description,
    normalized_text,
    content='rules',
    content_rowid='rowid'
);

-- Vector table (thay embedding column + HNSW index)
CREATE VIRTUAL TABLE IF NOT EXISTS rule_embeddings USING vec0(
    rule_id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);
```

### 2. Embeddings: fastembed

```python
from fastembed import TextEmbedding

_embedding_model: TextEmbedding | None = None

def get_embedding_model() -> TextEmbedding:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model

def get_fastembed_embedding(text: str) -> list[float]:
    truncated = text[:500] if text else ""
    model = get_embedding_model()
    embeddings = list(model.embed([truncated]))
    return embeddings[0].tolist()
```

- First run: auto-download ONNX model ~46MB vào `~/.cache/fastembed`
- Output: list[float] 384 dimensions — **tương thích 100% với V1**

### 3. requirements.txt (V2)

```
fastapi>=0.100.0
uvicorn>=0.22.0
pyyaml>=6.0
tomli>=2.0.1
pysigma>=0.10.8
pysigma-backend-splunk>=1.0.2
pysigma-backend-kusto>=1.0.1
pysigma-backend-elasticsearch>=1.0.3
requests>=2.31.0
pydantic>=2.0.0
fastembed>=0.3.0
sqlite-vec>=0.1.0
```

**Loại bỏ:** `psycopg2-binary`, `ollama`

---

## API Contract — Không thay đổi

Toàn bộ API endpoint giữ nguyên interface — frontend không cần sửa.

| Endpoint | Status |
|---|---|
| `GET /api/stats` | Giữ nguyên |
| `GET /api/rules` | Giữ nguyên |
| `GET /api/rules/{id}` | Giữ nguyên |
| `POST /api/rules/{id}/tags` | Giữ nguyên |
| `POST /api/rules/translate` | Giữ nguyên |
| `GET /api/sources` | Giữ nguyên |
| `POST /api/sources` | Giữ nguyên |
| `DELETE /api/sources/{name}` | Giữ nguyên |
| `POST /api/sources/sync` | Giữ nguyên |
| `GET /api/sources/sync/status` | Giữ nguyên |

---

## Thay đổi SQL cần thiết

### Tags (JSONB → json_each)
```sql
-- V1 (PostgreSQL)
SELECT jsonb_array_elements_text(tags) as tag FROM rules ...

-- V2 (SQLite)
SELECT value as tag FROM rules, json_each(rules.tags) ...
```

### Full-text search (tsvector → FTS5)
```sql
-- V1
WHERE search_vector @@ websearch_to_tsquery('english', %s)

-- V2
WHERE rules_fts MATCH ?
```

### Vector search (pgvector → sqlite-vec)
```sql
-- V1
ORDER BY embedding <=> %s::vector

-- V2
SELECT rule_id, distance
FROM rule_embeddings
WHERE embedding MATCH ? AND k = 50
ORDER BY distance
```

### Parameter placeholder
```python
# V1: %s (psycopg2)
# V2: ?  (sqlite3)
```

---

## Kế hoạch thực hiện

| Bước | File | Mô tả |
|---|---|---|
| 1 | `version2/backend/database.py` | SQLite + sqlite-vec + fastembed |
| 2 | `version2/backend/ingest.py` | Thay psycopg2 → sqlite3, %s → ? |
| 3 | `version2/backend/main.py` | Thay SQL dialect |
| 4 | `version2/requirements.txt` | Bỏ psycopg2/ollama, thêm fastembed/sqlite-vec |
| 5 | `version2/setup.ps1` | Bỏ Docker, đơn giản hơn nhiều |
| 6 | `version2/backend/static/` | Copy nguyên từ v1 |
