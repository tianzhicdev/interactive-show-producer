#!/usr/bin/env python3
"""Fix DAG node positions for webapp visualization.

The webapp uses XYFlow with a coordinate swap:
  DB position_x → visual Y (vertical)
  DB position_y → visual X (horizontal)

So for a top-to-bottom flowchart:
  position_x = row (increases downward)
  position_y = column (spreads horizontally)
"""

import os
import sys

import psycopg2


def load_env(env_path: str) -> str:
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1]
    raise ValueError("DATABASE_URL not found")


# Row spacing (vertical) and column spacing (horizontal)
ROW = 180
COL = 280

# Center column
CX = 3 * COL  # 840

# Hand-crafted positions: (position_x=row, position_y=col)
# This creates a clean top-down DAG flow
POSITIONS = {
    # ── Shared prefix: single column, top to bottom ──
    "EP01": (0 * ROW, CX),
    "EP02": (1 * ROW, CX),
    "EP03": (2 * ROW, CX),
    "EP04": (3 * ROW, CX),
    "EP05": (4 * ROW, CX),
    "EP06": (5 * ROW, CX),
    "EP07": (6 * ROW, CX),
    "EP08": (7 * ROW, CX),

    # ── 3-way fork ──
    "EP09a": (9 * ROW, 1 * COL),       # A-line: left
    "EP09b": (9 * ROW, CX),            # B-line: center
    "EP09c": (9 * ROW, 5 * COL),       # C-line: right

    # ── A-line branches ──
    "EP10a":  (10 * ROW, 0 * COL + 60),  # A武力: far left
    "EP10a2": (10 * ROW, 2 * COL - 60),  # A智谋: center-left
    "EP11a":  (11 * ROW, 1 * COL),       # A converge

    # ── B-line branches ──
    "EP10b":  (10 * ROW, CX - COL // 2),  # B高调: left of center
    "EP10b2": (10 * ROW, CX + COL // 2),  # B暗蚕: right of center
    "EP11b":  (11 * ROW, CX),             # B converge

    # ── C-line branches ──
    "EP10c":  (10 * ROW, 4 * COL + 60),  # C示弱: center-right
    "EP10c2": (10 * ROW, 6 * COL - 60),  # C强势: far right
    "EP11c":  (11 * ROW, 5 * COL),       # C converge

    # ── Convergence at EP13, then shared endgame ──
    "EP13": (13 * ROW, CX),
    "EP14": (14 * ROW, CX),
    "EP15": (15 * ROW, CX),
    "EP16": (16 * ROW, CX),
    "EP17": (17 * ROW, CX),

    # ── Endings: spread at bottom ──
    "END_A": (19 * ROW, 1 * COL),
    "END_C": (19 * ROW, CX),
    "END_B": (19 * ROW, 5 * COL),

    # ── Dead ends: placed beside their source regions ──
    "DE01": (1 * ROW, 6 * COL),         # Right side, near EP01-EP03 sources
    "DE02": (5 * ROW, 6 * COL),         # Right side, near EP04-EP07 sources
    "DE_A": (10 * ROW, -1 * COL),       # Far left, beside A-line
    "DE_B": (10 * ROW, 7 * COL + 60),   # Far right, beside B/C-line
    "DE_C": (11 * ROW, 7 * COL + 60),   # Far right, below DE_B
    "DE03": (15 * ROW, 6 * COL),        # Right side, near EP13-EP16 sources
}


def fix_positions(project_id: str, db_url: str):
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # Get current version
        cur.execute(
            "SELECT MAX(version) FROM dag_nodes WHERE project_id = %s",
            (project_id,),
        )
        version = cur.fetchone()[0]
        if version is None:
            print("No DAG nodes found for this project.")
            return

        updated = 0
        for node_key, (px, py) in POSITIONS.items():
            cur.execute(
                """UPDATE dag_nodes
                   SET position_x = %s, position_y = %s
                   WHERE project_id = %s AND version = %s AND node_key = %s""",
                (px, py, project_id, version, node_key),
            )
            if cur.rowcount > 0:
                updated += 1

        conn.commit()
        print(f"Updated {updated}/{len(POSITIONS)} node positions (version {version})")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_dag_positions.py <project_id> [--env <.env>]")
        sys.exit(1)

    project_id = sys.argv[1]
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")

    if "--env" in sys.argv:
        idx = sys.argv.index("--env")
        env_path = sys.argv[idx + 1]

    db_url = load_env(env_path)
    fix_positions(project_id, db_url)
