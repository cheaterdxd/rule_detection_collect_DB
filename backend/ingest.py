import os
import re
import json
import uuid
import yaml
import tomli
import requests
import subprocess
from datetime import datetime
from database import get_db_connection, init_db

# Configure Cache Directory for rules repositories
REPOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules_repositories")
os.makedirs(REPOS_DIR, exist_ok=True)

def get_windows_host_ip():
    """Fetches the IP address of the Windows Host from inside WSL to connect to Windows services."""
    try:
        # Check default route in Linux to find the hyper-v network gateway IP
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
print(f"Ollama Service Target: http://{OLLAMA_HOST}:11434 (Model: {OLLAMA_MODEL})")

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

def run_git_command(args, cwd=None):
    """Helper to run a git command in a specific directory."""
    try:
        result = subprocess.run(
            args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {' '.join(args)} in {cwd}. Error: {e.stderr}")
        raise e

def sync_repository(source):
    """Clones or updates a repository using Git Sparse-Checkout to only pull target rules."""
    name = source["name"]
    repo_url = source["repo_url"]
    relative_path = source["relative_rules_path"]
    
    slug = name.lower().replace(" ", "_").replace("/", "_")
    target_dir = os.path.join(REPOS_DIR, slug)
    
    print(f"\n--- Syncing source: {name} ---")
    
    if not os.path.exists(os.path.join(target_dir, ".git")):
        print(f"Initializing repository at: {target_dir}")
        os.makedirs(target_dir, exist_ok=True)
        
        # 1. Initialize empty git repository
        run_git_command(["git", "init"], cwd=target_dir)
        
        # 2. Add remote origin
        run_git_command(["git", "remote", "add", "origin", repo_url], cwd=target_dir)
        
        # 3. Enable sparse checkout
        run_git_command(["git", "config", "core.sparseCheckout", "true"], cwd=target_dir)
        
        # 4. Set sparse-checkout paths
        sparse_file = os.path.join(target_dir, ".git", "info", "sparse-checkout")
        with open(sparse_file, "w", encoding="utf-8") as f:
            f.write(f"{relative_path}\n")
            f.write(f"{relative_path}/**/*\n")
        
        # 5. Fetch depth 1 from origin
        print("Fetching repository structure (depth 1)...")
        run_git_command(["git", "fetch", "--depth", "1", "origin"], cwd=target_dir)
        
        # 6. Checkout rules
        print("Checking out rules files...")
        run_git_command(["git", "checkout", "FETCH_HEAD"], cwd=target_dir)
    else:
        print(f"Repository already exists at {target_dir}. Pulling updates...")
        try:
            run_git_command(["git", "fetch", "--depth", "1", "origin"], cwd=target_dir)
            run_git_command(["git", "reset", "--hard", "FETCH_HEAD"], cwd=target_dir)
        except Exception as e:
            print(f"Failed to update via Git pull, recreating repository cache... Error: {e}")
            # Fallback: remove and re-clone if corrupted
            import shutil
            shutil.rmtree(target_dir)
            return sync_repository(source)
            
    print(f"Successfully synced: {name}")
    return os.path.join(target_dir, relative_path)

def parse_sigma(file_path, content):
    """Strictly parses a Sigma rule YAML structure."""
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None
        
        # Parse fields
        title = data.get("title", "Unnamed Sigma Rule").strip()
        description = data.get("description", "").strip()
        level = data.get("level", "medium").lower().strip()
        author = data.get("author", "Unknown").strip()
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags] if tags else []
        tags = [str(t).strip() for t in tags]
        
        # Extracted queries/detection block
        detection = data.get("detection", {})
        detection_query = yaml.dump(detection, default_flow_style=False)
        
        logsource = data.get("logsource", {})
        
        # Normalize
        normalized_text = (
            f"Rule Title: {title}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: Sigma\n"
            f"Log Sources: Product: {logsource.get('product', 'any')}, Service: {logsource.get('service', 'any')}, Category: {logsource.get('category', 'any')}\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Detects security events matching the logic:\n{detection_query}"
        )
        
        return {
            "name": os.path.basename(file_path),
            "title": title,
            "description": description,
            "level": level,
            "author": author,
            "detection_query": detection_query,
            "tags": tags,
            "normalized_text": normalized_text
        }
    except Exception as e:
        print(f"Error parsing Sigma rule {file_path}: {e}")
        return None

