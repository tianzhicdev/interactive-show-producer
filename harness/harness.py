"""§4 — Main algorithm: build, expand_edge, stabilize."""

from __future__ import annotations

import copy
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import (
    Feedback, Graph, HarnessError, Highlight, Node, NodeId, Params,
    Registry, Reject, Violation,
)

# Sentinel: parallel thread hit a transient error (timeout, network).
# Distinct from None (generation genuinely failed) — edge should NOT be
# marked non-expandable and will be retried next iteration.
_TRANSIENT = object()
from .guaranteed import compute_guaranteed
from .registry import seed_registry
from .graph_ops import build_goal, choose_expansion_type, merge, rank_edges
from .budget import estimate_minutes, shortest_playthrough, total_minutes
from .validation import validate, validate_deterministic, compute_node_memories
from .checkpoint import (
    checkpoint, checkpoint_phase1, detect_resume_phase,
    find_latest_checkpoint, init_run_dir, load_graph, load_phase1,
    set_run_dir, write,
)
from .chunker import build_chapter_index, build_extraction_chunks
from .web_export import write_web_exports
from .upload import upload_to_webapp
from .llm import (
    creative_graph_fix, creative_writing, creative_writing_fix, fill_prose,
    fix_s4_question, get_cornerstone_nodes, get_highlights, get_highlights_chunk,
    get_story_bible, get_story_bible_chunk, merge_story_bible_chunks,
    fix_skeleton_node_semantics, validate_semantic_node,
    validate_skeleton_node_semantic,
)

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back (with a warning) on a malformed value
    rather than crashing the whole run."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Ignoring malformed %s=%r; using %d", name, raw, default)
        return default


def build(
    raw_novel: str, instruction: str, params: Params,
    chapter_range: tuple[int, int] | None = None,
    project_name: str | None = None,
    resume_dir: str | None = None,
) -> Graph:
    """§4 — Main entry point. Builds an interactive story graph from a novel.

    Three phases only:
      Phase 1: Extraction (bible, chapters, highlights, registry)
      Phase 2: Cornerstone (skeleton graph with prose, stabilize until clean)
      Phase 3: Expansion loop (rank edges, expand, full-graph validate after each)
    No separate prose phase — prose is written during expansion.

    Args:
        chapter_range: Optional (start, end) to limit processing to a chapter range.
        resume_dir: Optional path to a previous run directory to resume from.
    """
    # Handle resume
    if resume_dir:
        return _build_resume(raw_novel, instruction, params, chapter_range,
                             project_name, resume_dir)

    return _build_fresh(raw_novel, instruction, params, chapter_range, project_name)


def _build_resume(
    raw_novel: str, instruction: str, params: Params,
    chapter_range: tuple[int, int] | None,
    project_name: str | None,
    resume_dir: str,
) -> Graph:
    """Resume a build from a previous run directory."""
    import glob as _glob
    if resume_dir == "latest":
        candidates = sorted(_glob.glob("harness_output/run_*"))
        if not candidates:
            raise HarnessError("--resume latest: no run directories found")
        resume_dir = candidates[-1]
        log.info(f"--resume latest → {resume_dir}")

    if not os.path.isdir(resume_dir):
        raise HarnessError(
            f"--resume directory does not exist: {resume_dir!r} — refusing to "
            f"silently start a fresh run (check the path, or use --resume latest)")

    phase = detect_resume_phase(resume_dir)
    log.info(f"Resuming from {resume_dir} (detected phase: {phase})")

    if phase == "none":
        raise HarnessError(
            f"No usable checkpoint in {resume_dir!r} — refusing to silently "
            f"start a fresh run (a typo here once burned a full generation)")

    # Set run dir to resume directory (new files written here)
    run_dir = set_run_dir(resume_dir)

    # Load Phase 1 data
    phase1_data = load_phase1("phase1_complete", resume_dir)
    if not phase1_data:
        log.warning("No phase1_complete.json — starting fresh")
        return _build_fresh(raw_novel, instruction, params, chapter_range, project_name)

    bible = phase1_data.get("bible", {})
    chapters_raw = phase1_data.get("chapters", {})
    chapters = {int(k): v for k, v in chapters_raw.items()}
    highlights_raw = phase1_data.get("highlights", [])
    highlights = [
        Highlight(id=h["id"], chapter=h["chapter"], weight=h["weight"], gloss=h["gloss"],
                  satisfaction_type=h.get("satisfaction_type", ""),
                  hook_type=h.get("hook_type", ""))
        for h in highlights_raw
    ]

    log.info(f"Loaded Phase 1: {len(bible.get('facts', []))} facts, "
             f"{len(chapters)} chapters, {len(highlights)} highlights")

    # Apply chapter range filter
    if chapter_range:
        ch_start, ch_end = chapter_range
        chapters = {k: v for k, v in chapters.items() if ch_start <= k <= ch_end}

    registry = seed_registry(bible)

    if params.mini_story:
        return _build_mini_story(bible, chapters, registry, params, run_dir, project_name)

    # P1 outline: reuse the saved artifact; regenerate only if absent
    outline = _load_outline(resume_dir)
    if outline is None and phase in ("phase1", "expansion"):
        log.info("=== P1: Outline plan (resumed run had none) ===")
        from .llm import generate_outline
        outline = generate_outline(bible, highlights, params, _chapter_bounds(chapters))
        _save_outline(outline, run_dir)

    if phase == "expansion":
        # Load graph from latest checkpoint
        cp_path = find_latest_checkpoint(resume_dir)
        graph = load_graph(cp_path)
        log.info(f"Resuming from expansion checkpoint: {len(graph.nodes)} nodes")

        # Re-register any facts produced by nodes (they may have declared new facts)
        _recover_registry_from_graph(graph, registry)
        # Backfill structured fields on old nodes (pre-overhaul checkpoints)
        _backfill_structured_fields(graph)
        # `guaranteed` is not serialized in checkpoints — recompute before any reader.
        compute_guaranteed(graph, registry)
    elif phase == "phase3_done":
        cp_path = find_latest_checkpoint(resume_dir)
        graph = load_graph(cp_path)
        log.info(f"Resuming from phase3_done checkpoint: {len(graph.nodes)} nodes")
        _recover_registry_from_graph(graph, registry)
        _backfill_structured_fields(graph)
        # `guaranteed` is not serialized in checkpoints — recompute before any reader.
        compute_guaranteed(graph, registry)
        # STRICT first-episode flows through the SAME post-skeleton pipeline as a
        # full run; only Phase 4/4.5 narrow to episode-1 nodes (see _build_phase3_5_onwards).
        return _build_phase3_5_onwards(graph, bible, chapters, highlights,
                                        registry, params, project_name, run_dir)
    elif phase == "phase1":
        # Phase 1 done but no cornerstone — run Phase 2
        log.info("=== P2: Trunk (cornerstone from outline, resumed) ===")
        graph, cornerstone_new_facts = get_cornerstone_nodes(
            bible, registry, params, _chapter_bounds(chapters), outline=outline
        )
        if cornerstone_new_facts:
            for decl in cornerstone_new_facts:
                if decl.id not in registry:
                    registry[decl.id] = decl
            log.info(f"Cornerstone declared {len(cornerstone_new_facts)} new facts, "
                     f"registry now {len(registry)} facts")
        log.info(f"Cornerstone: {len(graph.nodes)} nodes")
        graph = stabilize_cornerstone(graph, registry, params, bible, chapters, highlights)
        checkpoint(graph)
    else:
        log.warning(f"Unknown phase {phase} — starting fresh")
        return _build_fresh(raw_novel, instruction, params, chapter_range, project_name)

    # Continue with Phase 3 (expansion runs identically; first-episode narrows P4/P4.5)
    return _build_phase3(graph, bible, chapters, highlights, registry, params,
                         project_name, run_dir, outline=outline)


def _recover_registry_from_graph(graph: Graph, registry: Registry) -> None:
    """Recover fact declarations from graph node effects (for resume)."""
    from .models import FactDecl

    def _recover(fid: str, node_id: str, kind: str = "event") -> None:
        if fid not in registry:
            registry[fid] = FactDecl(
                id=fid, kind=kind,
                gloss=f"(recovered from node {node_id})",
                initial=False, invariant=False,
            )

    for node in graph.nodes.values():
        for effect in node.produces:
            _recover(effect.fact, node.id)
        for req in node.requires:
            _recover(req.fact, node.id)
        for req in node.entry_invariants:
            _recover(req.fact, node.id)
        for choice in node.choices:
            for req in choice.label_requires:
                _recover(req.fact, node.id)
            for eff in choice.state_delta:
                # Per-choice deltas are usually player dispositions
                _recover(eff.fact, node.id, kind="disposition")


def _backfill_structured_fields(graph: Graph) -> None:
    """Backfill structured fields on nodes from pre-overhaul checkpoints.

    Old checkpoints may have nodes without entry_context, exit_context,
    or structured content. Fill in minimal defaults so validation passes.
    """
    from .models import make_scene_header
    filled = 0
    for node in graph.nodes.values():
        changed = False
        loc = node.get_scene_location() or "（未设定）"
        if not node.entry_context:
            node.entry_context = loc
            changed = True
        if not node.exit_context:
            node.exit_context = loc
            changed = True
        # If no content but has legacy prose, __post_init__ already converted.
        # If no content at all, add a minimal scene_header.
        if not node.skeleton:
            node.skeleton = [make_scene_header(loc, node.get_scene_time() or "（未设定）",
                                                node.get_scene_characters() or ["（未设定）"])]
            changed = True
        if not node.content:
            node.content = list(node.skeleton)
            changed = True
        if changed:
            filled += 1
    if filled:
        log.info(f"Backfilled structured fields on {filled} old nodes")


def _build_fresh(
    raw_novel: str, instruction: str, params: Params,
    chapter_range: tuple[int, int] | None,
    project_name: str | None,
) -> Graph:
    """Full fresh build from scratch."""
    run_dir = init_run_dir()
    log.info(f"Run directory: {run_dir}")
    log.info("=== Phase 1: Extraction ===")

    text_len = len(raw_novel)
    log.info(f"Story size: {text_len:,} chars")

    # Phase 1a: Build chapter index (pure text, no LLM)
    chapters = build_chapter_index(raw_novel)
    if chapters:
        log.info(f"Phase 1a: Found {len(chapters)} chapters via text markers")
    else:
        # No chapter markers found — create a single "chapter" from the full text
        chapters = {1: raw_novel}
        log.info("Phase 1a: No chapter markers found, treating as single chapter")

    checkpoint_phase1("chapters", chapters=chapters)

    # Apply chapter range filter
    if chapter_range:
        ch_start, ch_end = chapter_range
        chapters = {k: v for k, v in chapters.items() if ch_start <= k <= ch_end}
        log.info(f"Phase 1a: Filtered to chapters {ch_start}-{ch_end} ({len(chapters)} chapters)")

    # Phase 1b: Map/reduce extraction chunks.
    extraction_chunks = build_extraction_chunks(raw_novel, chapters, max_chars=8000, overlap_chars=600)
    if chapter_range:
        ch_start, ch_end = chapter_range
        extraction_chunks = [
            c for c in extraction_chunks
            if c.get("chapter_end", 1) >= ch_start and c.get("chapter_start", 1) <= ch_end
        ]
    total_chunk_chars = sum(c["char_count"] for c in extraction_chunks)
    avg_chunk = total_chunk_chars // max(1, len(extraction_chunks))
    log.info(
        "Phase 1b: Built %d extraction chunks (target<=8,000 chars, avg=%s, total=%s)",
        len(extraction_chunks), f"{avg_chunk:,}", f"{total_chunk_chars:,}",
    )
    for chunk in extraction_chunks:
        log.debug(
            "Phase 1b chunk %s: chapters %s-%s, %s chars",
            chunk["index"], chunk.get("chapter_start"), chunk.get("chapter_end"),
            f"{chunk['char_count']:,}",
        )

    # Phase 1c: Bible map/reduce.
    if len(extraction_chunks) > 1:
        chunk_bibles: list[dict] = []
        for chunk in extraction_chunks:
            if not params.llm_calls_left():
                log.warning("LLM budget exhausted during bible chunk extraction")
                break
            label = _chunk_label(chunk)
            log.info(
                "Phase 1c: Bible map chunk %s/%s, chapters %s-%s, %s chars (parallel)",
                chunk["index"], len(extraction_chunks),
                chunk.get("chapter_start"), chunk.get("chapter_end"),
                f"{chunk['char_count']:,}",
            )
            chunk_bibles.append(chunk)  # placeholder; replaced below

        # P0: map calls run in parallel (pure extraction, no shared state)
        def _bible_one(chunk: dict) -> dict:
            return get_story_bible_chunk(
                _chunk_prompt_text(chunk), instruction, params,
                chunk_label=_chunk_label(chunk),
            )

        _ingest_workers = _env_int("HARNESS_INGEST_WORKERS", 4)
        with ThreadPoolExecutor(max_workers=max(1, min(_ingest_workers, len(chunk_bibles)))) as pool:
            results = list(pool.map(_bible_one, chunk_bibles))
        for chunk, chunk_bible in zip(chunk_bibles, results):
            log.info(
                "Phase 1c: Chunk %s bible extracted %d characters, %d facts",
                chunk["index"],
                len(chunk_bible.get("characters", [])),
                len(chunk_bible.get("facts", [])),
            )
        chunk_bibles = results
        log.info("Phase 1c: Reducing %d bible chunks deterministically", len(chunk_bibles))
        bible = merge_story_bible_chunks(chunk_bibles)
    else:
        source = _chunk_prompt_text(extraction_chunks[0]) if extraction_chunks else raw_novel
        bible = get_story_bible(source, instruction, params)
    log.info(f"Bible: {len(bible.get('facts', []))} facts, "
             f"{len(bible.get('characters', []))} characters")
    checkpoint_phase1("bible", bible=bible)

    # Phase 1d: Highlights map/reduce.
    if len(extraction_chunks) > 1:
        all_highlights: list[Highlight] = []
        for chunk in extraction_chunks:
            if not params.llm_calls_left():
                log.warning("LLM budget exhausted during highlight extraction")
                break
            log.info(
                "Phase 1d: Highlights map chunk %s/%s, chapters %s-%s, %s chars (parallel)",
                chunk["index"], len(extraction_chunks),
                chunk.get("chapter_start"), chunk.get("chapter_end"),
                f"{chunk['char_count']:,}",
            )
            all_highlights.append(chunk)  # placeholder; replaced below

        def _hl_one(chunk: dict) -> list[Highlight]:
            return get_highlights_chunk(
                _chunk_prompt_text(chunk), instruction, params,
                chunk_label=_chunk_label(chunk),
                chapter_start=int(chunk.get("chapter_start", 1)),
                chapter_end=int(chunk.get("chapter_end", 1)),
            )

        _ingest_workers = _env_int("HARNESS_INGEST_WORKERS", 4)
        with ThreadPoolExecutor(max_workers=max(1, min(_ingest_workers, len(all_highlights)))) as pool:
            hl_results = list(pool.map(_hl_one, all_highlights))
        for chunk, chunk_highlights in zip(all_highlights, hl_results):
            log.info(
                "Phase 1d: Chunk %s highlights extracted %d",
                chunk["index"], len(chunk_highlights),
            )
        all_highlights = [h for chunk_hl in hl_results for h in chunk_hl]
        highlights = _reduce_highlights(all_highlights, max_items=24)
        log.info(
            "Phase 1d: Reduced highlights %d -> %d",
            len(all_highlights), len(highlights),
        )
    else:
        source = _chunk_prompt_text(extraction_chunks[0]) if extraction_chunks else raw_novel
        highlights = get_highlights(source, instruction, params)

    log.info(f"Highlights: {len(highlights)}")
    checkpoint_phase1("phase1_complete", bible=bible, chapters=chapters, highlights=highlights)

    registry = seed_registry(bible)
    log.info(f"Registry: {len(registry)} facts")

    if params.stop_after == "phase1":
        log.info("Stopping after phase1 (--until phase1)")
        return Graph(root="", nodes={})

    if params.mini_story:
        return _build_mini_story(bible, chapters, registry, params, run_dir, project_name)

    log.info("=== P1: Outline plan ===")
    from .llm import generate_outline
    outline = generate_outline(bible, highlights, params, _chapter_bounds(chapters))
    _save_outline(outline, run_dir)
    log.info("Outline: %d sequences, %d ledger entries, %d player stats — %s",
             len(outline.get("sequences", [])), len(outline.get("ledger", [])),
             len(outline.get("player_stats", [])),
             outline.get("main_dramatic_question", "")[:60])
    if params.stop_after == "outline":
        log.info("Stopping after outline (--until outline)")
        return Graph(root="", nodes={})

    log.info("=== P2: Trunk (cornerstone from outline) ===")
    graph, cornerstone_new_facts = get_cornerstone_nodes(
        bible, registry, params, _chapter_bounds(chapters), outline=outline
    )
    _clamp_node_chapters(graph.nodes, chapters)
    # Register any new facts declared by the cornerstone LLM
    if cornerstone_new_facts:
        for decl in cornerstone_new_facts:
            if decl.id not in registry:
                registry[decl.id] = decl
        log.info(f"Cornerstone declared {len(cornerstone_new_facts)} new facts, "
                 f"registry now {len(registry)} facts")
    log.info(f"Cornerstone: {len(graph.nodes)} nodes")

    # Phase 2 stabilize: loop FOREVER until cornerstone is clean.
    # Only exit condition: llm budget exhausted. (STRICT first-episode runs this
    # identically — the root must be stabilized exactly as in a full run.)
    graph = stabilize_cornerstone(graph, registry, params, bible, chapters, highlights)
    checkpoint(graph)
    _live_upload(graph, registry, bible, run_dir, project_name, params)

    if params.stop_after == "cornerstone":
        from .metrics import write_report
        write_report(graph, run_dir)
        log.info("Stopping after cornerstone (--until cornerstone); report written")
        return graph

    return _build_phase3(graph, bible, chapters, highlights, registry, params,
                         project_name, run_dir, outline=outline)


