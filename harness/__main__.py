"""CLI entry point: python -m harness <story_file> [options]"""

import argparse
import logging
import os
import sys
from pathlib import Path

from .models import Params


def _load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE lines without overriding the caller environment."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _report_main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(
        prog="python -m harness report",
        description="Compute the quality report card for a run dir or graph JSON.",
    )
    p.add_argument("path", help="Run directory or graph_final.json path")
    p.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = p.parse_args(argv)

    import json as _json

    from .metrics import render_markdown, report_from_path

    rep = report_from_path(args.path)
    if args.json:
        print(_json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(rep))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        _report_main(sys.argv[2:])
        return

    p = argparse.ArgumentParser(
        prog="python -m harness",
        description="Build an interactive story graph from a novel/story.",
    )
    p.add_argument("story", help="Path to raw story text file (UTF-8)")
    p.add_argument("-i", "--instruction", default="", help="Production instruction text or @file")
    p.add_argument("--playthrough", type=float, default=55, help="Target shortest-playthrough minutes (default 55)")
    p.add_argument("--total", type=float, default=100, help="Total budget minutes across all nodes (default 100)")
    p.add_argument("--max-fix", type=int, default=10, help="Max fix attempts per edge (default 10)")
    p.add_argument("--chapters", default=None, help="Chapter range to process, e.g. 1-80")
    p.add_argument(
        "--model",
        default="glm",
        help=(
            "LLM model profile: glm, deepseek, cc, fireworks, or a Fireworks "
            "model id (default: glm)"
        ),
    )
    p.add_argument(
        "--tier",
        default="",
        choices=["", "premium", "cheap"],
        help="Harness tier: premium uses Claude Code; cheap uses OpenRouter free-first routing",
    )
    p.add_argument("--cc", action="store_true", help="Alias for --model cc")
    p.add_argument("--resume", default=None, metavar="RUN_DIR",
                   help="Resume from a previous run directory (e.g. harness_output/run_20260605_234041)")
    p.add_argument("--min-endings", type=int, default=1, help="Minimum ENDING nodes (default 1)")
    p.add_argument("--no-upload", action="store_true", help="Skip the final webapp DB upload")
    p.add_argument("--live-upload", action="store_true",
                   help="Re-upload intermediary state to the webapp at phase milestones (one stable project)")
    p.add_argument("--until", default="",
                   choices=["", "phase1", "outline", "cornerstone", "expansion"],
                   help="Stop after this pass (fast iteration; writes report card and exits)")
    p.add_argument("--max-llm-calls", type=int, default=0,
                   help="Hard cap on LLM calls (0 = unlimited). Safety valve for expensive models.")
    p.add_argument("--mini", action="store_true",
                   help="Mini-story: generate a tiny 3-node unit (1 choice → 2 endings) "
                        "from the opening chapters with the real prompts + quality passes")
    p.add_argument("--first-episode", action="store_true",
                   help="Lab mode: stop after trunk, run metadata/semantics/prose on the "
                        "ROOT node only, write first_episode.md (fast choice-prompt iteration; "
                        "implies --no-upload; combine with HARNESS_LLM_CACHE=1)")
    p.add_argument("--editor-notes", default="", help="Editor guidance for cornerstone generation (text or @file)")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy HTTP debug logs (httpx, httpcore, urllib3)
    for noisy in ("httpx", "httpcore", "urllib3", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _load_dotenv()

    # Backend/model profile
    from .llm import set_model_profile, set_tier
    if args.tier:
        set_tier(args.tier)
    elif args.cc:
        set_model_profile("cc")
    else:
        set_model_profile(args.model)

    # Read story
    with open(args.story, encoding="utf-8") as f:
        raw_novel = f.read()

    # Instruction: inline text or @filepath
    instruction = args.instruction
    if instruction and instruction.startswith("@"):
        with open(instruction[1:], encoding="utf-8") as f:
            instruction = f.read()

    # Editor notes: inline text or @filepath
    editor_notes = args.editor_notes
    if editor_notes and editor_notes.startswith("@"):
        with open(editor_notes[1:], encoding="utf-8") as f:
            editor_notes = f.read()

    # Parse chapter range
    chapter_range = None
    if args.chapters:
        parts = args.chapters.split("-")
        if len(parts) == 2:
            chapter_range = (int(parts[0]), int(parts[1]))
        elif len(parts) == 1:
            ch = int(parts[0])
            chapter_range = (ch, ch)
        else:
            print(f"Invalid --chapters format: {args.chapters!r} (expected e.g. 1-80)")
            sys.exit(1)

    params = Params(
        target_playthrough_min=args.playthrough,
        total_budget_min=args.total,
        max_fix_attempts=args.max_fix,
        min_ending_count=args.min_endings,
        editor_notes=editor_notes,
        skip_upload=args.no_upload or args.first_episode,
        live_upload=args.live_upload and not args.first_episode,
        stop_after=args.until,
        first_episode=args.first_episode,
        mini_story=args.mini,
        max_llm_calls=args.max_llm_calls,
    )

    # Derive project name from filename
    project_name = Path(args.story).stem

    from .harness import build
    graph = build(raw_novel, instruction, params, chapter_range=chapter_range,
                  project_name=project_name, resume_dir=args.resume)

    print(f"\nDone: {len(graph.nodes)} nodes, "
          f"{sum(1 for n in graph.nodes.values() if n.ending == 'ENDING')} endings")


if __name__ == "__main__":
    main()