def parse_elastic(file_path, content):
    """Strictly parses an Elastic Security TOML rule structure."""
    try:
        data = tomli.loads(content)
        rule = data.get("rule", {})
        if not rule:
            return None
            
        title = rule.get("name", "Unnamed Elastic Rule").strip()
        description = rule.get("description", "").strip()
        level = rule.get("severity", "medium").lower().strip()
        
        author = rule.get("author", [])
        if isinstance(author, list):
            author = ", ".join(author)
        author = str(author).strip()
        
        tags = rule.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags] if tags else []
        tags = [str(t).strip() for t in tags]
        
        query = rule.get("query", "").strip()
        rule_type = rule.get("type", "query").strip()
        
        normalized_text = (
            f"Rule Title: {title}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: Elastic ({rule_type})\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Runs query matching logic: {query}"
        )
        
        return {
            "name": os.path.basename(file_path),
            "title": title,
            "description": description,
            "level": level,
            "author": author,
            "detection_query": query,
            "tags": tags,
            "normalized_text": normalized_text
        }
    except Exception as e:
        print(f"Error parsing Elastic rule {file_path}: {e}")
        return None

def parse_yara_file(file_path, content):
    """Strictly parses YARA file contents. A single file can contain multiple rule blocks."""
    rules_found = []
    
    # Locate all rule definitions (allowing tags and multiline definitions)
    # E.g. rule Agent_BTZ_Aug17 : tag1 tag2 {
    rule_starts = list(re.finditer(r'(?:global\s+)?rule\s+(\w+)\s*(?::\s*[\w\s]+)?\s*\{', content))
    
    for i, match in enumerate(rule_starts):
        rule_name = match.group(1)
        start_pos = match.start()
        
        # Determine the boundaries of this rule block
        end_pos = len(content)
        if i + 1 < len(rule_starts):
            end_pos = rule_starts[i+1].start()
            
        rule_block = content[start_pos:end_pos]
        
        # Extract meta block
        meta_match = re.search(r'meta\s*:\s*([\s\S]*?)(?:strings\s*:|condition\s*:|\})', rule_block)
        meta_data = {}
        if meta_match:
            meta_str = meta_match.group(1)
            for line in meta_str.splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    continue
                # Split by first "="
                parts = line.split("=", 1)
                k = parts[0].strip()
                v = parts[1].strip()
                # Strip quotes
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1].strip()
                meta_data[k] = v
                
        # Extract metadata fields safely
        description = str(meta_data.get("description", meta_data.get("desc", "") or f"YARA signature rule for {rule_name}")).strip()
        author = str(meta_data.get("author", "Unknown") or "Unknown").strip()
        level = str(meta_data.get("level", meta_data.get("severity", "medium")) or "medium").lower().strip()
        
        # Extract YARA tags from the rule definition line
        rule_line_match = re.search(r'rule\s+(\w+)\s*:\s*([\w\s]+)\s*\{', rule_block)
        tags = []
        if rule_line_match and rule_line_match.group(2):
            tags = [t.strip() for t in rule_line_match.group(2).split() if t.strip()]
        if "category" in meta_data:
            tags.append(meta_data["category"])
        if "id" in meta_data:
            tags.append(f"id:{meta_data['id']}")
        tags = list(set([t.strip() for t in tags if t.strip()]))
        
        # Extract strings block
        strings_match = re.search(r'strings\s*:\s*([\s\S]*?)(?:condition\s*:|\})', rule_block)
        strings_str = strings_match.group(1).strip() if strings_match else ""
        
        # Extract condition block
        condition_match = re.search(r'condition\s*:\s*([\s\S]*?)(?:\})', rule_block)
        condition_str = condition_match.group(1).strip() if condition_match else ""
        
        # Format clean raw block (up to closing brace)
        # Find matching closing brace to avoid trailing content from other rules
        brace_count = 0
        rule_clean_block = ""
        for char in rule_block:
            rule_clean_block += char
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    break
        
        detection_query = f"strings:\n{strings_str}\n\ncondition:\n{condition_str}"
        
        normalized_text = (
            f"Rule Title: {rule_name}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: YARA\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Scans for binary strings or patterns:\n{strings_str}\nunder conditions: {condition_str}"
        )
        
        rules_found.append({
            "name": rule_name,
            "title": rule_name,
            "description": description,
            "level": level,
            "author": author,
            "detection_query": detection_query,
            "tags": tags,
            "normalized_text": normalized_text,
            "raw_content": rule_clean_block if rule_clean_block else rule_block
        })
        
    return rules_found