def _save_outline(outline: dict, run_dir: str) -> None:
    import json as _json
    path = os.path.join(run_dir, "outline.json")
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(outline, fh, ensure_ascii=False, indent=2)
    log.info(f"Outline written to {path}")


def _load_outline(run_dir: str) -> dict | None:
    import json as _json
    path = os.path.join(run_dir, "outline.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return _json.load(fh)


def _chunk_label(chunk: dict) -> str:
    return (
        f"chunk {chunk['index']} chapters "
        f"{chunk.get('chapter_start', 1)}-{chunk.get('chapter_end', 1)}"
    )


def _chunk_prompt_text(chunk: dict) -> str:
    parts: list[str] = []
    if chunk.get("context_before"):
        parts.append("## Previous context\n" + chunk["context_before"][-600:])
    parts.append("## Main chunk\n" + chunk["text"])
    if chunk.get("context_after"):
        parts.append("## Next context\n" + chunk["context_after"][:600])
    return "\n\n".join(parts)


def _clamp_node_chapters(nodes: dict[NodeId, Node], chapters: dict[int, str]) -> None:
    """Keep LLM-authored node chapter ranges inside the available source index."""
    if not chapters:
        return
    min_ch, max_ch = _chapter_bounds(chapters)
    for node in nodes.values():
        start, end = node.chapters
        original = (start, end)
        start = max(min_ch, min(max_ch, int(start or min_ch)))
        end = max(min_ch, min(max_ch, int(end or start)))
        if end < start:
            start, end = end, start
        node.chapters = (start, end)
        if node.chapters != original:
            log.info(
                "  Clamped %s chapters %s-%s to source bounds %s-%s => %s-%s",
                node.id, original[0], original[1], min_ch, max_ch, start, end,
            )


def _chapter_bounds(chapters: dict[int, str]) -> tuple[int, int]:
    if not chapters:
        return (1, 1)
    return (min(chapters), max(chapters))


def _reduce_highlights(highlights: list[Highlight], max_items: int) -> list[Highlight]:
    """Deterministically dedupe, rank, cap, and assign stable IDs."""
    deduped: dict[tuple[int, str], Highlight] = {}
    for h in highlights:
        gloss_key = re.sub(r"\s+", "", h.gloss).lower()[:80]
        key = (int(h.chapter), gloss_key)
        existing = deduped.get(key)
        if existing is None or h.weight > existing.weight:
            deduped[key] = h

    ranked = sorted(
        deduped.values(),
        key=lambda h: (-float(h.weight), int(h.chapter), h.gloss),
    )[:max_items]
    ranked = sorted(ranked, key=lambda h: (int(h.chapter), -float(h.weight), h.gloss))
    reduced: list[Highlight] = []
    for i, h in enumerate(ranked, start=1):
        reduced.append(Highlight(
            id=f"h{i:03d}",
            chapter=int(h.chapter),
            weight=float(h.weight),
            gloss=h.gloss,
            satisfaction_type=h.satisfaction_type,
            hook_type=h.hook_type,
        ))
    return reduced


def _build_phase3(
    graph: Graph, bible: dict, chapters: dict[int, str],
    highlights: list[Highlight], registry: Registry, params: Params,
    project_name: str | None, run_dir: str,
    outline: dict | None = None,
) -> Graph:
    """Phase 3: Expansion loop + Phase 4: Prose fill + final validation + export."""
    _clamp_node_chapters(graph.nodes, chapters)
    log.info("=== Phase 3: Expansion loop ===")

    def _same_target_pairs(g: Graph) -> list[NodeId]:
        # TRUNK pairs only (prologue/bottleneck): those are scaffolding that
        # expansion must break into real forks. Excursion-INTERIOR pairs
        # (kind=scene) are the designed stat-write reconvergence mechanism —
        # demanding their breakage would recurse forever (each break creates
        # a new interior pair).
        out = []
        for nid, node in g.nodes.items():
            if node.kind not in ("prologue", "bottleneck"):
                continue
            targets = [c.to for c in node.choices]
            if len(targets) == 2 and targets[0] == targets[1]:
                out.append(nid)
        return out

    iteration = 0
    prev_state_sig: tuple | None = None
    stuck = 0
    while params.llm_calls_left() and (
        total_minutes(graph, params) < params.total_budget_min
        or _same_target_pairs(graph)  # W2: pairs are scaffolding — budget may
        # not strand them in the product; keep expanding until all are broken
    ):
        iteration += 1
        tm = total_minutes(graph, params)
        sp = shortest_playthrough(graph, params)

        # Anti-spin guard: if nodes / total-minutes / residual-pair-count are all
        # unchanged for several iterations, no forward progress is possible (e.g.
        # only unbreakable pairs remain and the budget can't be met) — stop rather
        # than loop until the LLM budget is exhausted.
        state_sig = (len(graph.nodes), round(tm, 1), len(_same_target_pairs(graph)))
        if state_sig == prev_state_sig:
            stuck += 1
            if stuck >= 3:
                log.warning("Expansion made no progress for 3 iterations "
                            "(nodes/minutes/pairs unchanged) — stopping to avoid a spin")
                break
        else:
            stuck = 0
        prev_state_sig = state_sig
        log.info(f"Iteration {iteration}: total={tm:.1f}min, shortest={sp:.1f}min, "
                 f"nodes={len(graph.nodes)}, llm_calls={params.llm_calls_used()}")

        edges = rank_edges(graph, highlights, params)
        # Filter to expandable edges with their expansion types
        candidate_edges: list[tuple[NodeId, NodeId, str]] = []
        for from_node, choice in edges:
            to_node = choice.to
            if to_node in graph.nodes[from_node]._non_expandable_edges:
                continue
            etype = choose_expansion_type(graph, from_node, to_node, params)
            candidate_edges.append((from_node, to_node, etype))

        if not candidate_edges:
            log.info("No expandable edges — done")
            break

        # W2: once the minute budget is met, the ONLY remaining job is breaking
        # residual same-target pairs — restrict candidates to pair edges and
        # stop if none are expandable (unbreakable pairs get reported, not looped).
        if total_minutes(graph, params) >= params.total_budget_min:
            pair_nodes = set(_same_target_pairs(graph))
            candidate_edges = [
                (a, b, e) for (a, b, e) in candidate_edges if a in pair_nodes
            ]
            if not candidate_edges:
                log.info("Budget met; remaining pairs unbreakable — done")
                break
            log.info("Budget met; %d same-target pair(s) remain — breaking pairs only",
                     len(pair_nodes))

        # Select non-conflicting batch for parallel generation
        batch = _select_non_conflicting_edges(candidate_edges, max_batch=3)
        log.info(f"  Batch size: {len(batch)} edges: "
                 f"{', '.join(f'{a}→{b}({e})' for a, b, e in batch)}")

        # Generate in parallel; commit each result AS IT COMPLETES so finished
        # excursions are never held hostage by a straggler stuck in retries.
        progressed, had_transient = _parallel_generate_and_commit(
            graph, batch, bible, chapters, highlights, registry, params,
            outline=outline)

        if not progressed:
            if had_transient:
                # All successes failed merge or all were transient — retry
                # with sequential (batch=1) to avoid concurrent API pressure
                log.info("  Parallel batch had transient failures; "
                         "falling back to sequential")
                for from_node, to_node, etype in candidate_edges:
                    if to_node in graph.nodes[from_node]._non_expandable_edges:
                        continue
                    log.info(f"  Sequential retry: {from_node}→{to_node} ({etype})")
                    if expand_edge(graph, from_node, to_node, etype, bible,
                                   chapters, highlights, registry, params):
                        checkpoint(graph)
                        progressed = True
                        break
            if not progressed:
                remaining = [
                    (a, b, e) for a, b, e in candidate_edges
                    if b not in graph.nodes[a]._non_expandable_edges
                ]
                if remaining:
                    log.info("  Batch did not commit; trying next ranked edge(s)")
                    continue
                log.info("No edge expandable — done")
                break

    checkpoint(graph, tag="phase3_done")
    _live_upload(graph, registry, bible, run_dir, project_name, params)

    if params.stop_after == "expansion":
        from .metrics import write_report
        write_report(graph, run_dir)
        log.info("Stopping after expansion (--until expansion); report written")
        return graph

    return _build_phase3_5_onwards(graph, bible, chapters, highlights, registry,
                                   params, project_name, run_dir)


def _live_upload(graph: Graph, registry: Registry, bible: dict, run_dir: str,
                 project_name: str | None, params: Params,
                 status: str = "running") -> None:
    """Milestone re-upload of intermediary state under one stable project id.
    Non-fatal; gated by --live-upload (and disabled by --no-upload)."""
    if params.skip_upload or not params.live_upload:
        return
    try:
        from .upload import upload_to_webapp
        from .web_export import write_web_exports
        paths = write_web_exports(graph, registry, bible, run_dir,
                                  project_name=project_name)
        pid_file = os.path.join(run_dir, "live_project_id.txt")
        pid = None
        if os.path.exists(pid_file):
            with open(pid_file) as _pf:
                pid = _pf.read().strip() or None
        # webapp's projects_status_check allows: draft/uploading/
        # pipeline_running/phase{1,2}_{running,ready}/done — map our generic
        # "running" onto pipeline_running.
        db_status = "pipeline_running" if status == "running" else status
        new_pid = upload_to_webapp(paths["web_app_export"], project_id=pid,
                                   status=db_status)
        with open(pid_file, "w") as fh:
            fh.write(new_pid)
        log.info(f"Live upload ({status}): https://hudongju.net/project/{new_pid}")
    except Exception:
        log.exception("Live upload failed (non-fatal)")


def _prose_cast_context(graph: Graph, registry: Registry) -> dict:
    """Per-node (first_appearing, known) character lists, computed from the
    graph's reader memory (meet-over-paths at convergence). The prose LLM
    cannot infer playthrough history from one node — this is its only source."""
    from .validation import _extract_characters_from_content, compute_node_memories
    memories = compute_node_memories(graph, registry)
    ctx = {}
    for nid, node in graph.nodes.items():
        cast = _extract_characters_from_content(node)
        known = memories[nid].known_characters if nid in memories else set()
        ctx[nid] = (sorted(cast - known), sorted(cast & known))
    return ctx


def _build_phase3_5_onwards(
    graph: Graph, bible: dict, chapters: dict[int, str],
    highlights: list[Highlight], registry: Registry, params: Params,
    project_name: str | None, run_dir: str,
) -> Graph:
    def _canonical_goal_id(goal_id: str, goal_ids: set[str]) -> str | None:
        if goal_id in goal_ids:
            return goal_id
        # Source bible sometimes carries a prose-label alias for the same goal.
        if goal_id == "活下来度过今夜" and "goal.survive" in goal_ids:
            return "goal.survive"
        return None

    """Phase 3.5 → Phase 4 → Phase 4.5 → Final validation → Export."""
    # B1: drop off-vocabulary goal_impacts keys (deterministic; P2.5 refills
    # any impacts emptied here, so drift self-heals into the canonical vocab)
    goal_ids = {g.get("id") for g in (bible or {}).get("protagonist_goals", [])
                if g.get("id")}
    if goal_ids:
        dropped = 0
        for node in graph.nodes.values():
            for c in node.choices:
                normalized: dict[str, int] = {}
                for k, v in list(c.goal_impacts.items()):
                    canon = _canonical_goal_id(k, goal_ids)
                    if not canon:
                        dropped += 1
                        continue
                    try:
                        iv = int(v)
                    except (TypeError, ValueError):
                        continue
                    normalized[canon] = max(-1, min(1, iv))
                if normalized != c.goal_impacts:
                    c.goal_impacts = normalized
        if dropped:
            log.info("Goal-vocab sanitize: dropped %d off-vocabulary impact keys",
                     dropped)

    # P2.5: dramatic-metadata backfill (idempotent; fills only missing fields).
    # Runs here so both fresh builds and resumes pass through it.
    try:
        from .metadata_fill import backfill_dramatic_metadata
        filled = backfill_dramatic_metadata(graph, bible, params)
        if filled:
            checkpoint(graph)
    except Exception:
        log.exception("Metadata backfill failed (non-fatal)")

    if params.first_episode:
        log.info("STRICT first-episode: skeleton pipeline below runs IDENTICALLY to a "
                 "full run (stabilize+expansion already done); only Phase 4/4.5 narrow "
                 "to episode-1 node(s).")

    # === Phase C: Competing-goods choice gate (graph-wide) ===
    # Recast dominated / no-pull / method-question choices into competing goods.
    # Runs in BOTH full and first-episode builds → episode 1 is identical.
    from .validation import choice_quality_defects
    from .llm import recast_competing_goods
    recast_n = 0
    for nid in graph.topo_order():
        node = graph.nodes[nid]
        if node.ending in ("ENDING", "DEAD_END") or len(node.choices) != 2:
            continue
        for attempt in range(2):
            defects = choice_quality_defects(node.choices, node.question)
            if not defects or not params.llm_calls_left():
                break
            log.info("  Phase C: %s choice defects %s — recasting (attempt %d)",
                     nid, [k for k, _ in defects], attempt + 1)
            if not recast_competing_goods(node, defects, params, list(goal_ids)):
                break
            recast_n += 1
    if recast_n:
        checkpoint(graph)
    log.info("  Phase C: %d competing-goods recasts applied (graph-wide)", recast_n)

    # === Phase 3.5: DFS skeleton memory + local consistency check ===
    log.info("=== Phase 3.5: Skeleton semantic check (DFS + local) ===")
    _validate_and_fix_skeleton_dfs_semantics(graph, registry, params, bible=bible)

    # === Phase 4: Prose generation (per-node) ===
    log.info("=== Phase 4: Prose generation ===")
    try:
        topo = graph.topo_order()
    except ValueError:
        _break_cycles(graph)
        topo = graph.topo_order()

    # Episode 1 = root node (prologue → first choice). Aftermaths render at the
    # end of the root's choices, so episode 1 needs only the root's prose.
    ep1_nodes = {graph.root}

    # Resume efficiency: a node whose content already reads as finished prose
    # (meets the D9 length floor AND is no longer just the thin skeleton) was
    # filled on a prior run — skip it so --resume never re-proses completed nodes.
    def _already_prosed(nid: NodeId) -> bool:
        node = graph.nodes[nid]
        if not node.content or node.content == node.skeleton:
            return False
        floor = (max(120, int(node.planned_duration_min * 150))
                 if node.ending == "DEAD_END"
                 else max(420, int(node.planned_duration_min * 220)))
        return node.get_content_text_length() >= floor

    # P5: prose is a pure function of (node, frozen graph context) — render in
    # parallel; results are committed on the main thread as they complete.
    prose_filled = 0
    resumed = [nid for nid in topo if _already_prosed(nid)]
    if resumed:
        log.info("  Phase 4 resume: %d node(s) already have finished prose — skipping",
                 len(resumed))
    if params.first_episode:
        pending = [nid for nid in topo if nid in ep1_nodes and params.llm_calls_left()
                   and not _already_prosed(nid)]
        skipped = [nid for nid in topo if nid not in ep1_nodes]
        log.info("  STRICT first-episode: filling prose for episode-1 node(s) %s; "
                 "SKIPPING prose for %d downstream nodes — this is the ONLY divergence "
                 "from a full run (the root's own prose path is identical).",
                 sorted(ep1_nodes), len(skipped))
    else:
        pending = [nid for nid in topo if params.llm_calls_left()
                   and not _already_prosed(nid)]
    prose_workers = _env_int("HARNESS_PROSE_WORKERS", 3)

    prose_ctx = _prose_cast_context(graph, registry)

    def _prose_one(nid: NodeId):
        node = graph.nodes[nid]
        thin_len = sum(len(el.get("text", "") + el.get("line", ""))
                       for el in node.content if isinstance(el, dict))
        log.info(
            f"  Generating prose for {nid} (kind={node.kind}, ending={node.ending}, "
            f"thin_content={thin_len} chars)"
        )
        first, known = prose_ctx.get(nid, ([], []))
        return fill_prose(node, bible, params, graph=graph,
                          chapters_index=chapters,
                          first_appearing=first, known_characters=known)

    # Drain ALL futures, committing + checkpointing each success as it lands, so a
    # single failed node never discards in-flight prose from the other workers.
    # Raise only after the batch is drained (partial prose is then resumable).
    failed_nids: list[NodeId] = []
    with ThreadPoolExecutor(max_workers=max(1, prose_workers)) as pool:
        futures = {pool.submit(_prose_one, nid): nid for nid in pending}
        for f in as_completed(futures):
            nid = futures[f]
            try:
                content = f.result()
            except Exception as e:  # noqa: BLE001 — log and keep draining
                log.error(f"  Prose generation raised for {nid}: {e}")
                failed_nids.append(nid)
                continue
            if not content:
                log.error(f"  Prose generation failed for {nid} after local retry budget")
                failed_nids.append(nid)
                continue
            graph.nodes[nid].content = content
            prose_filled += 1
            if prose_filled % 3 == 0:
                checkpoint(graph)
    checkpoint(graph)
    if failed_nids:
        raise HarnessError(
            f"Prose generation failed for {len(failed_nids)} node(s): {failed_nids} "
            f"(succeeded for {prose_filled}; rerun with --resume to retry the rest)"
        )

    log.info(f"  Phase 4: prose filled for {prose_filled} nodes "
             f"({prose_workers} workers)")
    _live_upload(graph, registry, bible, run_dir, project_name, params)

    # === Phase 4.5: Per-node semantic validation (DFS in topo order) ===
    log.info("=== Phase 4.5: Per-node semantic validation ===")
    if params.first_episode:
        # Only episode-1 nodes have prose; restrict 4.5 to them. The root is the
        # graph root (no incoming paths) so its DFS reader-memory is empty —
        # 4.5 on the root is self-contained and identical to a full run.
        _ensure_scene_header_first(graph, only_nodes=ep1_nodes)
        compute_guaranteed(graph, registry)
        log.info("  STRICT first-episode: Phase 4.5 on episode-1 node(s) %s only",
                 sorted(ep1_nodes))
        remaining = _validate_and_fix_semantic_topo(graph, registry, bible, params,
                                                    chapters=chapters, only_nodes=ep1_nodes)
        return _finish_first_episode(graph, bible, chapters, registry, params,
                                     run_dir, ep1_nodes, remaining)
    _ensure_all_content(graph)
    _ensure_scene_header_first(graph)
    compute_guaranteed(graph, registry)
    remaining = _validate_and_fix_semantic_topo(graph, registry, bible, params,
                                                chapters=chapters)

    # Auto-fix terminal markers lost during prose regen
    for nid, node in graph.nodes.items():
        if not node.content or not isinstance(node.content, list):
            continue
        if node.ending == "ENDING":
            last = node.content[-1] if node.content else {}
            if not isinstance(last, dict) or "结局：" not in last.get("text", ""):
                node.content.append({"type": "narration", "text": "结局：" + (node.get_summary()[:10] or "结局")})
                log.info(f"  Auto-fixed terminal marker for ENDING node {nid}")
        elif node.ending == "DEAD_END":
            last = node.content[-1] if node.content else {}
            if not isinstance(last, dict) or "BE" not in last.get("text", ""):
                node.content.append({"type": "action", "text": "BE"})
                log.info(f"  Auto-fixed terminal marker for DEAD_END node {nid}")
    checkpoint(graph)

    log.info("=== Final validation ===")
    _ensure_all_content(graph)
    _ensure_scene_header_first(graph)
    compute_guaranteed(graph, registry)
    final_feedback = validate(graph, registry, region=None, params=None)

    # Self-heal prose-length violations (a 4.5 fix can regen prose under the
    # duration floor): targeted re-fill with explicit length feedback, then
    # revalidate, instead of killing the run at the finish line.
    length_violations = [
        v for v in final_feedback.violations
        if v.check == "D9" and "Content text length" in v.problem
    ]
    if length_violations and params.llm_calls_left():
        for v in length_violations:
            node = graph.nodes.get(v.node)
            if node is None:
                continue
            log.info(f"  Final-validation self-heal: re-filling prose for {v.node} ({v.problem})")
            heal_first, heal_known = _prose_cast_context(graph, registry).get(v.node, ([], []))
            content = fill_prose(
                node, bible, params, graph=graph,
                chapters_index=chapters,
                first_appearing=heal_first, known_characters=heal_known,
                violation_feedback=(
                    f"前一版 prose 太短：{v.problem}。在不增加新剧情事实的前提下，"
                    f"用更充分的动作、对白与气氛描写达到长度下限。"
                ),
            )
            if content:
                node.content = content
        checkpoint(graph)
        compute_guaranteed(graph, registry)
        final_feedback = validate(graph, registry, region=None, params=None)

    if not final_feedback.empty():
        det_violations = [v for v in final_feedback.violations if v.check.startswith("D")]
        sem_violations = [v for v in final_feedback.violations if not v.check.startswith("D")]
        if det_violations:
            problems = "; ".join(
                f"{v.check}:{v.node}:{v.problem}" for v in det_violations[:5]
            )
            raise RuntimeError(f"Final graph failed deterministic validation: {problems}")
        if sem_violations:
            log.warning(f"Final graph has {len(sem_violations)} semantic violations (non-blocking):")
            for v in sem_violations[:5]:
                log.warning(f"  [{v.check}] {v.node}: {v.problem}")

    path = write(graph, prose=True)
    log.info(f"Final graph written to {path}")

    # B5: post-prose shortest-playthrough floor — planned estimates governed
    # expansion; finished prose is what players actually experience.
    path_floor_msgs: list[str] = []
    try:
        sp_final = shortest_playthrough(graph, params)
        floor = 0.85 * params.target_playthrough_min
        if sp_final < floor:
            msg = (f"shortest playthrough {sp_final:.1f}min < floor {floor:.1f}min "
                   f"(target {params.target_playthrough_min}) — a player can "
                   f"speedrun to an ending; route an excursion onto the short path")
            log.warning("  [path_floor] %s", msg)
            path_floor_msgs.append(msg)
    except Exception:
        log.exception("Path-floor check failed (non-fatal)")

    # P6 drama lint: IR validators over the converted plan (warning-level)
    drama_sections = None
    try:
        from .ir import drama_report, plan_from_graph
        plan = plan_from_graph(graph, bible, _load_outline(run_dir))
        dr = drama_report(plan)
        if path_floor_msgs:
            dr["path_floor"] = path_floor_msgs
        trig = sum(1 for p in plan.nodes.values()
                   if p.dilemma and p.dilemma.trigger_beat)
        log.info("  Drama lint: %d/%d choice nodes carry trigger_beat",
                 trig, sum(1 for p in plan.nodes.values() if p.dilemma))
        drama_sections = {"drama": dr}
        for section, problems in drama_sections["drama"].items():
            for p in problems[:8]:
                log.warning(f"  [drama/{section}] {p}")
    except Exception:
        log.exception("Drama lint failed (non-fatal)")

    from .metrics import write_report
    rep = write_report(graph, run_dir, extra_sections=drama_sections)
    gate_summary = ", ".join(
        f"{name}={'PASS' if g['pass'] else 'FAIL'}" for name, g in rep["gates"].items()
    )
    log.info(f"Report card written to {run_dir}/report.md ({gate_summary})")

    export_paths = write_web_exports(graph, registry, bible, run_dir,
                                     project_name=project_name)
    log.info(f"Web app export written to {export_paths['web_app_export']}")
    log.info(f"Web outline payload written to {export_paths['web_outline_payload']}")

    # Final step: upload to webapp
    if params.skip_upload:
        log.info("Skipping webapp upload (skip_upload=True)")
        return graph
    log.info("=== Uploading to webapp ===")
    try:
        pid_file = os.path.join(run_dir, "live_project_id.txt")
        live_pid = None
        if os.path.exists(pid_file):
            with open(pid_file) as _pf:
                live_pid = _pf.read().strip() or None
        project_id = upload_to_webapp(export_paths['web_app_export'],
                                      project_id=live_pid, status="done")
        log.info(f"Webapp upload complete! Project ID: {project_id}")
        log.info(f"View at: https://hudongju.net/project/{project_id}")
    except Exception as e:
        log.warning(f"Webapp upload failed (non-fatal): {e}")

    return graph


def _aftermath_overlap(aftermath: list, target: Node) -> float:
    """Bigram Jaccard between an aftermath block and its target node's prose —
    detects the duplicate-scene bug (aftermath replays the next node's event)."""
    import re as _re

    def bigrams(els):
        text = _re.sub(r"\s+", "", "".join(
            (el.get("text", "") or "") + (el.get("line", "") or "")
            for el in els if isinstance(el, dict)))
        return {text[i:i + 2] for i in range(len(text) - 1)}

    a = bigrams(aftermath)
    b = bigrams(target.content or target.skeleton or [])
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _deterministic_prose_checks(node: Node, memory, bible: dict | None = None,
                                graph: Graph | None = None) -> list[Violation]:
    """Free checks computed from graph memory — run before any LLM judge.

    - W4: first-appearing bible characters need a namecard; known ones must not
      get one again.
    - W3: every choice on a non-ending node needs a dramatized aftermath.
    Violations route into the normal prose-regen feedback path."""
    out: list[Violation] = []
    content = [el for el in (node.content or []) if isinstance(el, dict)]
    namecards = {el.get("name", "") for el in content if el.get("type") == "namecard"}

    from .validation import _extract_characters_from_content
    cast = _extract_characters_from_content(node)
    # Enforce namecards only for BIBLE characters: skeleton headers may carry
    # placeholder names (主角/对手) that prose can never sensibly namecard.
    bible_names = {c.get("name", "") for c in (bible or {}).get("characters", [])}
    cast = {c for c in cast if c in bible_names}
    known = memory.known_characters if memory else set()
    for ch in sorted(cast - known):
        if ch and ch not in namecards:
            out.append(Violation(
                node=node.id, check="namecard",
                problem=f"角色「{ch}」在本路径上首次出场，但 prose 缺少 namecard 与引入",
                suggested_fix=f"为「{ch}」添加 namecard 元素并在动作/对白中自然引入",
            ))
    for ch in sorted(namecards & known):
        if ch:
            out.append(Violation(
                node=node.id, check="namecard",
                problem=f"角色「{ch}」观众已认识，但 prose 重复给了 namecard",
                suggested_fix=f"删除「{ch}」的 namecard（保留正常出场）",
            ))

    # 3-5 场 (scene_headers) for every node except DEAD_END — routes into regen.
    if node.ending != "DEAD_END":
        n_scenes = sum(1 for el in content if el.get("type") == "scene_header")
        if n_scenes and (n_scenes < 3 or n_scenes > 5):
            out.append(Violation(
                node=node.id, check="scene_count",
                problem=f"本节点有 {n_scenes} 个场（scene_header），要求 3-5 个",
                suggested_fix=(
                    "拆分或合并场景，使节点含 3-5 个 scene_header，每个是独立的地点/时间切换，"
                    "不得新增剧情事件"
                ),
            ))

    if node.ending == "NONE":
        for c in node.choices:
            tgt = graph.nodes.get(c.to) if graph else None
            if tgt is not None and c.aftermath:
                overlap = _aftermath_overlap(c.aftermath, tgt)
                if overlap > 0.30:
                    out.append(Violation(
                        node=node.id, check="aftermath",
                        problem=(
                            f"选择「{c.label}」的 aftermath 与目标节点「{c.to}」的"
                            f"场景内容重复（相似度 {overlap:.2f}）——事件被演了两遍"
                        ),
                        suggested_fix=(
                            "aftermath 只写选择的即时后果与过渡，停在下一场开场之前；"
                            "不得重复或预演下一场的事件"
                        ),
                    ))
            if len(c.aftermath) < 3:
                out.append(Violation(
                    node=node.id, check="aftermath",
                    problem=(
                        f"选择「{c.label}」缺少戏剧化 aftermath 支线段落"
                        f"（现有 {len(c.aftermath)} 个元素，需 3-6 个）"
                    ),
                    suggested_fix="在 aftermaths 中为该选择输出 3-6 个剧本元素（动作/对白），戏剧化呈现选择后果",
                ))
    return out


def _validate_and_fix_semantic_topo(
    graph: Graph, registry: Registry, bible: dict, params: Params,
    chapters: dict[int, str] | None = None,
    only_nodes: set[NodeId] | None = None,
) -> list[Violation]:
    """Phase 4.5: walk topo order, validate each node with compact memory, fix inline.

    Returns remaining violations after all per-node fix attempts.
    """
    from .llm import fix_summary_violations

    MAX_ATTEMPTS = 10
    topo = graph.topo_order()
    node_memories = compute_node_memories(graph, registry)

    total_violations = 0
    total_fixes = 0
    remaining: list[Violation] = []
    # Recompute reader memory before a node whenever an earlier node's fix mutated
    # the graph, so downstream nodes validate against fresh ancestor context.
    graph_dirty = False

    for nid in topo:
        if only_nodes is not None and nid not in only_nodes:
            continue
        node = graph.nodes[nid]
        if not node.content:
            continue
        if not params.llm_calls_left():
            log.warning("LLM budget exhausted during per-node semantic validation")
            break

        if graph_dirty:
            node_memories = compute_node_memories(graph, registry)
            graph_dirty = False
        memory = node_memories.get(nid)
        if memory is None:
            continue

        prose_regen_count = 0
        s4_fix_count = 0
        semantic_feedback_history: list[str] = []
        node_first, node_known = _prose_cast_context(graph, registry).get(nid, ([], []))

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not params.llm_calls_left():
                break

            # Deterministic pre-checks (free) BEFORE the LLM judge:
            # W4 namecards by computed first-appearance; W3 aftermath presence.
            det_pre = _deterministic_prose_checks(node, memory, bible, graph)
            if det_pre:
                sem_violations = det_pre
            else:
                violations = validate_semantic_node(node, memory, params)
                sem_violations = [v for v in violations if not v.check.startswith("D")]

            if not sem_violations:
                log.info(f"  {nid}: clean" + (f" (attempt {attempt})" if attempt > 1 else ""))
                break

            total_violations += len(sem_violations)
            log.info(f"  {nid}: {len(sem_violations)} violation(s) on attempt {attempt}")
            for v in sem_violations:
                log.info(f"    [{v.check}] {v.problem}")

            # Categorize violations
            s4_violations = [v for v in sem_violations if v.check == "S4"]
            prose_violations = [v for v in sem_violations if v.check != "S4"]

            fixed_something = False

            # Final attempt: escalate to a skeleton-plot rewrite if earlier prose/S4
            # regens didn't clear the violations. Fire whenever the cheaper fixes were
            # tried and exhausted on the last attempt (the prior `>= 10` gate was
            # unreachable — the counters are capped at < 10 everywhere else).
            if attempt == MAX_ATTEMPTS and (prose_regen_count > 0 or s4_fix_count > 0):
                problems = [f"[{v.check}] {v.problem}" for v in sem_violations]
                feedback_text = "\n".join(f"- {p}" for p in problems)
                log.info(f"  {nid}: escalating to summary fix after {prose_regen_count} prose regens")
                fixed = fix_summary_violations(node, graph, feedback_text, params)
                if fixed and fixed != node.get_summary():
                    log.info(f"  {nid}: rewrote skeleton plot")
                    node.skeleton = _rewrite_skeleton_from_fixed_summary(node, fixed)
                    node.content = []
                    # Regen prose from the rewritten skeleton
                    if params.llm_calls_left():
                        node.content = fill_prose(node, bible, params, graph=graph,
                                                  chapters_index=chapters,
                                                  first_appearing=node_first,
                                                  known_characters=node_known)
                        if not node.content:
                            raise HarnessError(
                                f"Prose regeneration failed for {nid} after summary fix"
                            )
                        total_fixes += 1
                        graph_dirty = True
                        checkpoint(graph)
                    continue  # re-validate

            # Fix S4 violations (question/choice mismatch)
            if s4_violations and s4_fix_count < 10 and node.choices:
                problem_text = s4_violations[0].problem
                log.info(f"  {nid}: S4 fix (was: '{node.question}')")
                fix_result = fix_s4_question(node, problem_text, params)
                if fix_result:
                    node.question, new_labels = fix_result
                    for i, c in enumerate(node.choices):
                        if i < len(new_labels):
                            c.label = new_labels[i]
                    s4_fix_count += 1
                    fixed_something = True
                    graph_dirty = True
                    log.info(f"  {nid}: → question='{node.question}', choices={[c.label for c in node.choices]}")

            # Fix prose violations via regen
            if prose_violations and prose_regen_count < 10:
                problems = [f"[{v.check}] {v.problem}" for v in prose_violations]
                semantic_feedback_history.extend(problems)
                feedback_text = "\n".join(
                    f"- {p}" for p in semantic_feedback_history[-10:]
                )
                log.info(f"  {nid}: regenerating prose to fix {len(prose_violations)} violation(s)")
                node.content = fill_prose(
                    node, bible, params,
                    graph=graph,
                    chapters_index=chapters,
                    first_appearing=node_first, known_characters=node_known,
                    violation_feedback=feedback_text,
                )
                if not node.content:
                    raise HarnessError(
                        f"Prose regeneration failed for {nid} after semantic feedback"
                    )
                prose_regen_count += 1
                fixed_something = True
                total_fixes += 1
                graph_dirty = True
                checkpoint(graph)

            if not fixed_something:
                # Nothing we can do, record remaining
                remaining.extend(sem_violations)
                break
        else:
            # Exhausted MAX_ATTEMPTS, re-validate to collect remaining
            if params.llm_calls_left():
                final_v = validate_semantic_node(node, memory, params)
                final_sem = [v for v in final_v if not v.check.startswith("D")]
                if final_sem:
                    remaining.extend(final_sem)
                    log.info(f"  {nid}: {len(final_sem)} violation(s) remaining after {MAX_ATTEMPTS} attempts")

    log.info(f"  Phase 4.5: {total_violations} total violations found, {total_fixes} fixes applied, {len(remaining)} remaining")
    return remaining


def _rewrite_skeleton_from_fixed_summary(node: Node, fixed_summary: str) -> list:
    from .models import _parse_prose_to_elements, make_scene_header
    loc = node.get_scene_location()
    time = node.get_scene_time()
    chars = node.get_scene_characters()
    elements = []
    if loc or time or chars:
        elements.append(make_scene_header(loc, time, list(chars)))
    elements.extend(_parse_prose_to_elements(fixed_summary))
    return elements


def _apply_upstream_fixes(
    graph: Graph,
    registry: Registry,
    upstream_fixes: list[dict],
) -> set[str]:
    """Apply upstream fix suggestions to parent nodes. Returns set of modified node ids."""
    from .models import Effect as FactEntry
    modified = set()
    for fix in upstream_fixes:
        pid = fix.get("node_id")
        if pid not in graph.nodes:
            log.warning("  upstream_fix references unknown node %s, skipping", pid)
            continue
        parent = graph.nodes[pid]
        original = copy.deepcopy(parent)

        for fact_entry in fix.get("produces_to_remove", []):
            fact_id = fact_entry if isinstance(fact_entry, str) else fact_entry.get("fact", fact_entry)
            parent.produces = [e for e in parent.produces if e.fact != fact_id]

        for fact_entry in fix.get("produces_to_add", []):
            fid = fact_entry.get("fact", "")
            fval = fact_entry.get("value", True)
            if fid and fid not in {e.fact for e in parent.produces}:
                parent.produces.append(FactEntry(fact=fid, value=fval))

        if parent.produces != original.produces:
            modified.add(pid)
            log.info("  Applied upstream fix to %s: produces changed", pid)

        summary_patch = fix.get("summary_patch", "")
        if summary_patch and parent.get_summary() != summary_patch:
            # Skeleton is the sole plot source: fold the patched plot back into it.
            parent.skeleton = _rewrite_skeleton_from_fixed_summary(parent, summary_patch)
            parent.content = []
            modified.add(pid)
            log.info("  Applied upstream plot patch to %s (skeleton rewritten)", pid)

    if modified:
        compute_guaranteed(graph, registry)
    return modified


def _build_mini_story(
    graph_bible: dict, chapters: dict[int, str], registry: Registry,
    params: Params, run_dir: str, project_name: str | None,
) -> Graph:
    """Tiny complete interactive unit: 1 root choice → 2 endings (3 nodes).

    The 'simple method': generate directly from the opening chapters with the
    real skeleton/choice prompts (so tuning transfers), then run the per-node
    quality passes (P2.5 → Phase C competing-goods → P3.5 local consistency →
    prose), validate, export, report. ~5-7 LLM calls.
    """
    from .llm import (generate_mini_story, recast_competing_goods)
    from .validation import choice_quality_defects
    bible = graph_bible
    bounds = (min(chapters), max(chapters)) if chapters else (1, 2)
    # Mini stories only need the opening; clamp to the first 2 chapters.
    bounds = (bounds[0], min(bounds[1], bounds[0] + 1))
    log.info("=== MINI-STORY: 3 nodes (1 choice → 2 endings), chapters %s ===", bounds)

    graph, new_decls = generate_mini_story(bible, registry, params,
                                           chapters_index=chapters, chapter_bounds=bounds)
    for decl in new_decls:
        if decl.id not in registry:
            registry[decl.id] = decl
    _backfill_structured_fields(graph)
    checkpoint(graph)

    # P2.5 metadata (title/charges/goal_impacts)
    try:
        from .metadata_fill import backfill_dramatic_metadata
        backfill_dramatic_metadata(graph, bible, params)
    except Exception:
        log.exception("Mini metadata backfill failed (non-fatal)")

    # Phase C: competing-goods gate on the root choice
    goal_ids = {g.get("id") for g in (bible or {}).get("protagonist_goals", []) if g.get("id")}
    root_node = graph.nodes[graph.root]
    for attempt in range(2):
        defects = choice_quality_defects(root_node.choices, root_node.question)
        if not defects or not params.llm_calls_left():
            break
        log.info("  Phase C: root choice defects %s — recasting", [k for k, _ in defects])
        if not recast_competing_goods(root_node, defects, params, list(goal_ids)):
            break

    # P3.5 local + DFS consistency (catches self-contradictions like the 暗格 bug)
    log.info("=== Phase 3.5: consistency check (3 nodes) ===")
    _validate_and_fix_skeleton_dfs_semantics(graph, registry, params, bible=bible)

    # P4 prose on all 3 nodes
    log.info("=== Phase 4: prose (3 nodes) ===")
    compute_guaranteed(graph, registry)
    prose_ctx = _prose_cast_context(graph, registry)
    for nid in graph.topo_order():
        node = graph.nodes[nid]
        first, known = prose_ctx.get(nid, ([], []))
        content = fill_prose(node, bible, params, graph=graph, chapters_index=chapters,
                             first_appearing=first, known_characters=known)
        if not content:
            raise HarnessError(f"Mini prose generation failed for {nid}")
        node.content = content
    _ensure_all_content(graph)
    _ensure_scene_header_first(graph)

    # Terminal markers for endings
    for nid, node in graph.nodes.items():
        if node.ending == "ENDING" and node.content:
            last = node.content[-1]
            if not (isinstance(last, dict) and "结局：" in last.get("text", "")):
                node.content.append({"type": "narration", "text": "结局：" + (node.get_summary()[:10] or "结局")})

    # P4.5 prose-semantic on all 3
    log.info("=== Phase 4.5: prose check (3 nodes) ===")
    compute_guaranteed(graph, registry)
    remaining = _validate_and_fix_semantic_topo(graph, registry, bible, params, chapters=chapters)

    # Final validation + export
    compute_guaranteed(graph, registry)
    final = validate(graph, registry, region=None, params=None)
    det = [v for v in final.violations if v.check.startswith("D")]
    if det:
        log.warning("Mini-story has %d deterministic violations:", len(det))
        for v in det[:8]:
            log.warning("  [%s] %s: %s", v.check, v.node, v.problem)
    path = write(graph, prose=True)
    log.info("Mini-story written to %s", path)

    cq = choice_quality_defects(root_node.choices, root_node.question)
    log.info("CHOICE QUALITY: %s | q=%s | labels=%s", "PASS" if not cq else "FAIL",
             root_node.question, [c.label for c in root_node.choices])

    report = _mini_story_report(graph, remaining)
    rpath = os.path.join(run_dir, "mini_story.md")
    with open(rpath, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("Mini-story report → %s (LLM calls used: %d)", rpath, params.llm_calls_used())
    print(report)

    if not params.skip_upload:
        try:
            _live_upload(graph, registry, bible, run_dir, project_name, params)
        except Exception:
            log.exception("Mini-story upload failed (non-fatal)")
    return graph


def _mini_story_report(graph: Graph, remaining: list) -> str:
    """Readable dump of the 3-node mini story: root choice + both endings."""
    from .validation import choice_quality_defects
    root = graph.nodes[graph.root]
    cq = choice_quality_defects(root.choices, root.question)
    lines = [f"# Mini-story — {len(graph.nodes)} nodes", ""]
    lines.append(f"- **choice quality: {'✅ PASS（竞争性收益）' if not cq else '❌ FAIL'}**")
    for kind, detail in cq:
        lines.append(f"  - [{kind}] {detail}")
    if remaining:
        lines.append("- 语义检查发现:")
        for v in remaining[:8]:
            lines.append(f"  - [{v.check}] {v.node}: {v.problem}")
    lines.append("")

    def _dump(node: Node, head: str):
        lines.append(f"## {head} — {node.id}" + (f"：{node.title}" if node.title else ""))
        if node.question:
            lines.append(f"\n**问题**：{node.question}\n")
        for i, c in enumerate(node.choices, 1):
            lines.append(f"- **选项{i}** {c.label} → {c.to}"
                         + (f"（代价：{c.cost}）" if c.cost else "")
                         + (f" {c.goal_impacts}" if c.goal_impacts else ""))
        lines.append("\n正文：")
        for el in (node.content or []):
            if not isinstance(el, dict):
                continue
            t = el.get("type", "")
            text = (el.get("text") or el.get("line") or "").strip()
            sp = el.get("speaker", "")
            if t == "dialogue" and sp:
                lines.append(f"**{sp}**：{text}")
            elif text:
                lines.append(text)
        lines.append("")

    _dump(root, "开场（选择）")
    for nid, node in graph.nodes.items():
        if node.ending == "ENDING":
            _dump(node, "结局")
    return "\n".join(lines)


def _finish_first_episode(
    graph: Graph, bible: dict, chapters: dict[int, str],
    registry: Registry, params: Params, run_dir: str,
    ep1_nodes: set, remaining: list,
) -> Graph:
    """STRICT first-episode tail: after the FULL skeleton pipeline + episode-1
    prose/4.5, run the same final-validation length self-heal a full run applies
    to these nodes (root-scoped), write first_episode.md, and stop.

    Everything above this (stabilize, expansion incl. root pair-break, P2.5,
    Phase C, P3.5, P4, P4.5) ran identically to a full run — so episode 1 is
    the same as it would be after a complete build.
    """
    # Terminal markers (n/a for the prologue root, but apply for parity).
    for nid in ep1_nodes:
        node = graph.nodes.get(nid)
        if node and node.ending == "ENDING" and node.content:
            last = node.content[-1]
            if not (isinstance(last, dict) and "结局：" in last.get("text", "")):
                node.content.append({"type": "narration", "text": "结局：" + (node.get_summary()[:10] or "结局")})

    # Final-validation length self-heal, scoped to episode-1 nodes — identical to
    # what a full run's final validation does for these same nodes.
    from .budget import estimate_minutes  # noqa: F401  (kept for parity context)
    for nid in ep1_nodes:
        node = graph.nodes.get(nid)
        if node is None or not node.content:
            continue
        from .models import render_content_to_text
        import re as _re
        text_len = len(_re.sub(r"\s+", "", render_content_to_text(node.content)))
        duration = float(getattr(node, "planned_duration_min", 0) or 0)
        min_len = max(420, int(duration * 220))
        if text_len < min_len and params.llm_calls_left():
            log.info("  Final self-heal: %s prose %d < floor %d — re-filling",
                     nid, text_len, min_len)
            hf, hk = _prose_cast_context(graph, registry).get(nid, ([], []))
            content = fill_prose(node, bible, params, graph=graph, chapters_index=chapters,
                                 first_appearing=hf, known_characters=hk,
                                 violation_feedback=(f"前一版 prose 仅 {text_len} 字，需≥{min_len} 字。"
                                                     "不增加新剧情，用更充分的动作/对白/气氛扩写。"))
            if content:
                node.content = content
    checkpoint(graph, tag="first_episode")

    root = graph.root
    node = graph.nodes[root]
    compute_guaranteed(graph, registry)
    memory = compute_node_memories(graph, registry).get(root)
    det = _deterministic_prose_checks(node, memory, bible, graph) if memory else []

    from .validation import choice_quality_defects
    cq = choice_quality_defects(node.choices, node.question)
    log.info("CHOICE QUALITY: %s | q=%s | labels=%s%s",
             "PASS" if not cq else "FAIL", node.question,
             [c.label for c in node.choices],
             "" if not cq else " | " + "; ".join(d for _, d in cq))
    log.info("PARITY: episode-1 node %s processed through stabilize→expansion→P2.5→"
             "PhaseC→P3.5→P4→P4.5→self-heal — identical to a full run for this node. "
             "4.5 residual=%d, det-findings=%d", root, len(remaining or []), len(det))

    report = _first_episode_report(node, (remaining or []) + det)
    path = os.path.join(run_dir, "first_episode.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("STRICT first-episode done → %s (LLM calls used: %d)",
             path, params.llm_calls_used())
    print(report)
    return graph


def _first_episode_report(node: Node, remaining: list) -> str:
    """Human-readable dump of the lab node: question, choices, prose."""
    from .validation import choice_quality_defects
    cq = choice_quality_defects(node.choices, node.question)
    lines = [f"# First-episode lab — {node.id}" +
             (f"：{node.title}" if node.title else ""), ""]
    verdict = "✅ PASS（竞争性收益）" if not cq else "❌ FAIL（被支配/无收获）"
    lines.append(f"- **choice quality: {verdict}**")
    for kind, detail in cq:
        lines.append(f"  - [{kind}] {detail}")
    lines.append(f"- summary: {node.get_summary() or '(none)'}")
    lines.append(f"- tension={node.tension} charge={node.opening_charge}→"
                 f"{node.closing_charge} turning={node.turning_type}")
    lines.append("")
    lines.append(f"## 问题\n\n{node.question or '(none)'}\n")
    lines.append("## 选项\n")
    for i, c in enumerate(node.choices, 1):
        lines.append(f"### {i}. {c.label} → {c.to}")
        if c.cost:
            lines.append(f"- 代价: {c.cost}")
        if c.state_delta:
            lines.append(f"- state_delta: {c.state_delta}")
        if c.goal_impacts:
            lines.append(f"- goal_impacts: {c.goal_impacts}")
        aft = "".join((el.get("text", "") or "") + (el.get("line", "") or "")
                      for el in (c.aftermath or []) if isinstance(el, dict))
        lines.append(f"- aftermath: {len(aft)} chars" +
                     (f" — {aft[:120]}…" if aft else ""))
        lines.append("")
    if remaining:
        lines.append("## 检查发现（lab 模式不自动修复）\n")
        for v in remaining:
            lines.append(f"- [{v.check}] {v.problem}")
        lines.append("")
    lines.append("## 正文\n")
    for el in (node.content or []):
        if not isinstance(el, dict):
            continue
        t = el.get("type", "")
        text = (el.get("text", "") or el.get("line", "") or "").strip()
        speaker = el.get("speaker", "")
        if t == "dialogue" and speaker:
            lines.append(f"**{speaker}**：{text}\n")
        elif text:
            lines.append(f"{text}\n")
    return "\n".join(lines)


def _validate_and_fix_skeleton_dfs_semantics(
    graph: Graph, registry: Registry, params: Params,
    bible: dict | None = None,
    only_nodes: set[NodeId] | None = None,
) -> None:
    """Validate ALL skeleton nodes with DFS reader memory and local consistency.

    This combines the former Phase 3.5 (DFS path-dependency) and Phase 3.6
    (local contract consistency) into a single pass that can fix the current
    node AND propagate fixes upstream to parent nodes when a contradiction
    cannot be resolved locally.

    Checks per node:
    - DFS memory: summary/thin content must not presuppose facts, characters,
      or events not guaranteed on every incoming path (convergence check).
    - Local consistency: unconditional produces must not contradict choice
      resolutions; question/choices must align; summary must establish
      produced facts before the choice point.
    """
    topo = graph.topo_order()
    total_violations = 0
    total_fixes = 0
    total_upstream_fixes = 0
    unresolved_nodes: list[NodeId] = []

    for nid in topo:
        if only_nodes is not None and nid not in only_nodes:
            continue
        node = graph.nodes[nid]
        for attempt in range(1, 11):
            if not params.llm_calls_left():
                log.warning("LLM budget exhausted during skeleton semantic check")
                return

            memory = compute_node_memories(graph, registry).get(nid)
            if memory is None:
                break

            dfs_violations = []
            if memory.is_convergence and memory.parent_count > 1:
                dfs_violations = [
                    v for v in validate_semantic_node(node, memory, params)
                    if not v.check.startswith("D")
                ]

            local_violations = [
                v for v in validate_skeleton_node_semantic(node, graph, params)
                if not v.check.startswith("D")
            ]

            all_violations = dfs_violations + local_violations
            if not all_violations:
                log.info(
                    "  %s: skeleton-semantic clean%s",
                    nid, f" (attempt {attempt})" if attempt > 1 else "",
                )
                break

            total_violations += len(all_violations)
            log.info(
                "  %s: %d violation(s) on attempt %d (dfs=%d, local=%d)",
                nid, len(all_violations), attempt,
                len(dfs_violations), len(local_violations),
            )
            for v in all_violations:
                log.info("    [%s] %s", v.check, v.problem)

            original_node = copy.deepcopy(node)
            originals_upstream = {
                pid: copy.deepcopy(graph.nodes[pid])
                for pid in graph.predecessors(nid)
            }

            fixed, upstream_fixes = fix_skeleton_node_semantics(
                node, graph, all_violations, params,
                allowed_fact_ids=set(registry.keys()),
                memory_context=_memory_context_payload(memory),
                protagonist_goals=[g.get("id") for g in
                                   (bible or {}).get("protagonist_goals", [])],
            )
            if fixed is None:
                raise HarnessError(f"Skeleton semantic fix failed for {nid}")

            graph.nodes[nid] = fixed
            node = fixed

            if upstream_fixes:
                _apply_upstream_fixes(graph, registry, upstream_fixes)
                total_upstream_fixes += len(upstream_fixes)

            compute_guaranteed(graph, registry)
            det = validate_deterministic(
                graph, registry, region=None, require_content=False,
                min_ending_count=params.min_ending_count,
            )
            if det and all(v.check in {"D5", "D7"} for v in det):
                # Fix mechanical deterministic failures inline instead of
                # rolling back — D5 closure and D7 invariant flips are both
                # machine-repairable and otherwise tend to loop.
                graph = _auto_fix(graph, registry, Feedback(violations=det))
                compute_guaranteed(graph, registry)
                det = validate_deterministic(
                    graph, registry, region=None, require_content=False,
                    min_ending_count=params.min_ending_count,
                )
            if det:
                problems = "; ".join(
                    f"{v.check}:{v.node}:{v.problem}" for v in det[:5]
                )
                log.info(
                    "  %s: attempted fix broke deterministic validation; "
                    "rolling back and retrying: %s",
                    nid, problems,
                )
                graph.nodes[nid] = original_node
                node = original_node
                for pid, orig in originals_upstream.items():
                    graph.nodes[pid] = orig
                compute_guaranteed(graph, registry)
                continue

            total_fixes += 1
            checkpoint(graph)
        else:
            # Exhausted the per-node budget. A residual nuance-level skeleton
            # violation is not worth killing a multi-hour run: keep the
            # original node, persist the violation loudly, and continue.
            log.error(
                "  %s: skeleton semantic violation UNRESOLVED after 10 attempts "
                "— persisting as warning and continuing", nid,
            )
            unresolved_nodes.append(nid)

    log.info(
        "  Phase 3.5: %d violations found, %d fixes applied, %d upstream fixes"
        "%s",
        total_violations, total_fixes, total_upstream_fixes,
        f", UNRESOLVED: {unresolved_nodes}" if unresolved_nodes else "",
    )


def _memory_context_payload(memory) -> dict:
    rhs = []
    summaries = memory.ancestor_summaries[-8:]
    beats = memory.ancestor_skeleton_beats[-8:]
    for i, (nid, summary) in enumerate(summaries):
        entry = {"node": nid, "summary": summary}
        if i < len(beats):
            entry["skeleton_beats"] = [bt[:60] for bt in beats[i][1][:8]]
        rhs.append(entry)
    return {
        "reader_has_seen": rhs,
        "established_facts": dict(list(memory.established_facts.items())[-20:]),
        "known_characters": sorted(memory.known_characters)[:30],
        "last_exit_context": memory.last_exit_context,
        "is_convergence": memory.is_convergence,
        "parent_count": memory.parent_count,
        "meaning": (
            "Only these summaries/skeleton beats/facts/characters are guaranteed before this node. "
            "Skeleton beats must not presuppose anything else."
        ),
    }


def _ensure_all_content(graph: Graph) -> None:
    """Final guard: log warnings for blank nodes but never fill in fake content.

    Per AGENTS.md: the harness never authors content. If the LLM didn't write it,
    we leave it blank rather than inserting generic filler.
    """
    blank_count = 0
    for node in graph.nodes.values():
        if not node.content and not node.skeleton and not (node.prose or "").strip():
            blank_count += 1
            log.warning(f"Node {node.id} has no content (ending={node.ending})")
    if blank_count:
        log.warning(f"{blank_count} node(s) have blank content — LLM failed to generate")


def _ensure_scene_header_first(graph: Graph, only_nodes: set | None = None) -> None:
    """Normalize generated content so exported scripts always start with 场/景/时/人."""
    for node in graph.nodes.values():
        if only_nodes is not None and node.id not in only_nodes:
            continue
        if not node.content or not isinstance(node.content, list):
            continue
        if node.content[0].get("type") == "scene_header":
            continue
        header_idx = next(
            (i for i, el in enumerate(node.content)
             if isinstance(el, dict) and el.get("type") == "scene_header"),
            None,
        )
        if header_idx is None:
            continue
        header = node.content.pop(header_idx)
        node.content.insert(0, header)
        log.info("  Moved scene_header to start of %s content", node.id)


def _select_non_conflicting_edges(
    candidate_edges: list[tuple[NodeId, NodeId, str]],
    max_batch: int = 3,
) -> list[tuple[NodeId, NodeId, str]]:
    """Greedily select non-conflicting edges for parallel generation.

    Two edges (A→B) and (C→D) conflict if they share any endpoint.
    Picks from highest-priority (first in list) down.
    """
    batch: list[tuple[NodeId, NodeId, str]] = []
    used_endpoints: set[NodeId] = set()
    for a, b, etype in candidate_edges:
        if len(batch) >= max_batch:
            break
        if a in used_endpoints or b in used_endpoints:
            continue
        batch.append((a, b, etype))
        used_endpoints.add(a)
        used_endpoints.add(b)
    return batch


def _parallel_generate_and_commit(
    graph: Graph,
    batch: list[tuple[NodeId, NodeId, str]],
    bible: dict, chapters: dict[int, str],
    highlights: list[Highlight], registry: Registry, params: Params,
    outline: dict | None = None,
) -> tuple[bool, bool]:
    """Generate subgraphs in parallel and COMMIT each one the moment its
    generation finishes (merge+validate+checkpoint are sequential on the main
    thread; generation threads only read a frozen snapshot).

    Returns (progressed, had_transient)."""
    progressed = False
    had_transient = False
    graph_snapshot = copy.deepcopy(graph)

    def _commit(a_id: NodeId, b_id: NodeId, etype: str, result) -> None:
        nonlocal progressed, had_transient
        # W2: pair-breaking commits are allowed PAST the minute budget — the
        # loop keeps running specifically to break residual same-target pairs,
        # so the budget gate must not drop exactly those commits.
        a_node = graph.nodes.get(a_id)
        a_targets = [c.to for c in a_node.choices] if a_node else []
        is_pair_break = (a_node is not None
                         and a_node.kind in ("prologue", "bottleneck")
                         and len(a_targets) == 2 and a_targets[0] == a_targets[1])
        if (total_minutes(graph, params) >= params.total_budget_min
                and not is_pair_break):
            log.info(
                "  Target total reached (%.1f/%.1fmin); dropping %s→%s",
                total_minutes(graph, params), params.total_budget_min, a_id, b_id,
            )
            # Budget only grows; this non-pair edge will never be wanted again —
            # mark it so it isn't re-ranked and re-generated on a later iteration.
            if a_node is not None:
                a_node._non_expandable_edges.add(b_id)
            return
        if result is _TRANSIENT:
            log.info(f"  [{a_id}→{b_id}] Transient failure, will retry")
            had_transient = True
            return
        if result is None:
            graph.nodes[a_id]._non_expandable_edges.add(b_id)
            return
        subgraph_nodes, new_decls = result
        before_nodes = set(graph.nodes)
        before_edges = {
            (src, c.to, c.label)
            for src, node in graph.nodes.items()
            for c in node.choices
        }
        if _try_merge_validate_repair(
            graph, a_id, b_id, etype, subgraph_nodes, new_decls,
            bible, chapters, highlights, registry, params,
        ):
            log.info(f"  Committed expansion {a_id}→{b_id}: "
                     f"+{len(subgraph_nodes)-2} interior nodes (as-completed)")
            _log_expansion_after(before_nodes, before_edges, graph)
            checkpoint(graph)
            progressed = True
        else:
            graph.nodes[a_id]._non_expandable_edges.add(b_id)

    if len(batch) == 1:
        a, b, etype = batch[0]
        result = _generate_subgraph(graph_snapshot, a, b, etype, bible, chapters,
                                    highlights, registry, params, outline=outline)
        _commit(a, b, etype, result)
        return progressed, had_transient

    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        futures = {}
        for a, b, etype in batch:
            f = pool.submit(_generate_subgraph, graph_snapshot, a, b, etype,
                            bible, chapters, highlights, registry, params,
                            outline)
            futures[f] = (a, b, etype)
        for f in as_completed(futures):
            a, b, etype = futures[f]
            try:
                result = f.result()
            except Exception:
                log.exception(f"  Thread failed for edge {a}→{b}")
                result = _TRANSIENT
            _commit(a, b, etype, result)

    return progressed, had_transient


def _between_nodes(graph: Graph, a_id: NodeId, b_id: NodeId) -> list[NodeId]:
    """Existing nodes strictly between A and B: descendants of A that are also
    ancestors of B. Edges into these can never skip bottleneck B."""
    def reach_from(start: NodeId) -> set[NodeId]:
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            for c in graph.nodes[n].choices:
                if c.to in graph.nodes and c.to not in seen:
                    seen.add(c.to); stack.append(c.to)
        return seen
    desc_a = reach_from(a_id)
    anc_b = {n for n in graph.nodes if b_id in reach_from(n)}
    return sorted((desc_a & anc_b) - {a_id, b_id})


def _sequence_obligations(outline: dict | None, b_node: Node) -> str:
    """Excursion context from the P1 outline: the target bottleneck's sequence
    question, scheduled 爽点, and ledger obligations."""
    if not outline:
        return ""
    seq_id = b_node.sequence
    seq = next((s for s in outline.get("sequences", []) if s.get("id") == seq_id), None)
    if not seq:
        return ""
    import json as _json
    ledger_rows = [e for e in outline.get("ledger", [])
                   if seq_id in (e.get("plant_sequence"), e.get("close_sequence"))]
    return (f"\n## Sequence obligations (sequence {seq_id} — the excursion must serve them)\n"
            f"Sequence question: {seq.get('dramatic_question', '')}\n"
            f"Scheduled 爽点/hooks: {_json.dumps(seq.get('satisfaction_beats', []), ensure_ascii=False)}\n"
            f"Ledger rows touching this sequence: {_json.dumps(ledger_rows, ensure_ascii=False)}\n")


def _generate_subgraph(
    graph: Graph, a_id: NodeId, b_id: NodeId, etype: str,
    bible: dict, chapters: dict[int, str],
    highlights: list[Highlight], registry: Registry, params: Params,
    outline: dict | None = None,
) -> tuple[dict[NodeId, Node], list] | None:
    """Generate a subgraph for edge A→B with fix loop. Thread-safe (reads graph only).

    Returns (subgraph_nodes, new_decls) on success, None on failure.
    """
    a_node = graph.nodes[a_id]
    b_node = graph.nodes[b_id]
    span = (a_node.chapters[0], b_node.chapters[1])
    goal = build_goal(graph, a_id, b_id, registry)

    unplaced = [h for h in highlights
                if span[0] <= h.chapter <= span[1]
                and not any(h.id in n.covers for n in graph.nodes.values())]
    _log_expansion_before(graph, a_id, b_id, span, unplaced)

    # Extract scene context for continuity anchors
    a_context = {
        "exit_context": a_node.exit_context or "",
        "entry_context": a_node.entry_context or "",
        "location": a_node.get_scene_location() or "",
    }
    b_context = {
        "exit_context": b_node.exit_context or "",
        "entry_context": b_node.entry_context or "",
        "location": b_node.get_scene_location() or "",
    }

    # Candidate target menu: B + existing between-nodes (cannot skip B);
    # a new DEAD_END is offered only while the dead-end budget is open.
    between = _between_nodes(graph, a_id, b_id)
    dead_end_count = sum(1 for n in graph.nodes.values() if n.ending == "DEAD_END")
    dead_end_allowed = dead_end_count < params.dead_end_target()

    log.info(f"  [{a_id}→{b_id}] Starting generation ({etype}; "
             f"candidates={len(between)+1}, dead_end_allowed={dead_end_allowed})")
    subgraph_nodes, new_decls = creative_writing(
        a_id, b_id, bible, span, chapters, unplaced, goal, etype, params,
        registry=registry, a_context=a_context, b_context=b_context,
        extra_context=_sequence_obligations(outline, b_node),
        target_candidates=between, dead_end_allowed=dead_end_allowed)

    attempts_used = 0
    structural_fixes = 0
    max_structural = min(params.edge_structural_fix_attempts, params.max_fix_attempts)

    while params.llm_calls_left():
        attempts_used += 1

        _normalize_subgraph_schema(subgraph_nodes)
        # Deterministic save: responses sometimes omit the immutable B endpoint
        # stub — reinsert from the graph instead of burning an LLM repair call.
        if b_id not in subgraph_nodes and b_id in graph.nodes:
            subgraph_nodes[b_id] = copy.deepcopy(graph.nodes[b_id])
        if a_id not in subgraph_nodes and a_id in graph.nodes:
            subgraph_nodes[a_id] = copy.deepcopy(graph.nodes[a_id])
        _normalize_length_extending_splice(subgraph_nodes, graph, a_id, b_id, etype)
        feedback = _validate_expansion_shape(
            subgraph_nodes, a_id, b_id, etype,
            allowed_external=set(between))
        if not feedback.empty():
            log.info(f"  [{a_id}→{b_id}] Shape invalid (attempt {attempts_used}): "
                     f"{len(feedback.violations)} violations")
            _log_feedback(feedback)
            if not subgraph_nodes:
                log.info(f"  [{a_id}→{b_id}] Empty subgraph; giving up")
                return None
            if structural_fixes >= max_structural:
                log.info(f"  [{a_id}→{b_id}] Structural fix budget exhausted")
                return None
            structural_fixes += 1
            subgraph_nodes, new_decls = creative_writing_fix(
                a_id, b_id, bible, span, chapters, unplaced, goal, etype,
                subgraph_nodes, feedback, params,
                a_context=a_context, b_context=b_context,
                registry=registry,
                extra_context=_sequence_obligations(outline, b_node),
                target_candidates=between, dead_end_allowed=dead_end_allowed)
            continue
        else:
            # Shape is valid — return for sequential merge
            log.info(f"  [{a_id}→{b_id}] Generation done (attempt {attempts_used})")
            return (subgraph_nodes, new_decls)

    log.warning(f"  [{a_id}→{b_id}] LLM budget exhausted during generation")
    return None


def _log_expansion_before(
    graph: Graph,
    a_id: NodeId,
    b_id: NodeId,
    span: tuple[int, int],
    unplaced: list[Highlight],
) -> None:
    a_node = graph.nodes[a_id]
    b_node = graph.nodes[b_id]
    top = sorted(unplaced, key=lambda h: -h.weight)[:5]
    if top:
        top_desc = "; ".join(
            f"{h.id}(ch{h.chapter}, w={h.weight:.2f}): {h.gloss}"
            for h in top
        )
    else:
        top_desc = "(none)"
    log.info(
        "  Expansion input: expanding from %s to %s; %s covers chapters %s-%s; "
        "%s covers chapters %s-%s; span chapters %s-%s; top highlights: %s",
        a_id, b_id,
        a_id, a_node.chapters[0], a_node.chapters[1],
        b_id, b_node.chapters[0], b_node.chapters[1],
        span[0], span[1], top_desc,
    )


def _log_expansion_after(
    before_nodes: set[NodeId],
    before_edges: set[tuple[NodeId, NodeId, str]],
    graph: Graph,
) -> None:
    added_nodes = [nid for nid in graph.topo_order() if nid not in before_nodes]
    log.info("  Expansion output: new nodes added:")
    if not added_nodes:
        log.info("    (none)")
    for nid in added_nodes:
        node = graph.nodes[nid]
        highlights = ", ".join(node.covers) if node.covers else "(none)"
        log.info(
            "    %s: chapters %s-%s; highlights: %s",
            nid, node.chapters[0], node.chapters[1], highlights,
        )

    current_edges = {
        (src, c.to, c.label)
        for src, node in graph.nodes.items()
        for c in node.choices
    }
    added_edges = sorted(current_edges - before_edges)
    log.info("  Expansion output: new edges added:")
    if not added_edges:
        log.info("    (none)")
    for src, dst, label in added_edges:
        log.info("    %s => %s (%s)", src, dst, label)


def _try_merge_and_validate(
    graph: Graph, a_id: NodeId, b_id: NodeId, etype: str,
    subgraph_nodes: dict[NodeId, Node], new_decls: list,
    registry: Registry, params: Params,
) -> bool:
    """Try to merge a generated subgraph into the graph. Returns True on success.

    Handles exit contract propagation, ID collision fix, merge, validation,
    and D1 auto-fix. On success, mutates graph and registry in place.
    """
    goal = build_goal(graph, a_id, b_id, registry)
    _propagate_exit_contract(subgraph_nodes, b_id, goal.exitB_contract)
    _autofix_colliding_ids(subgraph_nodes, graph, a_id, b_id)

    ok, feedback = _merge_candidate_once(
        graph, a_id, b_id, etype, subgraph_nodes, new_decls, registry, params
    )
    if ok:
        return True

    if feedback:
        log.info(f"  [{a_id}→{b_id}] Merge validation failed: "
                 f"{len(feedback.violations)} violations")
        _log_feedback(feedback)
    return False


def _try_merge_validate_repair(
    graph: Graph, a_id: NodeId, b_id: NodeId, etype: str,
    subgraph_nodes: dict[NodeId, Node], new_decls: list,
    bible: dict, chapters: dict[int, str], highlights: list[Highlight],
    registry: Registry, params: Params,
) -> bool:
    """Merge, validate, and repair candidate failures before abandoning an edge."""
    a_node = graph.nodes[a_id]
    b_node = graph.nodes[b_id]
    span = (a_node.chapters[0], b_node.chapters[1])
    goal = build_goal(graph, a_id, b_id, registry)
    between = _between_nodes(graph, a_id, b_id)
    dead_end_count = sum(1 for n in graph.nodes.values() if n.ending == "DEAD_END")
    dead_end_allowed = dead_end_count < params.dead_end_target()
    unplaced = [
        h for h in highlights
        if span[0] <= h.chapter <= span[1]
        and not any(h.id in n.covers for n in graph.nodes.values())
    ]
    a_context = {
        "exit_context": a_node.exit_context or "",
        "entry_context": a_node.entry_context or "",
        "location": a_node.get_scene_location() or "",
    }
    b_context = {
        "exit_context": b_node.exit_context or "",
        "entry_context": b_node.entry_context or "",
        "location": b_node.get_scene_location() or "",
    }

    max_repairs = min(params.edge_structural_fix_attempts, params.max_fix_attempts)
    repair_count = 0

    while params.llm_calls_left():
        _clamp_node_chapters(subgraph_nodes, chapters)
        _normalize_subgraph_schema(subgraph_nodes)
        # Deterministic save: responses sometimes omit the immutable B endpoint
        # stub — reinsert from the graph instead of burning an LLM repair call.
        if b_id not in subgraph_nodes and b_id in graph.nodes:
            subgraph_nodes[b_id] = copy.deepcopy(graph.nodes[b_id])
        if a_id not in subgraph_nodes and a_id in graph.nodes:
            subgraph_nodes[a_id] = copy.deepcopy(graph.nodes[a_id])
        _normalize_length_extending_splice(subgraph_nodes, graph, a_id, b_id, etype)
        shape_feedback = _validate_expansion_shape(
            subgraph_nodes, a_id, b_id, etype, allowed_external=set(between))
        if not shape_feedback.empty():
            feedback = shape_feedback
        else:
            _propagate_exit_contract(subgraph_nodes, b_id, goal.exitB_contract)
            _autofix_colliding_ids(subgraph_nodes, graph, a_id, b_id)
            ok, feedback = _merge_candidate_once(
                graph, a_id, b_id, etype, subgraph_nodes, new_decls, registry, params
            )
            if ok:
                return True

        if feedback is None or feedback.empty():
            return False
        log.info(f"  [{a_id}→{b_id}] Candidate failed after merge/shape check "
                 f"({len(feedback.violations)} violations)")
        _log_feedback(feedback)

        if repair_count >= max_repairs:
            log.info(f"  [{a_id}→{b_id}] Merge repair budget exhausted")
            return False
        repair_count += 1

        repair_feedback = _scope_candidate_feedback_to_subgraph(
            feedback, subgraph_nodes, a_id, b_id
        )
        subgraph_nodes, new_decls = creative_writing_fix(
            a_id, b_id, bible, span, chapters, unplaced, goal, etype,
            subgraph_nodes, repair_feedback, params,
            a_context=a_context, b_context=b_context,
            registry=registry, target_candidates=between,
            dead_end_allowed=dead_end_allowed,
        )
        if not subgraph_nodes:
            return False

    log.warning(f"  [{a_id}→{b_id}] LLM budget exhausted during merge repair")
    return False


def _merge_candidate_once(
    graph: Graph, a_id: NodeId, b_id: NodeId, etype: str,
    subgraph_nodes: dict[NodeId, Node], new_decls: list,
    registry: Registry, params: Params,
) -> tuple[bool, Feedback | None]:
    """Attempt one merge/validation pass. Commits graph only on success."""
    trial_registry = copy.deepcopy(registry)
    candidate = merge(
        graph, subgraph_nodes, a_id, b_id, trial_registry, etype, new_decls
    )

    if isinstance(candidate, Reject):
        return False, Feedback(violations=[
            Violation(node=a_id, check="merge", problem=candidate.reason)
        ])

    feedback = _validate_expansion_candidate(
        candidate, trial_registry, subgraph_nodes, b_id, params
    )
    if feedback.empty():
        registry.clear()
        registry.update(trial_registry)
        graph.root = candidate.root
        graph.nodes = candidate.nodes
        return True, feedback

    # Auto-fix D1 violations on interior nodes
    d1_fixed = _autofix_expansion_d1(feedback, subgraph_nodes, a_id, b_id)
    if d1_fixed:
        log.info(f"  [{a_id}→{b_id}] Auto-fixed {d1_fixed} D1 violations")
        trial_registry = copy.deepcopy(registry)
        candidate = merge(
            graph, subgraph_nodes, a_id, b_id, trial_registry, etype, new_decls
        )
        if not isinstance(candidate, Reject):
            feedback = _validate_expansion_candidate(
                candidate, trial_registry, subgraph_nodes, b_id, params
            )
            if feedback.empty():
                registry.clear()
                registry.update(trial_registry)
                graph.root = candidate.root
                graph.nodes = candidate.nodes
                return True, feedback

    return False, feedback


def expand_edge(
    graph: Graph, a_id: NodeId, b_id: NodeId, etype: str,
    bible: dict, chapters: dict[int, str], highlights: list[Highlight],
    registry: Registry, params: Params,
) -> bool:
    """§4 — Try to expand edge A→B. Returns True on success.

    Legacy sequential interface — used by stabilize and single-edge callers.
    For parallel expansion, see _build_phase3 which uses _generate_subgraph
    + _try_merge_and_validate directly.
    """
    result = _generate_subgraph(graph, a_id, b_id, etype, bible, chapters,
                                highlights, registry, params)
    if result is None:
        log.warning(f"  LLM failed edge {a_id}→{b_id}; skipping")
        graph.nodes[a_id]._non_expandable_edges.add(b_id)
        return False

    subgraph_nodes, new_decls = result
    before_nodes = set(graph.nodes)
    before_edges = {
        (src, c.to, c.label)
        for src, node in graph.nodes.items()
        for c in node.choices
    }
    if _try_merge_validate_repair(
        graph, a_id, b_id, etype, subgraph_nodes, new_decls,
        bible, chapters, highlights, registry, params,
    ):
        log.info(f"  Expansion succeeded: +{len(subgraph_nodes)-2} interior nodes")
        _log_expansion_after(before_nodes, before_edges, graph)
        return True

    log.warning(f"  Merge failed for edge {a_id}→{b_id}; skipping")
    graph.nodes[a_id]._non_expandable_edges.add(b_id)
    return False


def _autofix_expansion_d1(
    feedback: Feedback,
    subgraph_nodes: dict[NodeId, Node],
    a_id: NodeId,
    b_id: NodeId,
) -> int:
    """Auto-fix D1 violations on expansion interior nodes.

    D1 = 'requires fact X but guaranteed=False'. For new interior nodes,
    the LLM often puts requires that aren't guaranteed upstream.
    Fix: remove the offending requires entry.
    """
    fixed = 0
    interior_ids = set(subgraph_nodes) - {a_id, b_id}
    for v in feedback.violations:
        if v.check != "D1" or v.node not in interior_ids:
            continue
        node = subgraph_nodes.get(v.node)
        if not node:
            continue
        # Extract fact name from violation problem text
        m = re.search(r"Requires '([^']+)'=", v.problem)
        if not m:
            continue
        fact_name = m.group(1)
        before = len(node.requires)
        node.requires = [r for r in node.requires if r.fact != fact_name]
        if len(node.requires) < before:
            fixed += 1
            log.info(f"    D1 auto-fix: removed requires '{fact_name}' from {v.node}")
    return fixed


def _autofix_colliding_ids(
    subgraph_nodes: dict[NodeId, Node],
    graph: Graph,
    a_id: NodeId,
    b_id: NodeId,
) -> None:
    """Rename interior nodes whose IDs collide with existing graph nodes."""
    collisions = [
        nid for nid in subgraph_nodes
        if nid not in (a_id, b_id) and nid in graph.nodes
    ]
    for old_id in collisions:
        # Generate unique new ID
        base = f"exp_{old_id}"
        new_id = base
        counter = 1
        while new_id in subgraph_nodes or new_id in graph.nodes:
            new_id = f"{base}_{counter}"
            counter += 1

        node = subgraph_nodes.pop(old_id)
        node.id = new_id
        subgraph_nodes[new_id] = node
        log.info(f"    Auto-renamed colliding ID: {old_id} → {new_id}")

        # Update all choice references within the subgraph
        for n in subgraph_nodes.values():
            for c in n.choices:
                if c.to == old_id:
                    c.to = new_id


def _log_feedback(feedback: Feedback, limit: int = 12) -> None:
    for v in feedback.violations[:limit]:
        fix = f" fix={v.suggested_fix}" if v.suggested_fix else ""
        log.info(f"    [{v.check}] {v.node}: {v.problem}{fix}")
    if len(feedback.violations) > limit:
        log.info(f"    ... {len(feedback.violations) - limit} more violation(s)")


def _feedback_is_semantic(feedback: Feedback) -> bool:
    if not feedback.violations:
        return False
    return all(v.check.startswith("S") or v.check == "other" for v in feedback.violations)


def _validate_expansion_candidate(
    candidate: Graph,
    registry: Registry,
    subgraph_nodes: dict[NodeId, Node],
    b_id: NodeId,
    params: Params,
) -> Feedback:
    """Validate a candidate merge — deterministic only, skeleton (no content).

    Semantic (S*) validation on expansion subgraphs consistently triggers
    unfixable repair loops. S* issues are deferred to final validation
    where they're reported as non-blocking warnings.
    require_content=False because prose is filled in Phase 4.
    """
    det = validate_deterministic(candidate, registry, region=None, require_content=False)
    if det:
        # Filter out D9 violations on nodes NOT in the expansion subgraph.
        sub_ids = set(subgraph_nodes)
        filtered = [v for v in det if v.node in sub_ids or not v.check.startswith("D9")]
        if filtered:
            return Feedback(violations=filtered)

    return Feedback(violations=[])


def _scope_candidate_feedback_to_subgraph(
    feedback: Feedback,
    subgraph_nodes: dict[NodeId, Node],
    a_id: NodeId,
    b_id: NodeId,
) -> Feedback:
    """Turn candidate-graph failures into bounded subgraph repair instructions."""
    scoped: list[Violation] = []
    sub_ids = set(subgraph_nodes)
    for v in feedback.violations:
        if v.node in sub_ids:
            scoped.append(v)
            continue
        scoped.append(Violation(
            node=a_id,
            check=v.check,
            severity=v.severity,
            problem=(
                f"Merging this subgraph makes already validated downstream node "
                f"'{v.node}' fail: {v.problem}"
            ),
            suggested_fix=(
                v.suggested_fix
                or f"Fix only the generated subgraph between '{a_id}' and '{b_id}' "
                "so the existing graph remains valid."
            ),
        ))
    return Feedback(violations=scoped)


def _normalize_subgraph_schema(subgraph_nodes: dict[NodeId, Node]) -> None:
    """Deterministically repair local schema drift before validation."""
    for node in subgraph_nodes.values():
        if node.choices and node.ending != "NONE":
            node.ending = "NONE"
        if node.ending == "NONE":
            # Missing questions are visible content. Let validation route them
            # back to the LLM instead of inventing placeholder prose here.
            pass
        else:
            node.choices = []
            node.question = None


def _normalize_length_extending_splice(
    subgraph_nodes: dict[NodeId, Node],
    graph: Graph,
    a_id: NodeId,
    b_id: NodeId,
    etype: str,
) -> None:
    """Normalize the non-story wrapper for a LENGTH_EXTENDING splice."""
    if etype != "LENGTH_EXTENDING" or a_id not in subgraph_nodes:
        return

    a_node = subgraph_nodes[a_id]
    if len(a_node.choices) > 1:
        # For LENGTH_EXTENDING, pick the single best replacement choice for A.
        # Priority: scene node (can reach B) > any scene > any non-B in subgraph.
        all_candidates = [
            c for c in a_node.choices
            if c.to != b_id and c.to in subgraph_nodes
        ]
        scene_candidates = [
            c for c in all_candidates
            if subgraph_nodes.get(c.to) and subgraph_nodes[c.to].ending == "NONE"
        ]
        # Best: a scene node that can reach B through the subgraph
        reachable_scenes = [
            c for c in scene_candidates
            if _can_reach_within(subgraph_nodes, c.to, b_id)
        ]
        if reachable_scenes:
            a_node.choices = [reachable_scenes[0]]
        elif scene_candidates:
            a_node.choices = [scene_candidates[0]]
        elif all_candidates:
            a_node.choices = [all_candidates[0]]
        else:
            a_node.choices = [a_node.choices[0]]

    reachable = _reachable_within(subgraph_nodes, a_id)
    for nid in list(subgraph_nodes):
        if nid not in (a_id, b_id) and nid not in reachable:
            del subgraph_nodes[nid]



# _fallback_expansion REMOVED per AGENTS.md:
# The harness never generates story content. If the LLM fails, we skip the edge.


def _validate_expansion_shape(
    subgraph_nodes: dict[NodeId, Node], a_id: NodeId, b_id: NodeId, etype: str,
    allowed_external: set[NodeId] | None = None,
) -> Feedback:
    """Reject empty/no-op expansions before merge can treat them as success."""
    violations: list[Violation] = []
    if a_id not in subgraph_nodes:
        violations.append(Violation(
            node=a_id, check="shape",
            problem=f"Expansion subgraph is missing endpoint A '{a_id}'",
            suggested_fix=f"Include node '{a_id}' with choices into the new interior",
        ))
    if b_id not in subgraph_nodes:
        violations.append(Violation(
            node=b_id, check="shape",
            problem=f"Expansion subgraph is missing endpoint B '{b_id}'",
            suggested_fix=f"Include node '{b_id}' as the exit endpoint",
        ))

    interior = [nid for nid in subgraph_nodes if nid not in (a_id, b_id)]
    if not interior:
        violations.append(Violation(
            node=a_id, check="shape",
            problem="Expansion subgraph has no interior nodes; this would be a no-op",
            suggested_fix="Add at least one new scene node between A and B",
        ))
    interior_dead_ends = [
        nid for nid in interior if subgraph_nodes[nid].ending == "DEAD_END"
    ]
    if len(interior_dead_ends) > 1:
        violations.append(Violation(
            node=a_id, check="shape",
            problem=(
                f"Expansion contains {len(interior_dead_ends)} DEAD_END nodes; max is 1. "
                "Prefer the reconverging shape (both interior choices to B with "
                "different state_delta)"
            ),
            suggested_fix="Keep at most one DEAD_END; route the other choice back to B",
        ))
    elif a_id in subgraph_nodes and b_id in subgraph_nodes:
        if not _can_reach_within(subgraph_nodes, a_id, b_id):
            violations.append(Violation(
                node=a_id, check="shape",
                problem=f"Expansion subgraph does not preserve a route from '{a_id}' to '{b_id}'",
                suggested_fix=f"Connect A through the new interior node(s) back to '{b_id}'",
            ))
        for nid in interior:
            node = subgraph_nodes[nid]
            if not _can_reach_within(subgraph_nodes, a_id, nid):
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=f"Interior node '{nid}' is not reachable from endpoint A '{a_id}'",
                    suggested_fix=f"Connect '{a_id}' to '{nid}', or remove unreachable node '{nid}'",
                ))
            reaches_external = any(
                c.to in (allowed_external or set()) for c in node.choices
            )
            if (node.ending == "NONE" and not reaches_external
                    and not _can_reach_within(subgraph_nodes, nid, b_id)):
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=f"Interior node '{nid}' cannot reach endpoint B '{b_id}'",
                    suggested_fix=f"Add a choice path from '{nid}' to '{b_id}'",
                ))

    for nid, node in subgraph_nodes.items():
        if nid == b_id:
            continue
        for choice in node.choices:
            if (choice.to and choice.to not in subgraph_nodes
                    and choice.to not in (allowed_external or set())):
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=f"Choice '{choice.label}' points to '{choice.to}' which is not B, an interior node, or a listed candidate",
                    suggested_fix="Choices must target B, this subgraph's interiors, or the provided candidate list",
                ))
        if nid == a_id and etype == "LENGTH_EXTENDING":
            if len(node.choices) != 1:
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=(
                        f"LENGTH_EXTENDING endpoint A '{nid}' has {len(node.choices)} "
                        "replacement choices; must have exactly 1"
                    ),
                    suggested_fix=(
                        f"Give endpoint A '{nid}' exactly one replacement choice to "
                        f"a new interior node; the harness preserves its sibling choice"
                    ),
                ))
            elif node.choices[0].to == b_id:
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=f"LENGTH_EXTENDING endpoint A '{nid}' still points directly to B '{b_id}'",
                    suggested_fix="Point A's replacement choice to the new interior node",
                ))
            continue

        if node.ending == "NONE":
            if len(node.choices) != 2:
                violations.append(Violation(
                    node=nid, check="shape",
                    problem=(
                        f"Non-terminal expansion node '{nid}' has {len(node.choices)} choices; "
                        "must have exactly 2"
                    ),
                    suggested_fix="Give every non-terminal expansion node exactly 2 choices",
                ))
            targets = [c.to for c in node.choices]
            if len(targets) != len(set(targets)):
                delta_keys = [c.delta_key() for c in node.choices]
                if len(delta_keys) != len(set(delta_keys)):
                    violations.append(Violation(
                        node=nid, check="shape",
                        problem=(
                            f"Expansion node '{nid}' has multiple choices to the same "
                            "target with identical state_delta"
                        ),
                        suggested_fix=(
                            "Point the choices at different targets, or give each a "
                            "different state_delta"
                        ),
                    ))
        elif node.choices:
            violations.append(Violation(
                node=nid, check="shape",
                problem=f"Terminal expansion node '{nid}' has outgoing choices",
                suggested_fix="ENDING/DEAD_END nodes must have 0 choices",
            ))

    return Feedback(violations=violations)



