import os
import re
import json
import uuid
import yaml
import tomli
import subprocess
from datetime import datetime
from database import get_db_connection, init_db, get_fastembed_embedding

REPOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules_repositories")
os.makedirs(REPOS_DIR, exist_ok=True)


def run_git_command(args, cwd=None):
    try:
        result = subprocess.run(
            args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {' '.join(args)} in {cwd}. Error: {e.stderr}")
        raise


def sync_repository(source):
    """Clones or updates a repository using Git Sparse-Checkout."""
    name = source["name"]
    repo_url = source["repo_url"]
    relative_path = source["relative_rules_path"]
    slug = name.lower().replace(" ", "_").replace("/", "_")
    target_dir = os.path.join(REPOS_DIR, slug)

    print(f"\n--- Syncing source: {name} ---")

    if not os.path.exists(os.path.join(target_dir, ".git")):
        os.makedirs(target_dir, exist_ok=True)
        run_git_command(["git", "init"], cwd=target_dir)
        run_git_command(["git", "remote", "add", "origin", repo_url], cwd=target_dir)
        run_git_command(["git", "config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse_file = os.path.join(target_dir, ".git", "info", "sparse-checkout")
        with open(sparse_file, "w", encoding="utf-8") as f:
            f.write(f"{relative_path}\n")
            f.write(f"{relative_path}/**/*\n")
        print("Fetching repository (depth 1)...")
        run_git_command(["git", "fetch", "--depth", "1", "origin"], cwd=target_dir)
        print("Checking out rules...")
        run_git_command(["git", "checkout", "FETCH_HEAD"], cwd=target_dir)
    else:
        print(f"Repository exists at {target_dir}. Pulling updates...")
        try:
            run_git_command(["git", "fetch", "--depth", "1", "origin"], cwd=target_dir)
            run_git_command(["git", "reset", "--hard", "FETCH_HEAD"], cwd=target_dir)
        except Exception as e:
            print(f"Git pull failed, re-cloning... Error: {e}")
            import shutil
            shutil.rmtree(target_dir)
            return sync_repository(source)

    print(f"Synced: {name}")
    return os.path.join(target_dir, relative_path)


def parse_sigma(file_path, content):
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None
        title = data.get("title", "Unnamed Sigma Rule").strip()
        description = data.get("description", "").strip()
        level = data.get("level", "medium").lower().strip()
        author = data.get("author", "Unknown").strip()
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags] if tags else []
        tags = [str(t).strip() for t in tags]
        detection = data.get("detection", {})
        detection_query = yaml.dump(detection, default_flow_style=False)
        logsource = data.get("logsource", {})
        normalized_text = (
            f"Rule Title: {title}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: Sigma\n"
            f"Log Sources: Product: {logsource.get('product', 'any')}, Service: {logsource.get('service', 'any')}, Category: {logsource.get('category', 'any')}\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Detects security events matching the logic:\n{detection_query}"
        )
        return {"name": os.path.basename(file_path), "title": title, "description": description,
                "level": level, "author": author, "detection_query": detection_query,
                "tags": tags, "normalized_text": normalized_text}
    except Exception as e:
        print(f"Error parsing Sigma rule {file_path}: {e}")
        return None


def parse_elastic(file_path, content):
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
        return {"name": os.path.basename(file_path), "title": title, "description": description,
                "level": level, "author": author, "detection_query": query,
                "tags": tags, "normalized_text": normalized_text}
    except Exception as e:
        print(f"Error parsing Elastic rule {file_path}: {e}")
        return None


def parse_yara_file(file_path, content):
    rules_found = []
    rule_starts = list(re.finditer(r'(?:global\s+)?rule\s+(\w+)\s*(?::\s*[\w\s]+)?\s*\{', content))
    for i, match in enumerate(rule_starts):
        rule_name = match.group(1)
        start_pos = match.start()
        end_pos = len(content) if i + 1 >= len(rule_starts) else rule_starts[i + 1].start()
        rule_block = content[start_pos:end_pos]

        meta_match = re.search(r'meta\s*:\s*([\s\S]*?)(?:strings\s*:|condition\s*:|\})', rule_block)
        meta_data = {}
        if meta_match:
            for line in meta_match.group(1).splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                meta_data[k.strip()] = v

        description = str(meta_data.get("description", meta_data.get("desc", f"YARA signature rule for {rule_name}"))).strip()
        author = str(meta_data.get("author", "Unknown")).strip()
        level = str(meta_data.get("level", meta_data.get("severity", "medium"))).lower().strip()

        rule_line_match = re.search(r'rule\s+(\w+)\s*:\s*([\w\s]+)\s*\{', rule_block)
        tags = []
        if rule_line_match and rule_line_match.group(2):
            tags = [t.strip() for t in rule_line_match.group(2).split() if t.strip()]
        if "category" in meta_data:
            tags.append(meta_data["category"])
        tags = list(set([t.strip() for t in tags if t.strip()]))

        strings_match = re.search(r'strings\s*:\s*([\s\S]*?)(?:condition\s*:|\})', rule_block)
        strings_str = strings_match.group(1).strip() if strings_match else ""
        condition_match = re.search(r'condition\s*:\s*([\s\S]*?)(?:\})', rule_block)
        condition_str = condition_match.group(1).strip() if condition_match else ""

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

        normalized_text = (
            f"Rule Title: {rule_name}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: YARA\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Scans for binary strings or patterns:\n{strings_str}\nunder conditions: {condition_str}"
        )
        rules_found.append({
            "name": rule_name, "title": rule_name, "description": description,
            "level": level, "author": author, "detection_query": f"strings:\n{strings_str}\n\ncondition:\n{condition_str}",
            "tags": tags, "normalized_text": normalized_text, "raw_content": rule_clean_block or rule_block
        })
    return rules_found


def parse_kql(file_path, content):
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None
        query = data.get("query", "").strip()
        if not query:
            return None
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
        normalized_text = (
            f"Rule Title: {title}\n"
            f"Description: {description}\n"
            f"Severity Level: {level}\n"
            f"Rule Type: Microsoft Sentinel (KQL)\n"
            f"Threat Tags: {', '.join(tags)}\n"
            f"Detection Behavior: Runs KQL query: {query}"
        )
        return {"name": os.path.basename(file_path), "title": title, "description": description,
                "level": level, "author": "Microsoft", "detection_query": query,
                "tags": tags, "normalized_text": normalized_text}
    except Exception as e:
        print(f"Error parsing KQL rule {file_path}: {e}")
        return None


def process_and_load_rules():
    print("Initializing Database...")
    init_db()

    sources_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")
    with open(sources_file, "r", encoding="utf-8") as f:
        sources = json.load(f)

    conn = get_db_connection()

    # Pre-load existing rules to avoid redundant embedding calls
    existing_rules = {}
    try:
        existing_rules = {row["id"]: row["normalized_text"] for row in conn.execute("SELECT id, normalized_text FROM rules")}
        print(f"Cached {len(existing_rules)} existing rules.")
    except Exception as e:
        print(f"Could not load cache: {e}")

    # Pre-check embedding model (triggers download on first run)
    try:
        test = get_fastembed_embedding("connectivity test")
        print(f"Embedding model ready. Output dimensions: {len(test)}")
    except Exception as e:
        print(f"[CRITICAL] Cannot generate embeddings: {e}")
        conn.close()
        return

    total_inserted = 0

    for source in sources:
        try:
            rules_dir = sync_repository(source)
        except Exception as e:
            print(f"Skipping source {source['name']} due to sync error: {e}")
            continue

        rule_type = source["type"]
        extensions = source["target_extensions"]
        source_name = source["name"]

        print(f"Scanning {rules_dir} for {extensions}...")

        for root, _, files in os.walk(rules_dir):
            for file in files:
                if os.path.splitext(file)[1].lower() not in extensions:
                    continue

                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f_in:
                        content = f_in.read()
                except Exception as e:
                    print(f"Failed to read {file_path}: {e}")
                    continue

                parsed_rules = []
                if rule_type == "Sigma":
                    r = parse_sigma(file_path, content)
                    if r:
                        r["raw_content"] = content
                        parsed_rules.append(r)
                elif rule_type == "Elastic":
                    r = parse_elastic(file_path, content)
                    if r:
                        r["raw_content"] = content
                        parsed_rules.append(r)
                elif rule_type == "KQL":
                    r = parse_kql(file_path, content)
                    if r:
                        r["raw_content"] = content
                        parsed_rules.append(r)
                elif rule_type == "Yara":
                    parsed_rules = parse_yara_file(file_path, content)

                for rule in parsed_rules:
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{rule_type}:{rule['title']}"))

                    # Skip unchanged rules
                    curr = rule["normalized_text"].replace("\r\n", "\n").strip()
                    stored = existing_rules.get(rule_id, "").replace("\r\n", "\n").strip()
                    if rule_id in existing_rules and stored == curr:
                        continue

                    print(f"Indexing: [{rule_type}] {rule['title']}")

                    try:
                        embedding = get_fastembed_embedding(rule["normalized_text"])
                    except Exception as e:
                        print(f"Embedding failed for '{rule['title']}': {e}")
                        continue

                    try:
                        now = datetime.now().isoformat()
                        conn.execute("""
                            INSERT INTO rules (id, name, type, title, description, level, author,
                                detection_query, raw_content, tags, source_repo, normalized_text, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                name=excluded.name, title=excluded.title,
                                description=excluded.description, level=excluded.level,
                                author=excluded.author, detection_query=excluded.detection_query,
                                raw_content=excluded.raw_content, tags=excluded.tags,
                                normalized_text=excluded.normalized_text, updated_at=excluded.updated_at
                        """, (
                            rule_id, rule["name"], rule_type, rule["title"],
                            rule["description"], rule["level"], rule["author"],
                            rule["detection_query"], rule.get("raw_content", ""),
                            json.dumps(rule["tags"]), source_name,
                            rule["normalized_text"], now
                        ))

                        # Upsert into vector table separately
                        conn.execute("""
                            INSERT OR REPLACE INTO rule_embeddings(rule_id, embedding)
                            VALUES (?, ?)
                        """, (rule_id, json.dumps(embedding)))

                        total_inserted += 1

                        if total_inserted % 100 == 0:
                            conn.commit()
                            print(f"Checkpoint: {total_inserted} rules indexed...")

                    except Exception as e:
                        conn.rollback()
                        print(f"DB insert failed for '{rule['title']}': {e}")

    conn.commit()
    conn.close()
    print(f"\n=== Ingestion complete! Total rules indexed: {total_inserted} ===")

    try:
        last_sync_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".last_sync")
        with open(last_sync_path, "w", encoding="utf-8") as f:
            f.write(datetime.utcnow().isoformat())
    except Exception as e:
        print(f"[WARNING] Could not write .last_sync: {e}")


if __name__ == "__main__":
    process_and_load_rules()
