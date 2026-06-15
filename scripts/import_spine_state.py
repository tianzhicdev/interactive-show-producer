#!/usr/bin/env python3
"""Import a spine-format state.json (from interactive-play-writer) into the webapp database.

Maps:
  - bible → story_summaries + world_settings + characters
  - spine nodes → dag_nodes (with BFS-computed positions)
  - spine edges → dag_edges
  - node summaries + beats → scene_scripts (status='pending')

Positions: BFS depth → position_x (DB), branch spread → position_y (DB).
Webapp coordinate swap: DB position_x → visual Y, DB position_y → visual X.

Usage:
    python import_spine_state.py <state.json> [--env <.env path>]
"""

import json
import os
import re
import sys
import uuid
from collections import deque
from pathlib import Path
from typing import Any, List, Optional

import psycopg2
from psycopg2.extras import Json

# Add the data model to path for state computation
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "interactive-play-writer", "lib"))
from data_model import Spine, Registry, Node, Edge, Predicate, Effect, RegistryVar, state_at
from dfs_expander import compute_possible_states


def load_env(env_path: str) -> str:
    """Load DATABASE_URL from .env file."""
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1]
    raise ValueError("DATABASE_URL not found in .env")


def compute_bfs_positions(spine: dict) -> dict:
    """Compute node positions using BFS depth + branch spread.

    DB position_x → visual Y (depth/row), DB position_y → visual X (column).
    """
    nodes = {n["id"]: n for n in spine.get("nodes", [])}
    edges = spine.get("edges", [])
    entry = spine.get("entry_node", "")

    # Build adjacency
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e["src"], []).append(e["dst"])

    # BFS to compute depth
    depth: dict[str, int] = {}
    queue = deque([(entry, 0)])
    while queue:
        nid, d = queue.popleft()
        if nid in depth:
            continue
        depth[nid] = d
        for neighbor in adj.get(nid, []):
            if neighbor not in depth:
                queue.append((neighbor, d + 1))

    # Group by depth for spread computation
    by_depth: dict[int, list[str]] = {}
    for nid, d in depth.items():
        by_depth.setdefault(d, []).append(nid)

    # Sort within each depth level for deterministic ordering
    for d in by_depth:
        by_depth[d].sort()

    positions = {}
    spacing_x = 200  # vertical spacing (depth)
    spacing_y = 250  # horizontal spacing (spread)

    for d, nids in by_depth.items():
        width = len(nids)
        for i, nid in enumerate(nids):
            # Center the nodes at each depth level
            y_offset = (i - (width - 1) / 2) * spacing_y
            # DB position_x = depth (maps to visual Y)
            # DB position_y = spread (maps to visual X)
            positions[nid] = (d * spacing_x, y_offset)

    # Handle any nodes not reached by BFS
    max_depth = max(depth.values()) if depth else 0
    orphan_idx = 0
    for n in spine.get("nodes", []):
        if n["id"] not in positions:
            positions[n["id"]] = ((max_depth + 1) * spacing_x, orphan_idx * spacing_y)
            orphan_idx += 1

    return positions


def extract_episode_number(node_id: str) -> int:
    """Extract numeric episode number from node ID."""
    m = re.search(r"(\d+)", node_id)
    if m:
        return int(m.group(1))
    return 99


def node_to_scene_type(node: dict) -> str:
    """Map spine node kind → webapp scene_type."""
    kind = node.get("kind", "scene")
    node_id = node.get("id", "")

    if kind == "ending":
        return "ending"
    if node_id.startswith("DE"):
        return "hidden_ending"
    # Nodes with outgoing edges that fork are 'choice' type
    # (determined during import based on edge count)
    return "choice"  # default; overridden below for leaf nodes