# _pad_subgraph_content REMOVED per AGENTS.md:
# The harness never pads content. LLM output is used as-is.


def _can_reach_within(subgraph_nodes: dict[NodeId, Node], start: NodeId, target: NodeId) -> bool:
    seen: set[NodeId] = set()
    stack = [start]
    while stack:
        nid = stack.pop()
        if nid == target:
            return True
        if nid in seen or nid not in subgraph_nodes:
            continue
        seen.add(nid)
        stack.extend(c.to for c in subgraph_nodes[nid].choices if c.to in subgraph_nodes)
    return False


def _reachable_within(subgraph_nodes: dict[NodeId, Node], start: NodeId) -> set[NodeId]:
    seen: set[NodeId] = set()
    stack = [start]
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in subgraph_nodes:
            continue
        seen.add(nid)
        stack.extend(c.to for c in subgraph_nodes[nid].choices if c.to in subgraph_nodes)
    return seen


def _propagate_exit_contract(
    subgraph_nodes: dict[NodeId, Node],
    b_id: NodeId,
    requirements: list,
) -> None:
    """Make generated predecessors satisfy B.requires on every new route."""
    from .models import Effect

    if not requirements:
        return

    for nid, node in subgraph_nodes.items():
        if nid == b_id:
            continue
        if not any(c.to == b_id for c in node.choices):
            continue
        for req in requirements:
            if not any(e.fact == req.fact for e in node.produces):
                node.produces.append(Effect(fact=req.fact, value=req.value))


