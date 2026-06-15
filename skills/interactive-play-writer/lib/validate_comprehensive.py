"""Comprehensive validation orchestrator: IO checks + LLM judge.

Combines deterministic validation (validate_spine.py) with semantic
LLM judge checks (llm_judge.py) into a unified report conforming to
validation_report.schema.json.

This module does NOT make LLM calls itself — it builds the prompts
and expects the caller to execute them and feed back responses.
For fully autonomous validation, use the /interactive-play-writer-validate
skill which handles the LLM calls.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

try:
    from .data_model import SpineState
    from .dfs_expander import (
        compute_guaranteed_state,
        compute_varying_state,
        get_expansion_prompt_context,
        lookup_chapter_excerpts,
    )
    from .llm_judge import (
        S2_QUESTIONS,
        S3_QUESTIONS,
        JudgeReport,
        build_judge_prompt,
        build_step2_judge_context,
        build_step3_judge_context,
        filter_questions_for_node,
    )
except ImportError:
    from data_model import SpineState  # type: ignore[no-redef]
    from dfs_expander import (  # type: ignore[no-redef]
        compute_guaranteed_state,
        compute_varying_state,
        get_expansion_prompt_context,
        lookup_chapter_excerpts,
    )
    from llm_judge import (  # type: ignore[no-redef]
        S2_QUESTIONS,
        S3_QUESTIONS,
        JudgeReport,
        build_judge_prompt,
        build_step2_judge_context,
        build_step3_judge_context,
        filter_questions_for_node,
    )


def build_validation_prompts(
    state: SpineState,
    step: str | None = None,
) -> list[dict[str, Any]]:
    """Build LLM judge prompts for all nodes. Returns list of prompt tasks.

    Each task dict contains:
      - node_id: str
      - prompt: str (the LLM judge prompt text)
      - questions: list[JudgeQuestion] (for parsing the response)
      - step: "step-2" or "step-3"

    The caller executes these prompts (via Task agents or direct LLM calls)
    and feeds responses to parse_judge_responses().
    """
    step = step or state.step
    spine = state.spine
    registry = state.registry
    bible = state.bible

    bible_compact = {
        "protagonist": {
            "name": bible.protagonist.get("name", ""),
            "role": bible.protagonist.get("role", ""),
        },
        "characters": [
            {"name": c.get("name", ""), "role": c.get("role", "")}
            for c in bible.characters
        ],
        "world": bible.world,
        "canon_facts": bible.canon_facts,
    }

    tasks: list[dict[str, Any]] = []

    if step in ("step-2", "step-3", "step-4"):
        questions_pool = S2_QUESTIONS if step == "step-2" else S3_QUESTIONS

        for node in spine.nodes:
            questions = filter_questions_for_node(questions_pool, node.kind)
            if not questions:
                continue

            guaranteed = compute_guaranteed_state(spine, registry, node.id)
            varying = compute_varying_state(spine, registry, node.id)

            if step == "step-2":
                # Build context from the node's expansion data
                ctx = {
                    "parent_beats": node.beats,
                    "parent_exit_context": node.exit_context,
                    "choice_question": node.choice_question,
                    "nodes": [],
                    "edges": [
                        {"id": e.id, "src": e.src, "dst": e.dst,
                         "label": e.label, "resolution": e.resolution,
                         "effects": [asdict(eff) for eff in e.effects]}
                        for e in spine.edges if e.src == node.id
                    ],
                    "guaranteed_state": guaranteed,
                    "varying_state": varying,
                    "bible": bible_compact,
                    "accumulated_state": guaranteed,
                    "next_bottleneck": None,
                    "path_content": [],
                }
            else:
                # step-3 or step-4: validate scripts
                script = state.scripts.get(node.id, "")
                if not script:
                    continue

                outgoing_edges = [
                    {"id": e.id, "src": e.src, "dst": e.dst,
                     "label": e.label, "resolution": e.resolution}
                    for e in spine.edges if e.src == node.id
                ]

                # Get parent scripts for continuity check
                parent_ids = spine.get_predecessors(node.id)
                parent_scripts = {
                    pid: state.scripts[pid]
                    for pid in parent_ids
                    if pid in state.scripts
                }

                chapter_excerpts = lookup_chapter_excerpts(
                    state.chapter_index, node.chapter_range,
                )

                ctx = build_step3_judge_context(
                    script=script,
                    node={"id": node.id, "kind": node.kind, "beats": node.beats,
                          "entry_context": node.entry_context,
                          "exit_context": node.exit_context,
                          "choice_question": node.choice_question},
                    edges=outgoing_edges,
                    bible=bible_compact,
                    guaranteed_state=guaranteed,
                    varying_state=varying,
                    parent_scripts=parent_scripts if parent_scripts else None,
                    chapter_excerpts=chapter_excerpts if chapter_excerpts else None,
                )

            prompt = build_judge_prompt(questions, ctx)
            tasks.append({
                "node_id": node.id,
                "prompt": prompt,
                "questions": questions,
                "step": step if step != "step-4" else "step-3",
            })

    return tasks


def build_report(
    state: SpineState,
    io_result: dict[str, Any] | None,
    llm_reports: dict[str, JudgeReport],
    step: str | None = None,
) -> dict[str, Any]:
    """Merge IO validation and LLM judge reports into a unified report.

    Args:
        state: The SpineState being validated
        io_result: Result from validate_spine() — {ok, errors, warnings, advisory}
        llm_reports: Dict of node_id → JudgeReport from LLM judge
        step: Override step detection

    Returns:
        Report dict conforming to validation_report.schema.json
    """
    step = step or state.step

    # IO checks
    io_errors = []
    io_warnings = []
    io_advisory = []

    if io_result:
        for cat, msg in io_result.get("errors", []):
            io_errors.append({"category": cat, "message": msg})
        for cat, msg in io_result.get("warnings", []):
            io_warnings.append({"category": cat, "message": msg})
        for cat, msg in io_result.get("advisory", []):
            io_advisory.append({"category": cat, "message": msg})

    # LLM checks
    per_node: dict[str, Any] = {}
    total_hard = 0
    total_soft = 0

    for node_id, report in llm_reports.items():
        per_node[node_id] = {
            "verdicts": [asdict(v) for v in report.verdicts],
            "hard_fails": report.hard_fails,
            "soft_fails": report.soft_fails,
        }
        total_hard += len(report.hard_fails)
        total_soft += len(report.soft_fails)

    # Overall result
    has_io_errors = len(io_errors) > 0
    has_hard_fails = total_hard > 0

    if has_io_errors or has_hard_fails:
        overall = "FAIL"
    elif total_soft > 0 or len(io_warnings) > 0:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "step": step if step != "step-4" else "step-3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_result": overall,
        "io_checks": {
            "errors": io_errors,
            "warnings": io_warnings,
            "advisory": io_advisory,
        },
        "llm_checks": {
            "per_node": per_node,
        },
        "summary": {
            "total_nodes_checked": len(llm_reports),
            "hard_fails": total_hard,
            "soft_fails": total_soft,
            "io_errors": len(io_errors),
        },
    }


def format_report_md(report: dict[str, Any]) -> str:
    """Format a validation report as human-readable markdown."""
    lines = [
        f"# Validation Report — {report['step']}",
        f"",
        f"**Result**: {report['overall_result']}",
        f"**Timestamp**: {report['timestamp']}",
        f"",
    ]

    summary = report["summary"]
    lines.append("## Summary")
    lines.append(f"- Nodes checked: {summary['total_nodes_checked']}")
    lines.append(f"- IO errors: {summary['io_errors']}")
    lines.append(f"- Hard fails (LLM): {summary['hard_fails']}")
    lines.append(f"- Soft fails (LLM): {summary['soft_fails']}")
    lines.append("")

    # IO errors
    io = report["io_checks"]
    if io["errors"]:
        lines.append("## IO Errors (blocking)")
        for e in io["errors"]:
            node_tag = f" [{e['node_id']}]" if e.get("node_id") else ""
            lines.append(f"- [{e['category']}]{node_tag} {e['message']}")
        lines.append("")

    if io["warnings"]:
        lines.append("## IO Warnings")
        for w in io["warnings"]:
            node_tag = f" [{w['node_id']}]" if w.get("node_id") else ""
            lines.append(f"- [{w['category']}]{node_tag} {w['message']}")
        lines.append("")

    # LLM checks per node
    per_node = report["llm_checks"]["per_node"]
    if per_node:
        lines.append("## LLM Judge Results")
        for node_id, node_report in sorted(per_node.items()):
            hard = node_report["hard_fails"]
            soft = node_report["soft_fails"]
            if not hard and not soft:
                lines.append(f"### {node_id}: ✅ PASS")
            elif hard:
                lines.append(f"### {node_id}: ❌ FAIL ({len(hard)} hard)")
            else:
                lines.append(f"### {node_id}: ⚠️ WARN ({len(soft)} soft)")

            for v in node_report["verdicts"]:
                if not v["answer"]:
                    icon = "🔴" if v["severity"] == "hard" else "🟡"
                    lines.append(f"- {icon} **{v['question_id']}**: {v.get('reasoning', '')}")
            lines.append("")

    return "\n".join(lines)
