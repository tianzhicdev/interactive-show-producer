"""Upload web_app_export.json to the webapp database as the final pipeline step."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _load_db_url() -> str:
    """Load DATABASE_URL from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f".env not found at {env_path}")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise ValueError("DATABASE_URL not found in .env")


def upload_to_webapp(export_path: str, project_id: str | None = None,
                     status: str = "done") -> str:
    """Upload a web_app_export.json to the webapp DB. Returns project_id.

    With project_id given, REPLACES that project's rows transactionally —
    enables live re-uploads of intermediary pipeline state (status="running").
    """
    import psycopg2
    from psycopg2.extras import Json

    db_url = _load_db_url()

    with open(export_path, "r", encoding="utf-8") as f:
        package = json.load(f)

    project_name = package.get("project", {}).get("name", "Untitled")
    replacing = project_id is not None
    project_id = project_id or str(uuid.uuid4())

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # 0. Metadata column for per-node dramatic data (additive, idempotent)
        cur.execute("ALTER TABLE dag_nodes ADD COLUMN IF NOT EXISTS metadata jsonb")

        if replacing:
            for table in ("scene_scripts", "dag_edges", "dag_nodes",
                          "characters", "world_settings", "story_summaries"):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))

        # 1. Create project
        cur.execute(
            """INSERT INTO projects (id, name, status)
               VALUES (%s, %s, %s)""",
            (project_id, project_name, status),
        )

        # 2. Story summary
        summary = package.get("story_summary", "")
        cur.execute(
            """INSERT INTO story_summaries (project_id, version, content, arc_breakdown)
               VALUES (%s, 1, %s, %s)""",
            (project_id, summary, Json([])),
        )

        # 3. World settings
        world = package.get("world_settings", {})
        cur.execute(
            """INSERT INTO world_settings (project_id, version, setting_data)
               VALUES (%s, 1, %s)""",
            (project_id, Json(world)),
        )

        # 4. Characters
        for char in package.get("characters", []):
            cur.execute(
                """INSERT INTO characters (project_id, version, name, profile_data)
                   VALUES (%s, 1, %s, %s)""",
                (project_id, char["name"], Json(char.get("profile_data", {}))),
            )

        # 5. DAG nodes (incl. per-node dramatic metadata for the UI)
        for node in package.get("dag_nodes", []):
            cur.execute(
                """INSERT INTO dag_nodes
                   (project_id, version, node_key, title, summary, scene_type,
                    is_ending, is_hidden_ending, episode_number, episode_title,
                    position_x, position_y, metadata)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    project_id,
                    node["node_key"],
                    node.get("title", ""),
                    node.get("summary", ""),
                    node.get("scene_type", "normal"),
                    node.get("is_ending", False),
                    node.get("is_hidden_ending", False),
                    node.get("episode_number", 0),
                    node.get("episode_title", ""),
                    node.get("position_x", 0),
                    node.get("position_y", 0),
                    Json(node.get("metadata", {})),
                ),
            )

        # 6. DAG edges
        for edge in package.get("dag_edges", []):
            cur.execute(
                """INSERT INTO dag_edges
                   (project_id, version, source_node_key, target_node_key,
                    choice_label, choice_index)
                   VALUES (%s, 1, %s, %s, %s, %s)""",
                (
                    project_id,
                    edge["source_node_key"],
                    edge["target_node_key"],
                    edge.get("choice_label", ""),
                    edge.get("choice_index", 0),
                ),
            )

        # 7. Scene scripts
        for script in package.get("scene_scripts", []):
            cur.execute(
                """INSERT INTO scene_scripts
                   (project_id, node_key, version, content, status)
                   VALUES (%s, %s, 1, %s, %s)""",
                (
                    project_id,
                    script["node_key"],
                    script.get("content", ""),
                    script.get("status", "ready"),
                ),
            )

        conn.commit()
        log.info(f"Uploaded to webapp: {project_name} ({project_id})")
        return project_id

    except Exception as e:
        conn.rollback()
        log.error(f"Upload failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()