def stabilize_cornerstone(
    graph: Graph,
    registry: Registry,
    params: Params,
    bible: dict,
    chapters: dict[int, str],
    highlights: list[Highlight],
) -> Graph:
    """Phase 2 stabilize: fix deterministic violations only (skeleton, no content).

    Semantic (S*) violations are deferred to expansion/final — fixing them on a
    small cornerstone graph wastes LLM calls and can actually break structure.
    require_content=False because prose is filled in Phase 4.
    """
    from .validation import validate_deterministic, validate_trunk_shape

    attempt = 0
    max_attempts = params.cornerstone_fix_attempts
    while params.llm_calls_left() and attempt < max_attempts:
        attempt += 1
        # Break cycles before computing guaranteed
        try:
            graph.topo_order()
        except ValueError:
            log.info("  Breaking cycles in graph")
            _break_cycles(graph)

        compute_guaranteed(graph, registry)
        det = validate_deterministic(graph, registry, region=None, require_content=False,
                                      min_ending_count=params.min_ending_count)
        det.extend(validate_trunk_shape(graph, params.min_ending_count))

        if not det:
            log.info(f"  Cornerstone deterministic-clean after {attempt} rounds")
            return graph

        fb = Feedback(violations=det)
        log.info(f"  Cornerstone stabilize round {attempt}: {len(det)} D-violations")
        _log_feedback(fb)

        # Try auto-fix first
        graph = _auto_fix(graph, registry, fb)

        # Recheck after auto-fix
        try:
            graph.topo_order()
        except ValueError:
            _break_cycles(graph)
        compute_guaranteed(graph, registry)
        det_after = validate_deterministic(graph, registry, region=None, require_content=False,
                                           min_ending_count=params.min_ending_count)
        det_after.extend(validate_trunk_shape(graph, params.min_ending_count))

        if not det_after:
            log.info(f"  Cornerstone deterministic-clean after {attempt} rounds (auto-fix)")
            return graph

        # Auto-fix wasn't enough — call LLM to fix remaining D-violations
        if params.llm_calls_left():
            fb_after = Feedback(violations=det_after)
            log.info(f"  Auto-fix insufficient, calling LLM fix ({len(det_after)} remaining)")
            log.info(f"  Full-graph LLM repair targets:")
            for v in det_after:
                log.info(f"    [{v.check}] {v.node}: {v.problem}")
            graph = _llm_fix_graph(
                graph, registry, fb_after, params, bible, chapters, highlights
            )
            # Strip content from all nodes — skeleton phase, prose comes in Phase 4
            for node in graph.nodes.values():
                node.content = []

    # Final deterministic check
    try:
        graph.topo_order()
    except ValueError:
        _break_cycles(graph)
    compute_guaranteed(graph, registry)
    det_final = validate_deterministic(graph, registry, region=None, require_content=False,
                                        min_ending_count=params.min_ending_count)
    det_final.extend(validate_trunk_shape(graph, params.min_ending_count))
    if not det_final:
        log.info(f"  Cornerstone deterministic-clean after {attempt} rounds (final)")
        return graph

    problems = "; ".join(f"{v.check}:{v.node}:{v.problem}" for v in det_final[:5])
    raise HarnessError(f"Cornerstone failed deterministic validation after {attempt} rounds: {problems}")