def parse_kql(file_path, content):
    """Strictly parses Microsoft Sentinel/KQL YAML configuration files."""
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None
        
        # Check if it has sentinel rule properties
        query = data.get("query", "").strip()
        if not query:
            return None # Not a Sentinel rule file
            
        title = data.get("name", "Unnamed Sentinel Rule").strip()
        description = data.get("description", "").strip()
        level = data.get("severity", "medium").lower().strip()
        
        tactics = data.get("tactics", [])
        if not isinstance(tactics, list):
            tactics = [tactics] if tactics else []
        techniques = data.get("relevantTechniques", [])
        if not isinstance(techniques, list):
            techniques = [techniques] if techniques else []
            
        tags = [str(t).strip() for t in tactics + techniques]
        author = "Microsoft" # Default for official sentinel repo
        
        normalized_text = (
            f"Rule Title: {title}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: Microsoft Sentinel (KQL)\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Runs KQL query: {query}"
        )
        
        return {
            "name": os.path.basename(file_path),
            "title": title,
            "description": description,
            "level": level,
            "author": author,
            "detection_query": query,
            "tags": tags,
            "normalized_text": normalized_text
        }
    except Exception as e:
        print(f"Error parsing KQL rule {file_path}: {e}")
        return None

def process_and_load_rules():
    """Reads sources, syncs repos, parses rules, generates embeddings, and saves to database."""
    # 1. Initialize Database
    print("Initializing Database...")
    init_db()
    
    # 2. Read sources configuration
    sources_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")
    with open(sources_file, "r", encoding="utf-8") as f:
        sources = json.load(f)
        
    db_conn = get_db_connection()
    db_cursor = db_conn.cursor()
    
    # Pre-load existing rules to avoid redundant embedding API calls and database writes
    existing_rules = {}
    try:
        db_cursor.execute("SELECT id, normalized_text FROM rules")
        existing_rules = {row[0]: row[1] for row in db_cursor.fetchall()}
        print(f"Retrieved {len(existing_rules)} existing rules from database for caching.")
    except Exception as cache_err:
        print(f"Could not load existing rules cache (will proceed without cache): {cache_err}")
    
    total_inserted = 0
    
    # Pre-check Ollama service availability
    try:
        # Check if the connection to Ollama works
        test_embed = get_ollama_embedding("test query capability")
        print(f"Success: Connected to Ollama embedding API. Output vector length: {len(test_embed)}")
    except Exception:
        print("\n[CRITICAL ERROR] Cannot proceed because the Ollama service on Windows is unreachable.")
        print("Please check your windows command line / terminal:")
        print("1. Set environment variable: set OLLAMA_HOST=0.0.0.0 (cmd) or $env:OLLAMA_HOST='0.0.0.0' (PowerShell)")
        print("2. Run 'ollama serve' or restart your Ollama Desktop Application.")
        print("3. Pull the embedding model with: 'ollama pull all-minilm'\n")
        return
        
    for source in sources:
        # Sync Git folder
        try:
            rules_dir = sync_repository(source)
        except Exception as e:
            print(f"Skipping source {source['name']} due to sync error: {e}")
            continue
            
        rule_type = source["type"]
        extensions = source["target_extensions"]
        source_name = source["name"]
        
        print(f"Scanning parsed folder: {rules_dir} for extensions {extensions}...")
        
        # Traverse directory
        for root, _, files in os.walk(rules_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in extensions:
                    continue
                    
                file_path = os.path.join(root, file)
                
                # Load content
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f_in:
                        content = f_in.read()
                except Exception as e:
                    print(f"Failed to read file {file_path}: {e}")
                    continue
                
                # Parse depending on type
                parsed_rules = []
                if rule_type == "Sigma":
                    rule_data = parse_sigma(file_path, content)
                    if rule_data:
                        rule_data["raw_content"] = content
                        parsed_rules.append(rule_data)
                elif rule_type == "Elastic":
                    rule_data = parse_elastic(file_path, content)
                    if rule_data:
                        rule_data["raw_content"] = content
                        parsed_rules.append(rule_data)
                elif rule_type == "KQL":
                    rule_data = parse_kql(file_path, content)
                    if rule_data:
                        rule_data["raw_content"] = content
                        parsed_rules.append(rule_data)
                elif rule_type == "Yara":
                    parsed_rules = parse_yara_file(file_path, content)
                    
                # Index and Save into Database
                for rule in parsed_rules:
                    # Generate unique ID based on title and type
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{rule_type}:{rule['title']}"))
                    
                    # Skip embedding generation and DB write if rule is unchanged (normalize line endings for compatibility)
                    stored_text = existing_rules.get(rule_id, "")
                    normalized_curr = rule["normalized_text"].replace("\r\n", "\n").strip()
                    normalized_stored = stored_text.replace("\r\n", "\n").strip()
                    if rule_id in existing_rules and normalized_stored == normalized_curr:
                        continue
                    
                    print(f"Indexing Rule: [{rule_type}] {rule['title']}")
                    
                    # Generate embedding on normalized text (No Chunking)
                    try:
                        embedding = get_ollama_embedding(rule["normalized_text"])
                    except Exception as embed_err:
                        print(f"Failed to generate embedding for rule '{rule['title']}': {embed_err}")
                        continue
                    
                    # Insert to database
                    try:
                        db_cursor.execute("""
                            INSERT INTO rules (id, name, type, title, description, level, author, detection_query, raw_content, tags, source_repo, normalized_text, embedding, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                name = EXCLUDED.name,
                                title = EXCLUDED.title,
                                description = EXCLUDED.description,
                                level = EXCLUDED.level,
                                author = EXCLUDED.author,
                                detection_query = EXCLUDED.detection_query,
                                raw_content = EXCLUDED.raw_content,
                                tags = EXCLUDED.tags,
                                normalized_text = EXCLUDED.normalized_text,
                                embedding = EXCLUDED.embedding,
                                updated_at = EXCLUDED.updated_at;
                        """, (
                            rule_id,
                            rule["name"],
                            rule_type,
                            rule["title"],
                            rule["description"],
                            rule["level"],
                            rule["author"],
                            rule["detection_query"],
                            rule["raw_content"],
                            json.dumps(rule["tags"]),
                            source_name,
                            rule["normalized_text"],
                            embedding,
                            datetime.now()
                        ))
                        total_inserted += 1
                        
                        # Commit in batches of 100
                        if total_inserted % 100 == 0:
                            db_conn.commit()
                            print(f"Batch checkpoint: Inserted {total_inserted} rules...")
                    except Exception as db_err:
                        db_conn.rollback()
                        print(f"Failed to insert rule {rule['title']} into database: {db_err}")
                        
    db_conn.commit()
    db_cursor.close()
    db_conn.close()
    print(f"\n=== Ingestion Completed! Total successfully loaded rules: {total_inserted} ===")

if __name__ == "__main__":
    process_and_load_rules()
