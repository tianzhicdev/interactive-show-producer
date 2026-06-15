"""Deterministic export from a validated harness graph to web-app data."""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

from .models import VARIES, FactDecl, Graph, Node, Registry


def write_web_exports(
    graph: Graph,
    registry: Registry,
    bible: dict[str, Any],
    output_dir: str,
    *,
    project_name: str | None = None,
) -> dict[str, str]:
    """Write web-app upload/import artifacts derived without LLM calls."""
    package = build_web_package(graph, registry, bible, project_name=project_name)
    validate_web_package(package)

    out = Path(output_dir)
    package_path = out / "web_app_export.json"
    outline_path = out / "web_outline_payload.json"

    package_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    outline_payload = {
        "world_settings": package["world_settings"],
        "characters": package["characters"],
        "dag_nodes": package["dag_nodes"],
        "dag_edges": package["dag_edges"],
    }
    outline_path.write_text(
        json.dumps(outline_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "web_app_export": str(package_path),
        "web_outline_payload": str(outline_path),
    }


def build_web_package(
    graph: Graph,
    registry: Registry,
    bible: dict[str, Any],
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Convert harness data to the web app's persisted table/API shape."""
    order = graph.topo_order()

    # Build rename map: internal IDs → EP01/DE01/EN01 format
    rename = _build_rename_map(graph, order)

    positions = _compute_positions(graph, order)
    out_edges = _edges_by_source(graph, order)

    dag_nodes = []
    scene_scripts = []
    for idx, nid in enumerate(order, start=1):
        node = graph.nodes[nid]
        node_out = out_edges.get(nid, [])
        scene_type = _scene_type(node, len(node_out))
        title = _node_title(node, idx)
        summary = _node_summary(node)
        display_key = rename.get(nid, nid)
        dag_nodes.append({
            "node_key": display_key,
            "title": title,
            "summary": summary,
            "scene_type": scene_type,
            "is_ending": node.ending == "ENDING",
            "is_hidden_ending": node.ending == "DEAD_END",
            "episode_number": idx,
            "episode_title": title,
            "planned_duration_min": node.planned_duration_min,
            "position_x": positions[nid][0],
            "position_y": positions[nid][1],
            "requires": [_requirement_to_predicate(r) for r in node.requires],
            "invariants": [_requirement_to_predicate(r) for r in node.entry_invariants],
            "computed_states": _computed_states(node),
            # Per-node dramatic metadata for the UI (W: live review support)
            "metadata": {
                "sequence": node.sequence,
                "arc_slot": node.arc_slot,
                "tension": node.tension,
                "value": node.value,
                "opening_charge": node.opening_charge,
                "closing_charge": node.closing_charge,
                "turning_type": node.turning_type,
                "expectation": node.expectation,
                "result": node.result,
                "chapters": list(node.chapters),
                "covers": list(node.covers),
                "planned_duration_min": node.planned_duration_min,
                "question": node.question,
                "choices": [
                    {
                        "label": c.label,
                        "to": rename.get(c.to, c.to),
                        "cost": c.cost,
                        "goal_impacts": c.goal_impacts,
                        "state_delta": [
                            {"fact": e.fact, "value": e.value} for e in c.state_delta
                        ],
                        "has_aftermath": bool(c.aftermath),
                    }
                    for c in node.choices
                ],
            },
        })
        # Use renamed keys in scene_script content too
        renamed_out = []
        for e in node_out:
            re_edge = dict(e)
            re_edge["source_node_key"] = rename.get(e["source_node_key"], e["source_node_key"])
            re_edge["target_node_key"] = rename.get(e["target_node_key"], e["target_node_key"])
            renamed_out.append(re_edge)
        scene_scripts.append({
            "node_key": display_key,
            "version": 1,
            "content": _scene_script(node, title, renamed_out, display_key),
            "status": "ready" if node.content else "pending",
        })

    dag_edges = []
    for src in order:
        for idx, choice in enumerate(graph.nodes[src].choices):
            dag_edges.append({
                "source_node_key": rename.get(src, src),
                "target_node_key": rename.get(choice.to, choice.to),
                "choice_label": choice.label,
                "choice_index": idx,
                "effects": [_effect_to_state_effect(e) for e in graph.nodes[src].produces],
                "state_delta": [_effect_to_state_effect(e) for e in choice.state_delta],
                "resolution": list(choice.resolution),
                "aftermath": list(choice.aftermath),
            })

    return {
        "format": "harness_web_app_export",
        "version": 1,
        "project": {
            "name": project_name or bible.get("title") or bible.get("world", "")[:30] or "Untitled",
            "status": "done",
        },
        "story_summary": _story_summary(bible),
        "world_settings": _world_settings(bible, registry),
        "characters": _characters(bible),
        "dag_nodes": dag_nodes,
        "dag_edges": dag_edges,
        "scene_scripts": scene_scripts,
        "api_contract": {
            "get-outline": ["project", "story_summary", "world_settings", "characters", "dag"],
            "get-dag": ["nodes", "edges"],
        },
    }


def validate_web_package(package: dict[str, Any]) -> None:
    """Validate the deterministic export before it can be imported/uploaded."""
    required_top = {
        "format", "version", "project", "story_summary", "world_settings",
        "characters", "dag_nodes", "dag_edges", "scene_scripts",
    }
    missing = required_top - set(package)
    if missing:
        raise ValueError(f"web export missing top-level fields: {sorted(missing)}")

    nodes = package["dag_nodes"]
    edges = package["dag_edges"]
    scripts = package["scene_scripts"]
    chars = package["characters"]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("web export requires non-empty dag_nodes")
    if not isinstance(edges, list):
        raise ValueError("web export dag_edges must be a list")
    if not isinstance(scripts, list):
        raise ValueError("web export scene_scripts must be a list")
    if not isinstance(chars, list):
        raise ValueError("web export characters must be a list")

    node_keys = set()
    for node in nodes:
        _require_fields(node, {
            "node_key", "title", "summary", "scene_type", "is_ending",
            "is_hidden_ending", "position_x", "position_y", "requires",
            "invariants", "computed_states",
        }, "dag_node")
        if node["scene_type"] not in {"normal", "choice", "ending", "hidden_ending"}:
            raise ValueError(f"invalid scene_type for {node['node_key']}: {node['scene_type']}")
        if node["node_key"] in node_keys:
            raise ValueError(f"duplicate node_key: {node['node_key']}")
        question = (
            ((node.get("metadata") or {}).get("question"))
            or ((node.get("metadata") or {}).get("choice_question"))
            or ""
        )
        if question and _normalize_title_text(node["title"]) == _normalize_title_text(question):
            raise ValueError(
                f"dag_node {node['node_key']} title must describe node content, not repeat question"
            )
        node_keys.add(node["node_key"])

    for edge in edges:
        _require_fields(edge, {
            "source_node_key", "target_node_key", "choice_label",
            "choice_index", "effects", "resolution",
        }, "dag_edge")
        if edge["source_node_key"] not in node_keys:
            raise ValueError(f"edge source missing node: {edge['source_node_key']}")
        if edge["target_node_key"] not in node_keys:
            raise ValueError(f"edge target missing node: {edge['target_node_key']}")

    script_keys = set()
    for script in scripts:
        _require_fields(script, {"node_key", "version", "content", "status"}, "scene_script")
        if script["node_key"] not in node_keys:
            raise ValueError(f"script node missing from DAG: {script['node_key']}")
        if not str(script.get("content", "")).lstrip().startswith("场："):
            raise ValueError(f"scene_script for {script['node_key']} must start with 场：")
        script_keys.add(script["node_key"])
    if script_keys != node_keys:
        raise ValueError("scene_scripts must contain exactly one script for every DAG node")

    for char in chars:
        _require_fields(char, {"name", "profile_data"}, "character")


def _build_rename_map(graph: Graph, order: list[str]) -> dict[str, str]:
    """Map internal node IDs → display keys: EP01, DE01, EN01."""
    rename: dict[str, str] = {}
    ep_count = 0
    de_count = 0
    en_count = 0
    for nid in order:
        node = graph.nodes[nid]
        if node.ending == "ENDING":
            en_count += 1
            rename[nid] = f"EN{en_count:02d}"
        elif node.ending == "DEAD_END":
            de_count += 1
            rename[nid] = f"DE{de_count:02d}"
        else:
            ep_count += 1
            rename[nid] = f"EP{ep_count:02d}"
    return rename


def _compute_positions(graph: Graph, order: list[str]) -> dict[str, tuple[float, float]]:
    adj = {nid: [c.to for c in graph.nodes[nid].choices] for nid in graph.nodes}
    depth: dict[str, int] = {}
    queue = deque([(graph.root, 0)])
    while queue:
        nid, d = queue.popleft()
        if nid in depth:
            continue
        depth[nid] = d
        for dst in adj.get(nid, []):
            if dst in graph.nodes and dst not in depth:
                queue.append((dst, d + 1))

    max_depth = max(depth.values()) if depth else 0
    for nid in order:
        if nid not in depth:
            max_depth += 1
            depth[nid] = max_depth

    by_depth: dict[int, list[str]] = {}
    for nid in order:
        by_depth.setdefault(depth[nid], []).append(nid)

    positions = {}
    for d, nids in by_depth.items():
        width = len(nids)
        for i, nid in enumerate(nids):
            positions[nid] = (float(d * 220), float((i - (width - 1) / 2) * 280))
    return positions


def _edges_by_source(graph: Graph, order: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for src in order:
        for idx, choice in enumerate(graph.nodes[src].choices):
            grouped.setdefault(src, []).append({
                "source_node_key": src,
                "target_node_key": choice.to,
                "choice_label": choice.label,
                "choice_index": idx,
                "state_delta": [
                    {"fact": e.fact, "value": e.value} for e in choice.state_delta
                ],
                "resolution": list(choice.resolution),
                "aftermath": list(choice.aftermath),
            })
    return grouped


def _story_summary(bible: dict[str, Any]) -> str:
    """Build 故事背景 — a concise story background for the preview."""
    parts = []
    if bible.get("title"):
        parts.append(f"# {bible['title']}")

    # Combine setting + world into 故事背景
    bg_parts = []
    if bible.get("setting"):
        bg_parts.append(str(bible["setting"]).strip())
    if bible.get("world") and str(bible["world"]).strip() != str(bible.get("setting", "")).strip():
        bg_parts.append(str(bible["world"]).strip())
    if bg_parts:
        parts.append(f"\n## 故事背景\n{''.join(bg_parts)}")

    if bible.get("themes"):
        parts.append("\n## 主题\n" + "\n".join(f"- {t}" for t in _as_list(bible["themes"])))
    return "\n".join(parts) if parts else json.dumps(bible, ensure_ascii=False, indent=2)


def _world_settings(bible: dict[str, Any], registry: Registry) -> dict[str, Any]:
    # Combine setting + world into world_building
    bg_parts = []
    if bible.get("setting"):
        bg_parts.append(str(bible["setting"]).strip())
    if bible.get("world") and str(bible["world"]).strip() != str(bible.get("setting", "")).strip():
        bg_parts.append(str(bible["world"]).strip())
    ws: dict[str, Any] = {
        "title": bible.get("title", ""),
        "genre": bible.get("genre", ""),
        "world_building": " ".join(bg_parts) if bg_parts else "",
        "tone": bible.get("tone", ""),
        "themes": _as_list(bible.get("themes", [])),
    }
    for key in ("time_period", "locations", "power_system", "factions", "rules"):
        if bible.get(key):
            ws[key] = bible[key]
    return ws


def _characters(bible: dict[str, Any]) -> list[dict[str, Any]]:
    """Build character profiles following /interactive-play-writer-characters-intro format.

    Each character gets:
      - identity: one-line identity/role (身份)
      - bio: ~300 char background intro (背景介绍)
    These map to webapp profile_data keys.
    """
    seen = set()
    out = []
    for raw in _as_list(bible.get("characters", [])):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        identity = str(raw.get("role") or raw.get("identity") or "")
        description = str(raw.get("description") or raw.get("bio") or "")
        # Build profile matching the characters-intro skill output
        profile = {
            "identity": identity,
            "bio": description,
            # Legacy fields for webapp compatibility
            "role": identity,
            "description": description,
            "personality": _str_or_list(raw.get("personality") or raw.get("traits") or ""),
            "appearance": str(raw.get("appearance") or ""),
            "abilities": str(raw.get("abilities") or ""),
            "motivation": str(raw.get("goals") or raw.get("motivation") or ""),
            "relationships": _str_or_list(raw.get("relationships") or raw.get("relationship") or ""),
            "background": str(raw.get("backstory") or raw.get("background") or ""),
        }
        out.append({"name": name, "profile_data": profile})
    return out


def _str_or_list(val: Any) -> str:
    """Convert a list to comma-joined string, or pass through string."""
    if isinstance(val, list):
        return "、".join(str(v) for v in val)
    return str(val)


def _scene_type(node: Node, out_degree: int) -> str:
    if node.ending == "ENDING":
        return "ending"
    if node.ending == "DEAD_END":
        return "hidden_ending"
    return "choice" if out_degree > 1 else "normal"


def _node_title(node: Node, index: int) -> str:
    # W7: dedicated chapter-style title from the metadata pass wins
    if node.title:
        if node.ending == "DEAD_END" and not node.title.startswith("BE"):
            return f"BE：{node.title}"
        return node.title
    if node.ending == "ENDING":
        title = _ending_title(node) or _dramatic_title_from_summary(node.get_summary())
    elif node.ending == "DEAD_END":
        title = _dramatic_title_from_summary(node.get_summary())
        if title and not title.startswith("BE"):
            title = f"BE：{title}"
    else:
        title = (
            _dramatic_title_from_content(node)
            or _dramatic_title_from_summary(node.get_summary())
        )

    if len(title) > 28:
        title = title[:28] + "..."
    return title or f"剧情节点 {index}"


def _normalize_title_text(text: str) -> str:
    return re.sub(r"[？?。！!；;：:\s,，、]+", "", text or "").strip()


def _dramatic_title_from_content(node: Node) -> str:
    for el in node.content or node.skeleton or []:
        if not isinstance(el, dict):
            continue
        typ = el.get("type")
        text = ""
        if typ == "action":
            text = str(el.get("text") or "")
        elif typ == "dialogue":
            text = str(el.get("line") or "")
        elif typ == "narration":
            text = str(el.get("text") or "")
        if not text:
            continue
        title = _dramatic_title_from_summary(text)
        title = re.sub(r"^(颜如玉|霍长鹤|她|他|众人|婆母|霍大夫人)", "", title).strip(" ，,：:")
        if title:
            return title
    return ""


def _dramatic_title_from_summary(summary: str) -> str:
    text = re.sub(r"\s+", " ", summary or "").strip()
    if not text:
        return ""
    first_clause = re.split(r"[。！？!?；;]", text, maxsplit=1)[0].strip()
    first_clause = re.sub(
        r"^(本节点|该节点|这一节点|此节点|讲述|描写|展示|写出|围绕|主要|剧情|玩家)",
        "",
        first_clause,
    ).strip(" ，,：:")
    first_clause = re.sub(r"^(苏云落|女主|主角|她|霍长鹤|众人)", "", first_clause).strip(" ，,：:")
    return first_clause or text


def _ending_title(node: Node) -> str:
    for el in node.content or []:
        if not isinstance(el, dict) or el.get("type") != "narration":
            continue
        text = str(el.get("text", ""))
        if "结局：" in text:
            return text.split("结局：", 1)[1].strip()
    return ""


def _node_summary(node: Node) -> str:
    """Short scene description for the DAG node subtitle (NOT prose content)."""
    parts = []
    loc = node.get_scene_location()
    time = node.get_scene_time()
    chars = node.get_scene_characters()
    if loc:
        parts.append(loc)
    if time:
        parts.append(time)
    if chars:
        parts.append("、".join(chars[:4]))
    return " · ".join(parts) if parts else ""


def _scene_script(node: Node, title: str, out_edges: list[dict[str, Any]], display_key: str | None = None) -> str:
    from .models import render_content_to_text
    scene_no = display_key or _episode_code(node.id)

    parts: list[str] = []

    # NOTE: Metadata (原文章节, 入场状态) is NOT included here —
    # the webapp shows that in the collapsible "状态变化" panel via
    # dag_node.requires / dag_node.computed_states.

    # Render structured content elements
    if node.content:
        scene_idx = 0
        for el in node.content:
            t = el.get("type", "")
            if t == "scene_header":
                scene_idx += 1
                loc = el.get("location", "")
                time = el.get("time", "")
                chars = "、".join(el.get("characters", []))
                sub_no = f"{scene_no}-{scene_idx:02d}" if scene_idx > 1 else scene_no
                parts.append(f"\n场：{sub_no}    景：{loc}")
                parts.append(f"时：{time}    人：{chars}")
                parts.append("")
            elif t == "action":
                shot = el.get("shot", "")
                text = el.get("text", "")
                if shot:
                    parts.append(f"▲{shot}：{text}")
                else:
                    parts.append(f"▲{text}")
            elif t == "dialogue":
                speaker = el.get("speaker", "")
                emotion = el.get("emotion", "")
                line = el.get("line", "")
                if emotion:
                    parts.append(f"{speaker}：（{emotion}）{line}")
                else:
                    parts.append(f"{speaker}：{line}")
            elif t == "narration":
                parts.append(f"旁白：{el.get('text', '')}")
            elif t == "namecard":
                name = el.get("name", "")
                title = el.get("title", "")
                parts.append(f"【人名字幕条】{name}，{title}")
            else:
                parts.append(el.get("text", str(el)))
    else:
        # Fallback for nodes without structured content
        prose = node.get_prose()
        if prose:
            parts.append(f"\n{prose}")

    # Choices section
    if out_edges:
        parts.append(f"\n选择 {scene_no}")
        if node.question:
            parts.append(f"问题：{node.question}")
        for edge in out_edges:
            parts.append(
                f"{scene_no}-{chr(65 + edge['choice_index'])}：{edge['choice_label']} → "
                f"{edge['target_node_key']}"
            )
        for edge in out_edges:
            parts.append(
                f"\n━━━━━━━━━━ {scene_no}{chr(65 + edge['choice_index'])}："
                f"{edge['choice_label']} → {edge['target_node_key']} ━━━━━━━━━━"
            )
            aftermath = edge.get("aftermath") or []
            if aftermath:
                from .models import render_content_to_text
                parts.append(render_content_to_text(aftermath))
            else:
                for beat in edge.get("resolution", []):
                    parts.append(f"▲{beat}")
    elif node.ending == "DEAD_END":
        if not any(el.get("text") == "BE" for el in node.content if isinstance(el, dict)):
            parts.append("\nBE")
    elif node.ending == "ENDING":
        if not any("结局：" in str(el.get("text", "")) for el in node.content if isinstance(el, dict)):
            parts.append(f"\n结局：{title}")
    return "\n".join(parts).strip()


def _episode_code(node_id: str) -> str:
    m = re.search(r"(\d+)", node_id)
    if m:
        return m.group(1).zfill(3)
    return node_id.upper()[:3].ljust(3, "0")


def _split_context(context: str) -> tuple[str, str]:
    if not context:
        return "", ""
    parts = re.split(r"[·｜|/，,\s]+", context, maxsplit=1)
    place = parts[0]
    time = parts[1] if len(parts) > 1 and parts[1] else ""
    return place[:24], time[:24]


def _guess_people(content: str) -> str:
    """Extract character names from dialogue lines (Name：dialogue pattern)."""
    names = []
    seen = set()
    for m in re.finditer(r"^([^\s：:▲场时人选\d━┌┐└┘├┤│─]{1,6})：", content, re.MULTILINE):
        name = m.group(1).strip()
        if name and name not in seen and name not in ("问题", "旁白"):
            seen.add(name)
            names.append(name)
        if len(names) >= 5:
            break
    return "、".join(names)


def _computed_states(node: Node) -> dict[str, list[Any]]:
    state = node.guaranteed or {}
    return {
        key: [_json_value(value)]
        for key, value in sorted(state.items())
    }


def _requirement_to_predicate(req: Any) -> dict[str, Any]:
    return {"key": req.fact, "cmp": "eq", "value": _json_value(req.value)}


def _effect_to_state_effect(effect: Any) -> dict[str, Any]:
    return {"key": effect.fact, "op": "set", "value": _json_value(effect.value)}


def _json_value(value: Any) -> Any:
    if value is VARIES:
        return "__VARIES__"
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _require_fields(obj: Any, fields: set[str], label: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{label} must be an object")
    missing = fields - set(obj)
    if missing:
        raise ValueError(f"{label} missing fields: {sorted(missing)}")