def stabilize(
    graph: Graph,
    registry: Registry,
    params: Params,
    bible: dict,
    chapters: dict[int, str],
    highlights: list[Highlight],
) -> Graph:
    """Full-graph stabilize: validate-and-fix loop.

    Runs up to max_fix_attempts rounds. Each round tries auto-fix first,
    then LLM fix if violations remain.
    """
    for attempt in range(params.final_fix_attempts):
        # Break cycles before computing guaranteed
        try:
            graph.topo_order()
        except ValueError:
            log.info("  Breaking cycles in graph")
            _break_cycles(graph)

        compute_guaranteed(graph, registry)
        fb = validate(graph, registry, region=None, params=params)

        if fb.empty():
            log.info(f"  Stabilized after {attempt} fix rounds")
            return graph

        log.info(f"  Stabilize attempt {attempt+1}: {len(fb.violations)} violations")
        _log_feedback(fb)

        # Auto-fix common deterministic issues
        graph = _auto_fix(graph, registry, fb)

        # Recheck after auto-fix
        try:
            graph.topo_order()
        except ValueError:
            _break_cycles(graph)
        compute_guaranteed(graph, registry)
        fb_after = validate(graph, registry, region=None, params=params)

        if fb_after.empty():
            log.info(f"  Stabilized after {attempt+1} fix rounds (auto-fix)")
            return graph

        # Auto-fix wasn't enough — call LLM if budget allows
        if params.llm_calls_left() and len(fb_after.violations) > 0:
            log.info(f"  Auto-fix insufficient, calling LLM fix ({len(fb_after.violations)} remaining)")
            graph = _llm_fix_graph(
                graph, registry, fb_after, params, bible, chapters, highlights
            )

    log.warning(f"Could not fully stabilize after {params.final_fix_attempts} attempts")
    return graph