def build_placeholder_script(node: dict, out_edges: Optional[List[dict]] = None) -> str:
    """Build placeholder script content showing three-part brief.

    Parts: entry state, story skeleton (summary + beats), player choices.
    """
    parts = []
    nid = node.get("id", "Unknown")
    title = node.get("title", "")
    summary = node.get("summary", "")
    beats = node.get("beats", [])
    requires = node.get("requires", [])
    choice_question = node.get("choice_question", "")

    parts.append(f"# {nid}: {title}" if title else f"# {nid}")

    # Part 1: Entry state
    if requires:
        parts.append("\n## 入场状态")
        for req in requires:
            parts.append(f"- {req.get('key', '?')} {req.get('cmp', 'eq')} {req.get('value', '?')}")

    # Part 2: Story skeleton
    if summary:
        parts.append(f"\n## 剧情骨架\n{summary}")
    if beats:
        parts.append("\n### 节拍")
        for i, beat in enumerate(beats, 1):
            parts.append(f"{i}. {beat}")

    # Part 3: Player choices
    if out_edges:
        parts.append("\n## 玩家选择")
        if choice_question:
            parts.append(f"问题：{choice_question}")
        for edge in out_edges:
            label = edge.get("label", "?")
            dst = edge.get("dst", "?")
            effects = edge.get("effects", [])
            if effects:
                eff_strs = [f"{e.get('key', '?')}={e.get('value', '?')}" for e in effects]
                parts.append(f"- {label} → {dst} [{', '.join(eff_strs)}]")
            else:
                parts.append(f"- {label} → {dst}")
            resolution = edge.get("resolution", [])
            if resolution:
                parts.append(f"  ▸ 选择结果:")
                for beat in resolution:
                    parts.append(f"    {beat}")

    return "\n".join(parts)


def reconstruct_spine_registry(spine_dict: dict, registry_dict: dict) -> tuple:
    """Reconstruct typed Spine and Registry objects from raw dicts."""
    reg_vars = [RegistryVar(**v) for v in registry_dict.get("vars", [])]
    registry_obj = Registry(vars=reg_vars)

    nodes = []
    for nd in spine_dict.get("nodes", []):
        nd = dict(nd)  # shallow copy to avoid mutating original
        requires = [Predicate(**p) for p in nd.pop("requires", [])]
        invariants = [Predicate(**p) for p in nd.pop("invariants", [])]
        nodes.append(Node(**nd, requires=requires, invariants=invariants))

    edges = []
    for ed in spine_dict.get("edges", []):
        ed = dict(ed)
        effects = [Effect(**e) for e in ed.pop("effects", [])]
        resolution = ed.pop("resolution", [])
        edges.append(Edge(**ed, effects=effects, resolution=resolution))

    spine_obj = Spine(
        nodes=nodes, edges=edges,
        entry_node=spine_dict.get("entry_node", ""),
    )
    return spine_obj, registry_obj


