"""Export + upload an already-completed harness run to the webapp DB.

Usage: python -m scripts.upload_existing_run harness_output/mini_ds [project_name]
"""
import json
import sys
from pathlib import Path

from harness.checkpoint import find_latest_checkpoint, load_graph
from harness.registry import seed_registry
from harness.web_export import write_web_exports
from harness.upload import upload_to_webapp


def main() -> None:
    run_dir = Path(sys.argv[1])
    project_name = sys.argv[2] if len(sys.argv) > 2 else run_dir.name

    # Prefer graph_final.json, else latest checkpoint
    graph_final = run_dir / "graph_final.json"
    cp = str(graph_final) if graph_final.exists() else find_latest_checkpoint(str(run_dir))
    print(f"Loading graph from: {cp}")
    graph = load_graph(cp)

    bible = json.loads((run_dir / "phase1_complete.json").read_text())["bible"]
    registry = seed_registry(bible)

    paths = write_web_exports(graph, registry, bible, str(run_dir),
                              project_name=project_name)
    print(f"Wrote export: {paths['web_app_export']}")

    pid = upload_to_webapp(paths["web_app_export"], status="done")
    print(f"Uploaded. project_id = {pid}")


if __name__ == "__main__":
    main()