def _llm_fix_graph(
    graph: Graph,
    registry: Registry,
    feedback: Feedback,
    params: Params,
    bible: dict,
    chapters: dict[int, str],
    highlights: list[Highlight],
) -> Graph:
    """Use an LLM to repair exact full-graph validation failures."""
    if not feedback.violations:
        return graph

    log.info("  Full-graph LLM repair targets:")
    for v in feedback.violations[:10]:
        log.info(f"    [{v.check}] {v.node}: {v.problem}")

    try:
        fixed_graph, new_decls = creative_graph_fix(
            graph, bible, chapters, highlights, feedback, params
        )
        for decl in new_decls:
            if decl.id not in registry:
                registry[decl.id] = decl
        return fixed_graph
    except Exception as e:
        log.warning(f"  LLM fix failed: {e}")

    return graph


def _auto_fix(graph: Graph, registry: Registry, feedback: Feedback) -> Graph:
    """Attempt automatic fixes for common deterministic violations."""
    from .models import VARIES, Choice, Effect, FactDecl

    for v in feedback.violations:
        node = graph.nodes.get(v.node)
        if not node:
            continue

        if v.check == "D9":
            if "identical state_delta" in v.problem:
                # Don't auto-collapse a flavor pair into a dead end; the LLM
                # should differentiate the two choices' state_delta instead.
                continue
            structural_problem = (
                "choices" in v.problem
                or "same target" in v.problem
                or "should have no choices" in v.problem
            )
            if structural_problem and node.ending == "NONE":
                _repair_binary_choices(graph, node.id)
            elif structural_problem:
                node.choices = []
                node.question = None

        elif v.check == "D1":
            # Do not silently satisfy prerequisites by adding upstream facts.
            # A bad requires entry is often a local prose/modeling bug; let the
            # LLM remove it, introduce the element locally, or establish it with
            # source-grounded prose where that is genuinely required.
            continue

        elif v.check == "D5":
            # Fact not in registry. The cornerstone LLM should have declared
            # it in new_facts. As a last-resort fallback, auto-register it
            # so stabilization can progress.
            import re
            m = re.search(r"Fact '([^']+)' not in registry", v.problem)
            if m:
                fid = m.group(1)
                if fid not in registry:
                    if fid.startswith("player."):
                        kind = "event"
                    elif fid.startswith("char."):
                        kind = "disposition"
                    elif fid.startswith("world."):
                        kind = "knowledge"
                    else:
                        kind = "event"
                    registry[fid] = FactDecl(
                        id=fid, kind=kind, gloss=fid, initial=False,
                    )
                    log.warning(f"    D5 fallback: auto-registered undeclared fact '{fid}'")

        elif v.check == "D6":
            # Cycle detected — remove back-edges
            _break_cycles(graph)

        elif v.check == "D10":
            _prune_unreachable(graph)

        elif v.check == "D7":
            # Flips invariant — restore the invariant value if possible.
            import re
            m = re.search(r"Flips invariant fact '([^']+)'", v.problem)
            if m:
                fid = m.group(1)
                if fid in registry:
                    target = registry[fid].initial
                    changed = False
                    for e in node.produces:
                        if e.fact == fid:
                            e.value = target
                            changed = True
                    for c in node.choices:
                        for e in c.state_delta:
                            if e.fact == fid:
                                e.value = target
                                changed = True
                    if changed:
                        log.info(f"    Auto-restored invariant fact: {fid} on {node.id}")
                    else:
                        node.produces = [e for e in node.produces if e.fact != fid]
                        log.info(f"    Auto-removed invariant flip: {fid} from {node.id}")

    return graph