def import_spine_state(state_path: str, db_url: str) -> str:
    """Import spine-format state.json into the database. Returns project_id."""
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    bible = state.get("bible", {})
    registry = state.get("registry", {})
    spine = state.get("spine", {})
    metadata = state.get("metadata", {})

    # Reconstruct typed objects for state computation
    spine_obj, registry_obj = reconstruct_spine_registry(spine, registry)

    project_id = str(uuid.uuid4())
    project_name = bible.get("title", metadata.get("title", "Untitled"))
    steering_notes = metadata.get("note", "")

    nodes = spine.get("nodes", [])
    edges = spine.get("edges", [])
    entry_node = spine.get("entry_node", "")

    # Build out-degree map for scene_type determination
    out_degree: dict[str, int] = {}
    for e in edges:
        out_degree[e["src"]] = out_degree.get(e["src"], 0) + 1

    # Compute positions
    positions = compute_bfs_positions(spine)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # 0. Resolve user_id if --user was given
        user_id = None
        if "--user" in sys.argv:
            idx = sys.argv.index("--user")
            uname = sys.argv[idx + 1]
            cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (uname,))
            row = cur.fetchone()
            if row:
                user_id = row[0]
                print(f"Resolved user '{uname}' → {user_id}")
            else:
                print(f"Warning: user '{uname}' not found, project will have no owner")

        # 1. Create project
        cur.execute(
            """INSERT INTO projects (id, name, status, steering_notes, user_id)
               VALUES (%s, %s, 'done', %s, %s)""",
            (project_id, project_name, steering_notes, user_id),
        )
        print(f"Created project: {project_name} ({project_id})")

        # 2. Story summary (from bible) — full content for web app display
        summary_parts = []
        if bible.get("title"):
            summary_parts.append(f"# {bible['title']}")
        if bible.get("genre"):
            summary_parts.append(f"**题材**: {bible['genre']}")
        if bible.get("tone"):
            summary_parts.append(f"**基调**: {bible['tone']}")
        if bible.get("source_chapters"):
            summary_parts.append(f"**原著范围**: {bible['source_chapters']}")
        if bible.get("dramatic_question"):
            summary_parts.append(f"\n## 戏剧核心问题\n{bible['dramatic_question']}")

        # Protagonist section
        protag = bible.get("protagonist", {})
        if protag:
            summary_parts.append(f"\n## 主角：{protag.get('name', '未知')}")
            if protag.get("arc"):
                summary_parts.append(f"**角色弧光**: {protag['arc']}")
            if protag.get("starting_state"):
                summary_parts.append(f"**起始状态**: {protag['starting_state']}")
            if protag.get("core_conflict"):
                summary_parts.append(f"**核心冲突**: {protag['core_conflict']}")
            if protag.get("abilities"):
                summary_parts.append(f"**能力**: {protag['abilities']}")
            if protag.get("personality"):
                summary_parts.append(f"**性格**: {protag['personality']}")

        # Characters section
        chars = bible.get("characters", [])
        if chars:
            summary_parts.append(f"\n## 主要角色 ({len(chars)}位)")
            for c in chars:
                name = c.get("name", "?")
                role = c.get("role", "")
                rel = c.get("relationship", "")
                summary_parts.append(f"- **{name}** ({role}): {rel}")

        # Themes
        if bible.get("themes"):
            summary_parts.append(f"\n## 主题")
            for t in bible["themes"]:
                summary_parts.append(f"- {t}")

        # Canon facts
        if bible.get("canon_facts"):
            summary_parts.append(f"\n## 设定事实（不可违反）")
            for f in bible["canon_facts"]:
                summary_parts.append(f"- {f}")

        # World building
        world = bible.get("world", {})
        if world:
            summary_parts.append(f"\n## 世界观")
            for k, v in world.items():
                if isinstance(v, dict):
                    summary_parts.append(f"### {k}")
                    for sk, sv in v.items():
                        summary_parts.append(f"- **{sk}**: {sv}")
                elif isinstance(v, list):
                    summary_parts.append(f"### {k}")
                    for item in v:
                        summary_parts.append(f"- {item}")
                else:
                    summary_parts.append(f"- **{k}**: {v}")

        summary_content = "\n".join(summary_parts) if summary_parts else json.dumps(bible, ensure_ascii=False, indent=2)

        cur.execute(
            """INSERT INTO story_summaries (project_id, version, content, arc_breakdown)
               VALUES (%s, 1, %s, %s)""",
            (project_id, summary_content, Json(bible.get("themes", []))),
        )
        print("Inserted story summary")

        # 3. World settings
        setting_data = {}
        for key in ("world", "genre", "tone", "title", "source_chapters"):
            if key in bible and bible[key]:
                setting_data[key] = bible[key]
        # Include registry as part of world settings
        if registry.get("vars"):
            setting_data["registry"] = registry

        cur.execute(
            """INSERT INTO world_settings (project_id, version, setting_data)
               VALUES (%s, 1, %s)""",
            (project_id, Json(setting_data)),
        )
        print("Inserted world settings")

        # 4. Characters
        characters = bible.get("characters", [])
        protagonist = bible.get("protagonist", {})
        if protagonist and protagonist.get("name"):
            # Add protagonist as first character
            char_list = [protagonist] + characters
        else:
            char_list = characters

        for char in char_list:
            name = char.get("name", "Unknown")
            profile = {k: v for k, v in char.items() if k != "name"}
            cur.execute(
                """INSERT INTO characters (project_id, version, name, profile_data)
                   VALUES (%s, 1, %s, %s)""",
                (project_id, name, Json(profile)),
            )
        print(f"Inserted {len(char_list)} characters")

        # 5. DAG nodes (with state fields)
        print("Computing per-node possible states...")
        for node in nodes:
            nid = node["id"]
            kind = node.get("kind", "scene")

            # Determine scene_type
            if kind == "ending":
                scene_type = "ending"
            elif nid.startswith("DE"):
                scene_type = "hidden_ending"
            elif out_degree.get(nid, 0) > 1:
                scene_type = "choice"
            elif out_degree.get(nid, 0) == 1:
                scene_type = "normal"
            else:
                # Leaf node without explicit ending kind
                scene_type = "normal"

            is_ending = kind == "ending"
            is_hidden_ending = nid.startswith("DE")
            ep_num = extract_episode_number(nid)
            pos = positions.get(nid, (0, 0))

            # State fields
            node_requires = node.get("requires", None)
            node_invariants = node.get("invariants", None)

            # Compute possible states at this node across all paths
            computed_states = compute_possible_states(spine_obj, registry_obj, nid)

            cur.execute(
                """INSERT INTO dag_nodes
                   (project_id, version, node_key, title, summary, scene_type,
                    is_ending, is_hidden_ending, episode_number, episode_title,
                    position_x, position_y,
                    requires, invariants, computed_states)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    project_id, nid,
                    node.get("title", ""),
                    node.get("summary", ""),
                    scene_type, is_ending, is_hidden_ending,
                    ep_num, node.get("title", ""),
                    pos[0], pos[1],
                    Json(node_requires) if node_requires else None,
                    Json(node_invariants) if node_invariants else None,
                    Json(computed_states) if computed_states else None,
                ),
            )
        print(f"Inserted {len(nodes)} DAG nodes (with state fields)")

        # 6. DAG edges
        # Group edges by source for choice_index ordering
        edges_by_src: dict[str, list[dict]] = {}
        for edge in edges:
            edges_by_src.setdefault(edge["src"], []).append(edge)

        edge_count = 0
        for src, src_edges in edges_by_src.items():
            for idx, edge in enumerate(src_edges):
                label = edge.get("label", f"选择{idx + 1}")
                edge_effects = edge.get("effects", None)
                edge_resolution = edge.get("resolution", None)
                cur.execute(
                    """INSERT INTO dag_edges
                       (project_id, version, source_node_key, target_node_key,
                        choice_label, choice_index, effects, resolution)
                       VALUES (%s, 1, %s, %s, %s, %s, %s, %s)""",
                    (project_id, edge["src"], edge["dst"], label, idx,
                     Json(edge_effects) if edge_effects else None,
                     Json(edge_resolution) if edge_resolution else None),
                )
                edge_count += 1
        print(f"Inserted {edge_count} DAG edges (with effects)")

        # 7. Scene scripts (placeholders with three-part briefs)
        script_count = 0
        for node in nodes:
            node_out_edges = edges_by_src.get(node["id"], [])
            content = build_placeholder_script(node, node_out_edges)
            cur.execute(
                """INSERT INTO scene_scripts
                   (project_id, node_key, version, content, status)
                   VALUES (%s, %s, 1, %s, 'pending')""",
                (project_id, node["id"], content),
            )
            script_count += 1
        print(f"Inserted {script_count} scene scripts (status=pending)")

        conn.commit()
        print(f"\nImport complete! Project ID: {project_id}")
        return project_id

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_spine_state.py <state.json> [--env <.env path>]")
        sys.exit(1)

    state_path = sys.argv[1]
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")

    if "--env" in sys.argv:
        idx = sys.argv.index("--env")
        env_path = sys.argv[idx + 1]

    if not os.path.exists(state_path):
        print(f"Error: {state_path} not found")
        sys.exit(1)

    db_url = load_env(env_path)
    project_id = import_spine_state(state_path, db_url)
    print(f"\nProject URL: check your webapp for project {project_id}")
