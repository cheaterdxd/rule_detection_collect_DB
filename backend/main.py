import os
import json
import yaml
import requests
import subprocess
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

# pySigma converters
from sigma.collection import SigmaCollection
from sigma.backends.splunk import SplunkBackend
from sigma.backends.kusto import KustoBackend
from sigma.backends.elasticsearch import LuceneBackend

from database import get_db_connection

app = FastAPI(title="Cyber Security Detection Rule Database", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
print(f"FastAPI Ollama Service Target: http://{OLLAMA_HOST}:11434 (Model: {OLLAMA_MODEL})")

def get_ollama_embedding(text, model=OLLAMA_MODEL, host=OLLAMA_HOST):
    """Generates a 384-dimensional vector embedding using the local Ollama service on Windows."""
    url = f"http://{host}:11434/api/embeddings"
    payload = {
        "model": model,
        "prompt": text
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"[ERROR] Failed to query Ollama API at {url}")
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
            
            results = [{
                "id": r[0], "name": r[1], "type": r[2], "title": r[3],
                "description": r[4], "level": r[5], "author": r[6],
                "tags": r[7], "source_repo": r[8], "created_at": r[9], "score": float(r[10])
            } for r in cur.fetchall()]
            
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
                
            results = [{
                "id": r[0], "name": r[1], "type": r[2], "title": r[3],
                "description": r[4], "level": r[5], "author": r[6],
                "tags": r[7], "source_repo": r[8], "created_at": r[9], "score": float(r[10])
            } for r in cur.fetchall()]
            
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
            
            results = [{
                "id": r[0], "name": r[1], "type": r[2], "title": r[3],
                "description": r[4], "level": r[5], "author": r[6],
                "tags": r[7], "source_repo": r[8], "created_at": r[9], "score": float(r[10])
            } for r in cur.fetchall()]
            
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
            lex_results = {r[0]: {
                "id": r[0], "name": r[1], "type": r[2], "title": r[3],
                "description": r[4], "level": r[5], "author": r[6],
                "tags": r[7], "source_repo": r[8], "created_at": r[9], "lex_score": float(r[10])
            } for r in cur.fetchall()}
            
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
            sem_results = {r[0]: {
                "id": r[0], "name": r[1], "type": r[2], "title": r[3],
                "description": r[4], "level": r[5], "author": r[6],
                "tags": r[7], "source_repo": r[8], "created_at": r[9], "sem_score": float(r[10])
            } for r in cur.fetchall()}
            
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

@app.post("/api/rules/translate")
def translate_rule(req: TranslationRequest):
    """Translates a raw Sigma YAML rule to Splunk, Elastic, or Sentinel (KQL) formats."""
    try:
        rule = SigmaCollection.from_yaml(req.sigma_yaml)
        
        target = req.target.lower().strip()
        if target == "splunk":
            backend = SplunkBackend()
            converted = backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        elif target == "sentinel" or target == "kusto":
            backend = KustoBackend()
            converted = backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        elif target == "elastic" or target == "elasticsearch":
            backend = LuceneBackend()
            converted = backend.convert(rule)
            return {"query": converted[0] if converted else ""}
        else:
            raise HTTPException(status_code=400, detail=f"SIEM backend '{target}' is not supported.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SIEM Translation failed: {str(e)}")

# Serve Static files for UI
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    app_port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=app_port, reload=True)
