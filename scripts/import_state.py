#!/usr/bin/env python3
"""Import a state.json project into the webapp database."""

import json
import os
import sys
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import Json


def load_env(env_path: str) -> str:
    """Load DATABASE_URL from .env file."""
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1]
    raise ValueError("DATABASE_URL not found in .env")


def import_project(state_path: str, db_url: str) -> str:
    """Import state.json into the database. Returns project_id.

    Supports both old format (story_bible/structure) and new format (bible/spine).
    Checks validation gate: step-3 validation_report must not be FAIL.
    """
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    # Validation gate: check that step-3 validation passed
    validation_reports = state.get("validation_reports", {})
    step3_report = validation_reports.get("step-3")
    if step3_report and step3_report.get("overall_result") == "FAIL":
        hard_fails = step3_report.get("summary", {}).get("hard_fails", 0)
        io_errors = step3_report.get("summary", {}).get("io_errors", 0)
        raise ValueError(
            f"Import blocked: step-3 validation FAILED "
            f"({hard_fails} hard-fails, {io_errors} IO errors). "
            f"Fix issues and re-validate before importing."
        )

    # Support both old format (story_bible/structure) and new format (bible/spine)
    metadata = state.get("metadata", {})
    if "bible" in state and "spine" in state:
        # New format (interactive-play-writer pipeline)
        story_bible = _bible_to_story_bible(state["bible"])
        structure = _spine_to_structure(state["spine"])
    else:
        # Old format (make-interactive-show pipeline)
        story_bible = state["story_bible"]
        structure = state["structure"]
    scripts = state.get("scripts", {})

    project_id = str(uuid.uuid4())
    project_name = metadata.get("title") or story_bible.get("title", "Untitled")
    steering_notes = metadata.get("note", "")

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # 1. Create project
        cur.execute(
            """INSERT INTO projects (id, name, status, steering_notes)
               VALUES (%s, %s, 'done', %s)""",
            (project_id, project_name, steering_notes),
        )
        print(f"Created project: {project_name} ({project_id})")

        # 2. Insert story summary (from story_bible synopsis)
        synopsis_parts = []
        if "title" in story_bible:
            synopsis_parts.append(f"# {story_bible['title']}")
        if "genre" in story_bible:
            synopsis_parts.append(f"题材: {story_bible['genre']}")
        if "setting" in story_bible:
            synopsis_parts.append(f"\n## 世界观\n{json.dumps(story_bible['setting'], ensure_ascii=False, indent=2)}")
        if "plot_arcs" in story_bible:
            synopsis_parts.append(f"\n## 情节线\n{json.dumps(story_bible['plot_arcs'], ensure_ascii=False, indent=2)}")

        summary_content = "\n".join(synopsis_parts) if synopsis_parts else json.dumps(story_bible, ensure_ascii=False, indent=2)

        cur.execute(
            """INSERT INTO story_summaries (project_id, version, content, arc_breakdown)
               VALUES (%s, 1, %s, %s)""",
            (project_id, summary_content, Json(story_bible.get("plot_arcs", []))),
        )
        print("Inserted story summary")

        # 3. Insert world settings
        setting_data = {}
        for key in ("setting", "world_building", "themes", "genre", "title"):
            if key in story_bible:
                setting_data[key] = story_bible[key]
        if not setting_data:
            setting_data = story_bible

        cur.execute(
            """INSERT INTO world_settings (project_id, version, setting_data)
               VALUES (%s, 1, %s)""",
            (project_id, Json(setting_data)),
        )
        print("Inserted world settings")

        # 4. Insert characters
        characters = story_bible.get("characters", [])
        if isinstance(characters, dict):
            characters = [{"name": k, **v} if isinstance(v, dict) else {"name": k, "description": v}
                          for k, v in characters.items()]

        for char in characters:
            name = char.get("name", "Unknown")
            profile = {k: v for k, v in char.items() if k != "name"}
            cur.execute(
                """INSERT INTO characters (project_id, version, name, profile_data)
                   VALUES (%s, 1, %s, %s)""",
                (project_id, name, Json(profile)),
            )
        print(f"Inserted {len(characters)} characters")

        # 5. Insert DAG nodes
        episodes = structure.get("episodes", [])
        node_positions = compute_positions(episodes)

        for ep in episodes:
            ep_id = ep["id"]
            is_ending = ep.get("beat_type") == "ending"
            is_dead_end = ep.get("is_dead_end", False)

            # Determine scene_type
            if is_ending:
                scene_type = "ending"
            elif is_dead_end:
                scene_type = "hidden_ending"
            elif ep.get("choice") is not None:
                scene_type = "choice"
            else:
                scene_type = "normal"

            # Episode number from ID
            ep_num = extract_episode_number(ep_id)

            pos = node_positions.get(ep_id, (0, 0))

            cur.execute(
                """INSERT INTO dag_nodes
                   (project_id, version, node_key, title, summary, scene_type,
                    is_ending, is_hidden_ending, episode_number, episode_title,
                    position_x, position_y)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    project_id, ep_id, ep["title"], ep.get("summary", ""),
                    scene_type, is_ending, is_dead_end,
                    ep_num, ep.get("title", ""),
                    pos[0], pos[1],
                ),
            )
        print(f"Inserted {len(episodes)} DAG nodes")

        # 6. Insert DAG edges
        edge_count = 0
        for ep in episodes:
            choice = ep.get("choice")
            if not choice:
                continue
            options = choice.get("options", [])
            for idx, opt in enumerate(options):
                target = opt.get("next")
                if not target:
                    continue
                label = opt.get("text", f"Option {idx + 1}")
                cur.execute(
                    """INSERT INTO dag_edges
                       (project_id, version, source_node_key, target_node_key,
                        choice_label, choice_index)
                       VALUES (%s, 1, %s, %s, %s, %s)""",
                    (project_id, ep["id"], target, label, idx),
                )
                edge_count += 1
        print(f"Inserted {edge_count} DAG edges")

        # 7. Insert scene scripts
        script_count = 0
        for node_key, content in scripts.items():
            cur.execute(
                """INSERT INTO scene_scripts
                   (project_id, node_key, version, content, status)
                   VALUES (%s, %s, 1, %s, 'ready')""",
                (project_id, node_key, content),
            )
            script_count += 1
        print(f"Inserted {script_count} scene scripts")

        conn.commit()
        print(f"\nImport complete! Project ID: {project_id}")
        print(f"Status: done")

        # Update state to step-4 if using new format
        if "bible" in state and "spine" in state:
            state["step"] = "step-4"
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"State updated to step-4")

        return project_id

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def _bible_to_story_bible(bible: dict) -> dict:
    """Convert new-format bible to old story_bible format for DB import."""
    story_bible = {
        "title": bible.get("title", ""),
        "genre": bible.get("genre", ""),
        "tone": bible.get("tone", ""),
        "dramatic_question": bible.get("dramatic_question", ""),
        "characters": bible.get("characters", []),
        "setting": bible.get("world", {}),
        "themes": bible.get("themes", []),
    }
    if bible.get("protagonist"):
        story_bible["protagonist"] = bible["protagonist"]
    if bible.get("canon_facts"):
        story_bible["canon_facts"] = bible["canon_facts"]
    return story_bible


def _spine_to_structure(spine: dict) -> dict:
    """Convert new-format spine to old structure format for DB import."""
    nodes = spine.get("nodes", [])
    edges = spine.get("edges", [])

    # Build edge lookup: src → list of edges
    edge_map: dict[str, list[dict]] = {}
    for e in edges:
        edge_map.setdefault(e["src"], []).append(e)

    episodes = []
    for node in nodes:
        ep: dict = {
            "id": node["id"],
            "title": node.get("title", ""),
            "summary": node.get("summary", ""),
            "beat_type": node.get("kind", "scene"),
            "is_dead_end": node["id"].startswith("DE"),
        }

        # Convert outgoing edges to choice format
        out_edges = edge_map.get(node["id"], [])
        if out_edges:
            options = []
            for idx, e in enumerate(out_edges):
                options.append({
                    "text": e.get("label", f"Option {idx + 1}"),
                    "next": e["dst"],
                })
            ep["choice"] = {
                "question": node.get("choice_question", ""),
                "options": options,
            }

        episodes.append(ep)

    return {"episodes": episodes}


def extract_episode_number(ep_id: str) -> int:
    """Extract numeric episode number from ID like EP01, DE_A, END_B."""
    import re
    m = re.search(r"(\d+)", ep_id)
    if m:
        return int(m.group(1))
    # Non-numeric IDs: assign high numbers
    mapping = {"DE_A": 90, "DE_B": 91, "DE_C": 92, "END_A": 95, "END_B": 96, "END_C": 97}
    return mapping.get(ep_id, 99)


def compute_positions(episodes: list) -> dict:
    """Graph-aware DAG layout with 3 columns: dead ends | main spine | variants.

    The webapp swaps coordinates: DB position_x → visual Y, DB position_y → visual X.
    So we set position_x = row (vertical) and position_y = column (horizontal).
    """

    # Build adjacency
    children = {}   # src → [dst, ...]
    parents = {}    # dst → [src, ...]
    node_map = {ep["id"]: ep for ep in episodes}
    all_ids = set(node_map)

    for ep in episodes:
        choice = ep.get("choice")
        if not choice:
            continue
        for opt in choice.get("options", []):
            tgt = opt.get("next")
            if tgt and tgt in all_ids:
                children.setdefault(ep["id"], []).append(tgt)
                parents.setdefault(tgt, []).append(ep["id"])

    # Find root (no parents, not a dead end)
    root = next(
        (eid for eid in all_ids if eid not in parents and not eid.startswith("DE")),
        episodes[0]["id"],
    )

    # Find the main spine by following EP numbering (EP01→EP02→...→EP20),
    # not longest path (which would detour through variants like EP01A).
    import re

    def _spine_priority(nid):
        """Main EP nodes first, then variants, then dead ends."""
        if nid.startswith("DE"):
            return (3, 0, nid)
        m = re.match(r"^EP(\d+)([A-Z]?)$", nid)
        if m:
            num, suffix = int(m.group(1)), m.group(2)
            return (1 if suffix else 0, num, suffix)
        return (2, 0, nid)

    main_path = [root]
    visited = {root}
    current = root
    while True:
        kids = children.get(current, [])
        if not kids:
            break
        nxt = min(
            (k for k in kids if k not in visited),
            key=_spine_priority,
            default=None,
        )
        if nxt is None:
            break
        visited.add(nxt)
        main_path.append(nxt)
        current = nxt
    main_set = set(main_path)
    main_row = {nid: i for i, nid in enumerate(main_path)}

    # Layout constants — generous spacing for readability
    ROW_SP = 200    # vertical gap between rows (nodes are ~80px tall)
    COL_MAIN = 0    # main spine center
    COL_VAR = 350   # variant branches to the right
    COL_DE = -350   # dead ends to the left

    positions = {}

    # 1. Main path: center column, sequential rows
    for nid in main_path:
        positions[nid] = (main_row[nid] * ROW_SP, COL_MAIN)

    # 2. Non-main nodes: find their main-path fork parent to determine row
    remaining = [ep for ep in episodes if ep["id"] not in main_set]

    # First pass: nodes with at least one main-path parent
    for ep in remaining:
        nid = ep["id"]
        is_de = ep.get("is_dead_end", False) or nid.startswith("DE")
        main_pars = [p for p in parents.get(nid, []) if p in main_set]
        if not main_pars:
            continue  # handle in second pass (variant chains)
        fork_row = min(main_row[p] for p in main_pars)
        row = fork_row + 1  # one row below the fork point
        col = COL_DE if is_de else COL_VAR
        positions[nid] = (row * ROW_SP, col)

    # Second pass: nodes whose parents are variants (chains like EP13A→EP13B)
    for ep in remaining:
        nid = ep["id"]
        if nid in positions:
            continue
        is_de = ep.get("is_dead_end", False) or nid.startswith("DE")
        for p in parents.get(nid, []):
            if p in positions:
                parent_y = positions[p][0]
                col = COL_DE if is_de else COL_VAR
                positions[nid] = (parent_y + ROW_SP, col)
                break
        if nid not in positions:
            positions[nid] = (0, COL_DE if is_de else COL_VAR)

    # 3. De-overlap: shift nodes that share the same (row, col)
    from collections import defaultdict
    grid = defaultdict(list)
    for nid, (px, py) in positions.items():
        grid[(px, py)].append(nid)

    for key, nids in grid.items():
        if len(nids) <= 1:
            continue
        px, py = key
        # Spread vertically with half-row offsets
        for i, nid in enumerate(nids):
            positions[nid] = (px + i * (ROW_SP // 2), py)

    return positions


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_state.py <state.json> [--env <.env path>]")
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
    project_id = import_project(state_path, db_url)
    print(f"\nProject URL: check your webapp for project {project_id}")
