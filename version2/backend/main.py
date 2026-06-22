import os
import json
import sqlite3
import subprocess
import sys
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from sigma.collection import SigmaCollection
from sigma.backends.splunk import SplunkBackend
from sigma.backends.kusto import KustoBackend
from sigma.backends.elasticsearch import LuceneBackend

from database import get_db_connection, get_fastembed_embedding, DB_PATH

app = FastAPI(title="Cyber Security Detection Rule Database", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# pySigma backends — initialized once at startup
splunk_backend = SplunkBackend()
kusto_backend = KustoBackend()
lucene_backend = LuceneBackend()


def _embed(text: str) -> list[float]:
    """Wraps get_fastembed_embedding and converts exceptions to HTTP 503."""
    try:
        return get_fastembed_embedding(text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Embedding service error: {e}")


def _row_to_dict(row, score_key="score"):
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "title": row["title"],
        "description": row["description"],
        "level": row["level"],
        "author": row["author"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "source_repo": row["source_repo"],
        "created_at": row["created_at"],
        score_key: float(row["score"]),
    }


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def get_stats():
    conn = get_db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        types = {r[0]: r[1] for r in conn.execute("SELECT type, COUNT(*) FROM rules GROUP BY type")}
        levels = {r[0]: r[1] for r in conn.execute("SELECT level, COUNT(*) FROM rules GROUP BY level")}
        top_tags = [
            {"tag": r[0], "count": r[1]}
            for r in conn.execute("""
                SELECT value as tag, COUNT(*) as count
                FROM rules, json_each(rules.tags)
                GROUP BY tag ORDER BY count DESC LIMIT 15
            """)
        ]
        sources = {r[0]: r[1] for r in conn.execute("SELECT source_repo, COUNT(*) FROM rules GROUP BY source_repo")}
        return {"total": total, "types": types, "levels": levels, "top_tags": top_tags, "sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/rules")
def search_rules(
    q: Optional[str] = Query(None),
    mode: str = Query("hybrid"),
    rule_type: Optional[List[str]] = Query(None, alias="type"),
    level: Optional[List[str]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_db_connection()
    try:
        # Build filter fragments
        filter_parts: list[str] = []
        filter_vals: list = []

        if rule_type:
            placeholders = ",".join("?" * len(rule_type))
            filter_parts.append(f"r.type IN ({placeholders})")
            filter_vals.extend(rule_type)

        if level:
            placeholders = ",".join("?" * len(level))
            filter_parts.append(f"LOWER(r.level) IN ({placeholders})")
            filter_vals.extend([l.lower() for l in level])

        where = ("AND " + " AND ".join(filter_parts)) if filter_parts else ""

        # ── RAW search (substring) ─────────────────────────────────────────
        if mode == "raw" and q:
            like = f"%{q}%"
            rows = conn.execute(f"""
                SELECT r.id, r.name, r.type, r.title, r.description, r.level, r.author,
                       r.tags, r.source_repo, r.created_at, 1.0 as score
                FROM rules r
                WHERE (r.raw_content LIKE ? OR r.title LIKE ? OR r.description LIKE ?)
                {where}
                ORDER BY r.created_at DESC LIMIT ? OFFSET ?
            """, [like, like, like] + filter_vals + [limit, offset]).fetchall()
            return [_row_to_dict(r) for r in rows]

        # ── LEXICAL search (FTS5) ──────────────────────────────────────────
        if mode == "lexical" or not q:
            if not q:
                rows = conn.execute(f"""
                    SELECT id, name, type, title, description, level, author,
                           tags, source_repo, created_at, 1.0 as score
                    FROM rules r
                    WHERE 1=1 {where}
                    ORDER BY created_at DESC LIMIT ? OFFSET ?
                """, filter_vals + [limit, offset]).fetchall()
            else:
                rows = conn.execute(f"""
                    SELECT r.id, r.name, r.type, r.title, r.description, r.level, r.author,
                           r.tags, r.source_repo, r.created_at, bm25(rules_fts) * -1 as score
                    FROM rules_fts
                    JOIN rules r ON r.id = rules_fts.id
                    WHERE rules_fts MATCH ? {where}
                    ORDER BY score DESC LIMIT ? OFFSET ?
                """, [q] + filter_vals + [limit, offset]).fetchall()
            return [_row_to_dict(r) for r in rows]

        # ── SEMANTIC search (sqlite-vec) ───────────────────────────────────
        if mode == "semantic":
            vec = _embed(q)
            k = max(limit + offset, 100)
            vec_rows = conn.execute("""
                SELECT rule_id, distance FROM rule_embeddings
                WHERE embedding MATCH ? AND k = ?
                ORDER BY distance
            """, [json.dumps(vec), k]).fetchall()

            if not vec_rows:
                return []

            id_order = {r["rule_id"]: i for i, r in enumerate(vec_rows)}
            distances = {r["rule_id"]: r["distance"] for r in vec_rows}
            id_list = [r["rule_id"] for r in vec_rows]
            placeholders = ",".join("?" * len(id_list))

            rows = conn.execute(f"""
                SELECT r.id, r.name, r.type, r.title, r.description, r.level, r.author,
                       r.tags, r.source_repo, r.created_at, 0.0 as score
                FROM rules r
                WHERE r.id IN ({placeholders}) {where}
            """, id_list + filter_vals).fetchall()

            result = []
            for r in rows:
                d = distances.get(r["id"], 1.0)
                d = r
                item = _row_to_dict(r)
                item["score"] = max(0.0, 1.0 - distances.get(r["id"], 1.0))
                result.append(item)
            result.sort(key=lambda x: id_order.get(x["id"], 9999))
            return result[offset: offset + limit]

        # ── HYBRID search (FTS5 + sqlite-vec fusion) ──────────────────────
        hybrid_limit = max(100, offset + limit)

        # Lexical candidates
        lex_rows = conn.execute(f"""
            SELECT r.id, r.name, r.type, r.title, r.description, r.level, r.author,
                   r.tags, r.source_repo, r.created_at, bm25(rules_fts) * -1 as score
            FROM rules_fts
            JOIN rules r ON r.id = rules_fts.id
            WHERE rules_fts MATCH ? {where}
            ORDER BY score DESC LIMIT ?
        """, [q] + filter_vals + [hybrid_limit]).fetchall()
        lex = {r["id"]: _row_to_dict(r, "lex_score") for r in lex_rows}

        # Semantic candidates
        vec = _embed(q)
        vec_rows = conn.execute("""
            SELECT rule_id, distance FROM rule_embeddings
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
        """, [json.dumps(vec), hybrid_limit]).fetchall()

        sem_ids = [r["rule_id"] for r in vec_rows]
        sem_distances = {r["rule_id"]: r["distance"] for r in vec_rows}

        sem = {}
        if sem_ids:
            placeholders = ",".join("?" * len(sem_ids))
            sem_rows = conn.execute(f"""
                SELECT r.id, r.name, r.type, r.title, r.description, r.level, r.author,
                       r.tags, r.source_repo, r.created_at, 0.0 as score
                FROM rules r WHERE r.id IN ({placeholders}) {where}
            """, sem_ids + filter_vals).fetchall()
            for r in sem_rows:
                item = _row_to_dict(r, "sem_score")
                item["sem_score"] = max(0.0, 1.0 - sem_distances.get(r["id"], 1.0))
                sem[r["id"]] = item

        # Normalize lexical scores and fuse
        max_lex = max((v["lex_score"] for v in lex.values()), default=1.0) or 1.0

        combined = {}
        for k in set(lex) | set(sem):
            base = lex.get(k) or sem.get(k)
            lex_score = lex[k]["lex_score"] / max_lex if k in lex else 0.0
            sem_score = sem[k]["sem_score"] if k in sem else 0.0
            combined[k] = {**base, "score": 0.3 * lex_score + 0.7 * sem_score}

        sorted_results = sorted(combined.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[offset: offset + limit]

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/rules/{rule_id}")
def get_rule_detail(rule_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute("""
            SELECT id, name, type, title, description, level, author,
                   detection_query, raw_content, tags, source_repo, created_at, updated_at
            FROM rules WHERE id = ?
        """, (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {
            "id": row["id"], "name": row["name"], "type": row["type"],
            "title": row["title"], "description": row["description"],
            "level": row["level"], "author": row["author"],
            "detection_query": row["detection_query"], "raw_content": row["raw_content"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "source_repo": row["source_repo"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class TranslationRequest(BaseModel):
    sigma_yaml: str
    target: str


@app.post("/api/rules/translate")
def translate_rule(req: TranslationRequest):
    try:
        rule = SigmaCollection.from_yaml(req.sigma_yaml)
        target = req.target.lower().strip()
        if target == "splunk":
            converted = splunk_backend.convert(rule)
        elif target in ("sentinel", "kusto"):
            converted = kusto_backend.convert(rule)
        elif target in ("elastic", "elasticsearch"):
            converted = lucene_backend.convert(rule)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported backend: {target}")
        return {"query": converted[0] if converted else ""}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Translation failed: {e}")


class UpdateTagsRequest(BaseModel):
    tags: List[str]


@app.post("/api/rules/{rule_id}/tags")
def update_rule_tags(rule_id: str, req: UpdateTagsRequest):
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT id FROM rules WHERE id = ?", (rule_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Rule not found")
        conn.execute(
            "UPDATE rules SET tags = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(req.tags), rule_id)
        )
        conn.commit()
        return {"status": "success", "tags": req.tags}
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


SOURCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")


@app.get("/api/sources")
def get_sources():
    if not os.path.exists(SOURCES_FILE):
        return []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


class AddSourceRequest(BaseModel):
    name: str
    type: str
    repo_url: str
    relative_rules_path: str
    target_extensions: List[str]


@app.post("/api/sources")
def add_source(req: AddSourceRequest):
    sources = []
    if os.path.exists(SOURCES_FILE):
        with open(SOURCES_FILE) as f:
            sources = json.load(f)
    for s in sources:
        if s["name"].strip().lower() == req.name.strip().lower():
            raise HTTPException(status_code=400, detail=f"Source '{req.name}' already exists.")
    sources.append({
        "name": req.name.strip(), "type": req.type.strip(),
        "repo_url": req.repo_url.strip(), "relative_rules_path": req.relative_rules_path.strip(),
        "target_extensions": [e.strip() for e in req.target_extensions if e.strip()]
    })
    with open(SOURCES_FILE, "w") as f:
        json.dump(sources, f, indent=2, ensure_ascii=False)
    return sources


@app.delete("/api/sources/{name}")
def delete_source(name: str):
    if not os.path.exists(SOURCES_FILE):
        raise HTTPException(status_code=404, detail="Sources file not found")
    with open(SOURCES_FILE) as f:
        sources = json.load(f)
    filtered = [s for s in sources if s["name"].strip().lower() != name.strip().lower()]
    if len(filtered) == len(sources):
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    with open(SOURCES_FILE, "w") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    return filtered


sync_status = {"status": "idle", "message": "No sync in progress"}


def _run_ingest_bg():
    global sync_status
    sync_status = {"status": "running", "message": "Starting rule synchronization..."}
    try:
        ingest_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest.py")
        process = subprocess.Popen(
            [sys.executable, ingest_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy()
        )
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            sync_status = {"status": "success", "message": "Synchronization completed successfully!"}
        else:
            sync_status = {"status": "error", "message": f"Sync failed: {(stderr or stdout).strip()}"}
    except Exception as e:
        sync_status = {"status": "error", "message": f"Unexpected error: {e}"}


@app.post("/api/sources/sync")
def start_sync(background_tasks: BackgroundTasks):
    global sync_status
    if sync_status["status"] == "running":
        return {"status": "already_running", "message": "Sync is already in progress."}
    background_tasks.add_task(_run_ingest_bg)
    return {"status": "started", "message": "Rule ingestion started in background."}


@app.get("/api/sources/sync/status")
def get_sync_status():
    return sync_status


static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    app_port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=app_port, reload=True)
