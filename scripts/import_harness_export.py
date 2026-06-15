#!/usr/bin/env python3
"""Import harness/web_app_export.json into the web app database.

This is a deterministic importer: it persists the already-validated harness
package as-is and does not call any LLM pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json


def load_database_url(env_path: str) -> str:
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError(f"DATABASE_URL not found in {env_path}")


def validate_package(package: dict[str, Any]) -> None:
    required = {
        "format", "version", "project", "story_summary", "world_settings",
        "characters", "dag_nodes", "dag_edges", "scene_scripts",
    }
    missing = required - set(package)
    if missing:
        raise ValueError(f"Export missing required fields: {sorted(missing)}")
    if package["format"] != "harness_web_app_export":
        raise ValueError(f"Unsupported export format: {package['format']}")

    node_keys = set()
    for node in package["dag_nodes"]:
        for key in ("node_key", "title", "scene_type", "is_ending", "is_hidden_ending"):
            if key not in node:
                raise ValueError(f"DAG node missing {key}: {node}")
        if node["node_key"] in node_keys:
            raise ValueError(f"Duplicate node_key: {node['node_key']}")
        node_keys.add(node["node_key"])

    for edge in package["dag_edges"]:
        if edge.get("source_node_key") not in node_keys:
            raise ValueError(f"Edge source missing node: {edge}")
        if edge.get("target_node_key") not in node_keys:
            raise ValueError(f"Edge target missing node: {edge}")

    script_keys = {s.get("node_key") for s in package["scene_scripts"]}
    if script_keys != node_keys:
        raise ValueError("scene_scripts must contain exactly one script per DAG node")


def resolve_user_id(cur: Any, username: str | None) -> str | None:
    if not username:
        return None
    cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (username,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise ValueError(f"User not found: {username}")


def import_package(
    package_path: str,
    db_url: str,
    username: str | None = None,
    name_override: str | None = None,
) -> str:
    package = json.loads(Path(package_path).read_text(encoding="utf-8"))
    validate_package(package)

    project_id = str(uuid.uuid4())
    project = package["project"]
    project_name = name_override or project.get("name") or "Harness Interactive Story"
    status = project.get("status") or "done"

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    try:
        user_id = resolve_user_id(cur, username)
        cur.execute(
            """INSERT INTO projects (id, name, status, steering_notes, user_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (project_id, project_name, status, "Imported from harness web_app_export.json", user_id),
        )

        cur.execute(
            """INSERT INTO story_summaries (project_id, version, content, arc_breakdown)
               VALUES (%s, 1, %s, %s)""",
            (project_id, package["story_summary"], Json(None)),
        )

        cur.execute(
            """INSERT INTO world_settings (project_id, version, setting_data)
               VALUES (%s, 1, %s)""",
            (project_id, Json(package["world_settings"])),
        )

        for char in package["characters"]:
            cur.execute(
                """INSERT INTO characters (project_id, version, name, profile_data)
                   VALUES (%s, 1, %s, %s)""",
                (project_id, char["name"], Json(char["profile_data"])),
            )

        for node in package["dag_nodes"]:
            cur.execute(
                """INSERT INTO dag_nodes
                   (project_id, version, node_key, title, summary, scene_type,
                    is_ending, is_hidden_ending, episode_number, episode_title,
                    position_x, position_y, requires, invariants, computed_states)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    project_id,
                    node["node_key"],
                    node["title"],
                    node.get("summary"),
                    node.get("scene_type", "normal"),
                    bool(node.get("is_ending", False)),
                    bool(node.get("is_hidden_ending", False)),
                    node.get("episode_number"),
                    node.get("episode_title"),
                    node.get("position_x", 0),
                    node.get("position_y", 0),
                    Json(node.get("requires")) if node.get("requires") is not None else None,
                    Json(node.get("invariants")) if node.get("invariants") is not None else None,
                    Json(node.get("computed_states")) if node.get("computed_states") is not None else None,
                ),
            )

        for edge in package["dag_edges"]:
            cur.execute(
                """INSERT INTO dag_edges
                   (project_id, version, source_node_key, target_node_key,
                    choice_label, choice_index, effects, resolution)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s)""",
                (
                    project_id,
                    edge["source_node_key"],
                    edge["target_node_key"],
                    edge.get("choice_label"),
                    edge.get("choice_index", 0),
                    Json(edge.get("effects")) if edge.get("effects") is not None else None,
                    Json(edge.get("resolution")) if edge.get("resolution") is not None else None,
                ),
            )

        for script in package["scene_scripts"]:
            cur.execute(
                """INSERT INTO scene_scripts
                   (project_id, node_key, version, content, status)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    project_id,
                    script["node_key"],
                    script.get("version", 1),
                    script["content"],
                    script.get("status", "ready"),
                ),
            )

        conn.commit()
        return project_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import harness web_app_export.json")
    parser.add_argument("export", help="Path to web_app_export.json")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--user", default=None, help="Optional web app username owner")
    parser.add_argument("--name", default=None, help="Override imported project name")
    args = parser.parse_args()

    if not os.path.exists(args.export):
        print(f"Export not found: {args.export}", file=sys.stderr)
        sys.exit(1)
    db_url = load_database_url(args.env)
    project_id = import_package(args.export, db_url, args.user, args.name)
    print(f"Imported project_id={project_id}")


if __name__ == "__main__":
    main()
