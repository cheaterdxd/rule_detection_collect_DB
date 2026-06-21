import os
import json
import subprocess
import sys
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

# pySigma converters
from sigma.collection import SigmaCollection
from sigma.backends.splunk import SplunkBackend
from sigma.backends.kusto import KustoBackend
from sigma.backends.elasticsearch import LuceneBackend

from database import get_db_connection, get_ollama_embedding as db_get_ollama_embedding, OLLAMA_HOST, OLLAMA_MODEL

app = FastAPI(title="Cyber Security Detection Rule Database", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(f"FastAPI Ollama Service Target: http://{OLLAMA_HOST}:11434 (Model: {OLLAMA_MODEL})")

def get_ollama_embedding(text):
    """Wraps database get_ollama_embedding and handles API status exceptions."""
    try:
        return db_get_ollama_embedding(text)
    except Exception as e:
        raise HTTPException(
            status_code=503, 
            detail="Local Ollama embedding service is unreachable. Ensure Ollama is running with OLLAMA_HOST=0.0.0.0 set."
        )

# Request Model for Sigma Translation
class TranslationRequest(BaseModel):
    sigma_yaml: str
    target: str # splunk, elastic, sentinel

@app.get("/api/stats")
def get_stats():
    """Returns database summary statistics."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Total rules
        cur.execute("SELECT COUNT(*) FROM rules;")
        total_rules = cur.fetchone()[0]
        
        # Breakdown by type
        cur.execute("SELECT type, COUNT(*) FROM rules GROUP BY type;")
        type_counts = {row[0]: row[1] for row in cur.fetchall()}
        
        # Breakdown by level
        cur.execute("SELECT level, COUNT(*) FROM rules GROUP BY level;")
        level_counts = {row[0]: row[1] for row in cur.fetchall()}
        
        # Top 15 tags
        cur.execute("""
            SELECT jsonb_array_elements_text(tags) as tag, COUNT(*) as count 
            FROM rules 
            GROUP BY tag 
            ORDER BY count DESC 
            LIMIT 15;
        """)
        top_tags = [{"tag": row[0], "count": row[1]} for row in cur.fetchall()]
        
        # Source Repositories
        cur.execute("SELECT source_repo, COUNT(*) FROM rules GROUP BY source_repo;")
        source_counts = {row[0]: row[1] for row in cur.fetchall()}
        
        return {
            "total": total_rules,
            "types": type_counts,
            "levels": level_counts,
            "top_tags": top_tags,
            "sources": source_counts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

def _row_to_dict(r, score_key="score"):
    """Maps a PostgreSQL query tuple result to a standardized rule dictionary."""
    return {
        "id": r[0],
        "name": r[1],
        "type": r[2],
        "title": r[3],
        "description": r[4],
        "level": r[5],
        "author": r[6],
        "tags": r[7],
        "source_repo": r[8],
        "created_at": r[9],
        score_key: float(r[10])
    }

@app.get("/api/rules")
def search_rules(
    q: Optional[str] = Query(None, description="Search keyword, exact phrase, or natural language query"),
    mode: str = Query("hybrid", description="Search mode: lexical, semantic, hybrid"),
    rule_type: Optional[List[str]] = Query(None, alias="type", description="Filter by types (Sigma, Yara, Elastic, KQL)"),
    level: Optional[List[str]] = Query(None, description="Filter by severity level (Critical, High, Medium, Low)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """Searches rules using Lexical, Semantic, or Hybrid engines with metadata filters."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Base filter building
        filter_clauses = []
        filter_params = []
        
        if rule_type:
            filter_clauses.append("type = ANY(%s)")
            filter_params.append(rule_type)
            
        if level:
            level_params = [l.lower() for l in level]
            filter_clauses.append("LOWER(level) = ANY(%s)")
            filter_params.append(level_params)
            
        filters_sql = " AND ".join(filter_clauses)
        if filters_sql:
            filters_sql = "WHERE " + filters_sql
            
        # 1. RAW CODE SEARCH (Substring ILIKE)
        if mode == "raw" and q:
            where_clause = "(raw_content ILIKE %s OR title ILIKE %s OR description ILIKE %s)"
            if filters_sql:
                where_clause = " AND " + where_clause
            else:
                where_clause = "WHERE " + where_clause
                
            query_sql = f"""
                SELECT id, name, type, title, description, level, author, tags, source_repo, created_at, 1.0 as score
                FROM rules
                {filters_sql} {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
            """
            cur.execute(query_sql, filter_params + [f"%{q}%", f"%{q}%", f"%{q}%", limit, offset])
            
            results = [_row_to_dict(r) for r in cur.fetchall()]
            return results
            
        # 2. LEXICAL SEARCH
        if mode == "lexical" or not q:
            if not q:
                # No query, just list latest
                query_sql = f"""
                    SELECT id, name, type, title, description, level, author, tags, source_repo, created_at, 1.0 as score
                    FROM rules
                    {filters_sql}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s;
                """
                cur.execute(query_sql, filter_params + [limit, offset])
            else:
                # Full Text Search via tsvector & websearch
                where_clause = "search_vector @@ websearch_to_tsquery('english', %s)"
                if filters_sql:
                    where_clause = " AND " + where_clause
                else:
                    where_clause = "WHERE " + where_clause
                    
                query_sql = f"""
                    SELECT id, name, type, title, description, level, author, tags, source_repo, created_at,
                           ts_rank_cd(search_vector, websearch_to_tsquery('english', %s)) as score
                    FROM rules
                    {filters_sql} {where_clause}
                    ORDER BY score DESC
                    LIMIT %s OFFSET %s;
                """
                cur.execute(query_sql, [q] + filter_params + [q, limit, offset])
                
            results = [_row_to_dict(r) for r in cur.fetchall()]
            return results
            
        # 3. SEMANTIC SEARCH
        elif mode == "semantic":
            query_vector = get_ollama_embedding(q)
            
            # Using cosine similarity: 1 - (embedding <=> query_vector)
            order_clause = "embedding <=> %s::vector"
            where_clause = ""
            if filters_sql:
                where_clause = filters_sql
                
            query_sql = f"""
                SELECT id, name, type, title, description, level, author, tags, source_repo, created_at,
                       1.0 - (embedding <=> %s::vector) as score
                FROM rules
                {where_clause}
                ORDER BY {order_clause}
                LIMIT %s OFFSET %s;
            """
            cur.execute(query_sql, [query_vector] + filter_params + [query_vector, limit, offset])
            
            results = [_row_to_dict(r) for r in cur.fetchall()]
            return results
            
        # 4. HYBRID SEARCH (Deduplicated fusion)
        else: # hybrid
            hybrid_limit = max(100, offset + limit)
            
            # Fetch candidates from Lexical
            lex_where = "search_vector @@ websearch_to_tsquery('english', %s)"
            if filters_sql:
                lex_where = " AND " + lex_where
            else:
                lex_where = "WHERE " + lex_where
                
            lex_sql = f"""
                SELECT id, name, type, title, description, level, author, tags, source_repo, created_at,
                       ts_rank_cd(search_vector, websearch_to_tsquery('english', %s)) as lex_score
                FROM rules
                {filters_sql} {lex_where}
                ORDER BY lex_score DESC
                LIMIT %s;
            """
            cur.execute(lex_sql, [q] + filter_params + [q, hybrid_limit])
            lex_results = {r[0]: _row_to_dict(r, "lex_score") for r in cur.fetchall()}
            
            # Fetch candidates from Semantic
            query_vector = get_ollama_embedding(q)
            sem_where = ""
            if filters_sql:
                sem_where = filters_sql
                
            sem_sql = f"""
                SELECT id, name, type, title, description, level, author, tags, source_repo, created_at,
                       1.0 - (embedding <=> %s::vector) as sem_score
                FROM rules
                {sem_where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            cur.execute(sem_sql, [query_vector] + filter_params + [query_vector, hybrid_limit])
            sem_results = {r[0]: _row_to_dict(r, "sem_score") for r in cur.fetchall()}
            
            # Normalize lexical scores to [0, 1] range to combine with cosine similarity
            max_lex = max([r["lex_score"] for r in lex_results.values()]) if lex_results else 1.0
            if max_lex == 0:
                max_lex = 1.0
                
            for k in lex_results:
                lex_results[k]["normalized_lex_score"] = lex_results[k]["lex_score"] / max_lex
                
            # Fuse results
            combined = {}
            all_keys = set(lex_results.keys()).union(set(sem_results.keys()))
            
            for k in all_keys:
                lex_part = lex_results.get(k, {})
                sem_part = sem_results.get(k, {})
                
                base = lex_part if lex_part else sem_part
                
                lex_score = lex_part.get("normalized_lex_score", 0.0)
                sem_score = sem_part.get("sem_score", 0.0)
                
                # Formula: weighted score. 0.3 Lexical + 0.7 Semantic
                hybrid_score = (0.3 * lex_score) + (0.7 * sem_score)
                
                combined[k] = {
                    "id": base["id"],
                    "name": base["name"],
                    "type": base["type"],
                    "title": base["title"],
                    "description": base["description"],
                    "level": base["level"],
                    "author": base["author"],
                    "tags": base["tags"],
                    "source_repo": base["source_repo"],
                    "created_at": base["created_at"],
                    "score": hybrid_score
                }
                
            sorted_results = sorted(combined.values(), key=lambda x: x["score"], reverse=True)
            return sorted_results[offset : offset + limit]
            
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@app.get("/api/rules/{rule_id}")
def get_rule_detail(rule_id: str):
    """Returns rule details, including its original source query and complete content."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, name, type, title, description, level, author, detection_query, raw_content, tags, source_repo, created_at, updated_at
            FROM rules
            WHERE id = %s;
        """, (rule_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
            
        return {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "title": row[3],
            "description": row[4],
            "level": row[5],
            "author": row[6],
            "detection_query": row[7],
            "raw_content": row[8],
            "tags": row[9],
            "source_repo": row[10],
            "created_at": row[11],
            "updated_at": row[12]
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

# Global pySigma backends initialized once to prevent request overhead
splunk_backend = SplunkBackend()
kusto_backend = KustoBackend()
lucene_backend = LuceneBackend()

@app.post("/api/rules/translate")
def translate_rule(req: TranslationRequest):
    """Translates a raw Sigma YAML rule to Splunk, Elastic, or Sentinel (KQL) formats."""
    try:
        rule = SigmaCollection.from_yaml(req.sigma_yaml)
        
        target = req.target.lower().strip()
        if target == "splunk":
            converted = splunk_backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        elif target == "sentinel" or target == "kusto":
            converted = kusto_backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        elif target == "elastic" or target == "elasticsearch":
            converted = lucene_backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        else:
            raise HTTPException(status_code=400, detail=f"SIEM backend '{target}' is not supported.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SIEM Translation failed: {str(e)}")

# --- Rule Tagging & Sources Config Extension ---

class UpdateTagsRequest(BaseModel):
    tags: List[str]

class AddSourceRequest(BaseModel):
    name: str
    type: str
    repo_url: str
    relative_rules_path: str
    target_extensions: List[str]

# Global sync status tracker
sync_status = {"status": "idle", "message": "No sync in progress"}

def run_ingest_process_bg():
    global sync_status
    sync_status = {"status": "running", "message": "Starting rule repository synchronization..."}
    try:
        python_exe = sys.executable
        ingest_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest.py")
        env = os.environ.copy()
        
        # Start ingest subprocess
        process = subprocess.Popen(
            [python_exe, ingest_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            sync_status = {"status": "success", "message": "Rule database synchronization completed successfully!"}
        else:
            error_msg = stderr.strip() if stderr else stdout.strip()
            sync_status = {"status": "error", "message": f"Sync failed: {error_msg}"}
            print(f"[ERROR] Sync process failed: {error_msg}")
    except Exception as e:
        sync_status = {"status": "error", "message": f"Unexpected error during sync: {str(e)}"}
        print(f"[ERROR] Sync exception: {str(e)}")

@app.post("/api/rules/{rule_id}/tags")
def update_rule_tags(rule_id: str, req: UpdateTagsRequest):
    """Updates the manual tags for a specific rule."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check if rule exists
        cur.execute("SELECT id FROM rules WHERE id = %s;", (rule_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Rule not found")
            
        # Update tags
        tags_json = json.dumps(req.tags)
        cur.execute("""
            UPDATE rules 
            SET tags = %s::jsonb, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (tags_json, rule_id))
        conn.commit()
        return {"status": "success", "tags": req.tags}
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

SOURCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")

@app.get("/api/sources")
def get_sources():
    """Returns the list of configured rule repositories."""
    try:
        if not os.path.exists(SOURCES_FILE):
            return []
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read sources: {str(e)}")

@app.post("/api/sources")
def add_source(req: AddSourceRequest):
    """Adds a new rule repository configuration."""
    try:
        sources = []
        if os.path.exists(SOURCES_FILE):
            with open(SOURCES_FILE, "r", encoding="utf-8") as f:
                sources = json.load(f)
                
        for s in sources:
            if s["name"].strip().lower() == req.name.strip().lower():
                raise HTTPException(status_code=400, detail=f"Source with name '{req.name}' already exists.")
                
        new_source = {
            "name": req.name.strip(),
            "type": req.type.strip(),
            "repo_url": req.repo_url.strip(),
            "relative_rules_path": req.relative_rules_path.strip(),
            "target_extensions": [ext.strip() for ext in req.target_extensions if ext.strip()]
        }
        sources.append(new_source)
        
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2, ensure_ascii=False)
            
        return sources
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to save source: {str(e)}")

@app.delete("/api/sources/{name}")
def delete_source(name: str):
    """Deletes a rule repository configuration by name."""
    try:
        if not os.path.exists(SOURCES_FILE):
            raise HTTPException(status_code=404, detail="Sources file not found")
            
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            sources = json.load(f)
            
        filtered_sources = [s for s in sources if s["name"].strip().lower() != name.strip().lower()]
        
        if len(filtered_sources) == len(sources):
            raise HTTPException(status_code=404, detail=f"Source with name '{name}' not found")
            
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_sources, f, indent=2, ensure_ascii=False)
            
        return filtered_sources
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to delete source: {str(e)}")

@app.post("/api/sources/sync")
def start_sync(background_tasks: BackgroundTasks):
    """Triggers the rule ingestion process in the background."""
    global sync_status
    if sync_status["status"] == "running":
        return {"status": "already_running", "message": "Sync is already in progress."}
        
    background_tasks.add_task(run_ingest_process_bg)
    return {"status": "started", "message": "Rule ingestion started in background."}

@app.get("/api/sources/sync/status")
def get_sync_status():
    """Returns current status of the background ingestion sync."""
    global sync_status
    return sync_status

# Serve Static files for UI
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    app_port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=app_port, reload=True)