def _prune_unreachable(graph: Graph) -> None:
    """Remove nodes that are not reachable from the graph root."""
    reachable: set[NodeId] = set()
    stack = [graph.root]
    while stack:
        nid = stack.pop()
        if nid in reachable or nid not in graph.nodes:
            continue
        reachable.add(nid)
        stack.extend(c.to for c in graph.nodes[nid].choices)
    for nid in list(graph.nodes):
        if nid not in reachable:
            del graph.nodes[nid]


def _repair_binary_choices(graph: Graph, node_id: NodeId) -> None:
    """Best-effort deterministic repair for the strict binary-choice contract."""
    from .models import Choice, Node

    node = graph.nodes[node_id]
    if node.ending != "NONE":
        node.choices = []
        node.question = None
        return

    if not node.choices:
        node.ending = "DEAD_END"
        node.question = None
        node.choices = []
        return

    all_terminal = bool(node.choices) and all(
        c.to in graph.nodes and graph.nodes[c.to].ending != "NONE"
        for c in node.choices
    )
    max_choices = 3 if all_terminal else 2
    repaired: list[Choice] = []
    seen: set[tuple] = set()
    for choice in node.choices:
        key = (choice.to, choice.delta_key())
        if choice.to in graph.nodes and key not in seen:
            repaired.append(choice)
            seen.add(key)
        if len(repaired) == max_choices:
            break

    if len(repaired) < 2:
        de_id = f"{node_id}_auto_deadend"
        i = 1
        while de_id in graph.nodes:
            i += 1
            de_id = f"{node_id}_auto_deadend_{i}"
        graph.nodes[de_id] = Node(
            id=de_id,
            kind="ending",
            chapters=node.chapters,
            ending="DEAD_END",
            planned_duration_min=1.0,
            entry_context=node.exit_context or node.entry_context,
        )
        repaired.append(Choice(
            label=node.choices[0].label if node.choices else "继续",
            to=de_id,
            resolution=[],
        ))

    node.choices = repaired[:max_choices]


def _break_cycles(graph: Graph) -> None:
    """Remove back-edges to break cycles in the graph."""
    # BFS from root to assign depth
    depth: dict[str, int] = {}
    queue = [graph.root]
    depth[graph.root] = 0
    while queue:
        nid = queue.pop(0)
        for c in graph.nodes[nid].choices:
            if c.to in graph.nodes and c.to not in depth:
                depth[c.to] = depth[nid] + 1
                queue.append(c.to)

    # Remove any choice that points to a node at equal or lower depth (back-edge)
    for nid, node in graph.nodes.items():
        if nid not in depth:
            continue
        node.choices = [
            c for c in node.choices
            if c.to not in depth or depth[c.to] > depth[nid]
        ]
