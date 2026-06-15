#!/usr/bin/env python3
"""Update scene_scripts in DB to match fixed script files, and rebuild state.json."""

import json
import os
import sys

import psycopg2

PROJECT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/Users/biubiu/Downloads/interactive_show_20260531_150148"
PROJECT_ID = "7d248558-0a57-40cb-aea2-3fe47e0f8ce9"

# Read DB URL
with open("/Users/biubiu/projects/interactive-show-producer/.env") as f:
    for line in f:
        if line.startswith("DATABASE_URL="):
            db_url = line.strip().split("=", 1)[1]
            break

scripts_dir = os.path.join(PROJECT_DIR, "scripts")

# 1. Update scripts in DB
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Get latest version
cur.execute("SELECT MAX(version) FROM dag_nodes WHERE project_id = %s", (PROJECT_ID,))
version = cur.fetchone()[0] or 1

updated = 0
for filename in sorted(os.listdir(scripts_dir)):
    if not filename.endswith(".txt"):
        continue
    ep_id = filename.replace(".txt", "")
    filepath = os.path.join(scripts_dir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        script_text = f.read()

    # Find the node_key matching this episode
    cur.execute(
        "SELECT node_key FROM dag_nodes WHERE project_id = %s AND version = %s AND node_key = %s",
        (PROJECT_ID, version, ep_id),
    )
    row = cur.fetchone()
    if not row:
        print(f"  Skip {ep_id}: no matching dag_node")
        continue

    # Update scene_scripts (column is 'content', version matches dag_nodes)
    cur.execute(
        """
        UPDATE scene_scripts
        SET content = %s
        WHERE project_id = %s AND node_key = %s AND version = %s
        """,
        (script_text, PROJECT_ID, ep_id, version),
    )
    if cur.rowcount > 0:
        updated += 1
        print(f"  Updated: {ep_id}")
    else:
        # Insert if not exists
        cur.execute(
            """
            INSERT INTO scene_scripts (id, project_id, node_key, version, content, status, created_at)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, 'done', NOW())
            """,
            (PROJECT_ID, ep_id, version, script_text),
        )
        updated += 1
        print(f"  Inserted: {ep_id}")

conn.commit()
print(f"\nUpdated {updated} scripts in DB")

# 2. Rebuild state.json with fixed scripts
state_path = os.path.join(PROJECT_DIR, "state.json")
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

# Update scripts in state.json
for filename in sorted(os.listdir(scripts_dir)):
    if not filename.endswith(".txt"):
        continue
    ep_id = filename.replace(".txt", "")
    filepath = os.path.join(scripts_dir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        state["scripts"][ep_id] = f.read()

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print(f"Updated state.json")

cur.close()
conn.close()
