#!/usr/bin/env python3
"""Render spine DAG as a Graphviz PNG image.

Adapted from renderer.py overview graph. Spine-specific rendering:
  - Each node = one episode (EP01, EP02, ...)
  - Nodes colored by kind: scene=blue, bottleneck=orange, ending=green
  - Edge labels show choice text + effects
  - CJK font: Heiti SC

Usage:
    python render_spine_dag.py <project_dir> [--format png|svg|pdf]

Output:
    <project_dir>/dag.png (or .svg/.pdf)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from data_model import SpineState, Spine, Node, Edge, load_state


CJK_FONT = 'Heiti SC'

# ── Node styling ────────────────────────────────────────────────────

import re

def node_style(node: Node) -> dict:
    """Return Graphviz node attrs based on node kind and ID pattern."""
    # Dead ends (DE##): red fill
    if node.id.startswith("DE"):
        return dict(
            shape='box',
            fillcolor='#ffcdd2',
            color='#c62828',
            fontcolor='#b71c1c',
            style='filled,rounded',
            penwidth='2',
        )
    if node.kind == "bottleneck":
        return dict(
            shape='doubleoctagon',
            fillcolor='#fff3e0',
            color='#e65100',
            fontcolor='#bf360c',
            style='filled,bold',
            penwidth='2',
        )
    if node.kind == "ending":
        return dict(
            shape='box',
            fillcolor='#c8e6c9',
            color='#2e7d32',
            fontcolor='#1b5e20',
            style='filled,rounded',
        )
    # Prologue: light purple, bold rounded box
    if node.kind == "prologue":
        return dict(
            shape='box',
            fillcolor='#e1bee7',
            color='#7b1fa2',
            fontcolor='#4a148c',
            style='filled,bold,rounded',
            penwidth='2',
        )
    # Branch nodes (EP##A, EP##B, ...): lighter blue, dashed border
    if re.match(r'^EP\d{2}[A-Z]$', node.id):
        return dict(
            shape='box',
            fillcolor='#e8eaf6',
            color='#3949ab',
            fontcolor='#1a237e',
            style='filled,dashed,rounded',
        )
    # scene (default — linear nodes EP##)
    return dict(
        shape='box',
        fillcolor='#e3f2fd',
        color='#1565c0',
        fontcolor='#0d47a1',
        style='filled,rounded',
    )


# ── Main render function ────────────────────────────────────────────

def render_spine_dag(
    state: SpineState,
    project_dir: str,
    fmt: str = 'png',
) -> str:
    """Render the spine DAG and return the output file path."""
    import graphviz

    spine = state.spine
    bible = state.bible
    title = bible.title or state.metadata.get('title', '')

    g = graphviz.Digraph('SPINE', format=fmt, engine='dot')
    g.attr('graph',
        fontname=CJK_FONT,
        rankdir='TB',
        bgcolor='white',
        pad='0.5',
        nodesep='0.5',
        ranksep='0.7',
        dpi='150',
        label=f'《{title}》Story Spine',
        fontsize='18',
        labelloc='t',
    )
    g.attr('node', fontname=CJK_FONT, fontsize='10', style='filled')
    g.attr('edge', fontname=CJK_FONT, fontsize='8', color='#78909c')

    # Add nodes — each node IS one episode (EP01, EP02, ...)
    for node in spine.nodes:
        label_parts = [f"{node.id}"]
        if node.title:
            t = node.title if len(node.title) <= 15 else node.title[:14] + '…'
            label_parts.append(t)
        if node.goal:
            g_text = node.goal if len(node.goal) <= 20 else node.goal[:19] + '…'
            label_parts.append(f"[{g_text}]")
        label_parts.append(f"{node.duration_min}min")
        label = '\n'.join(label_parts)

        g.node(node.id, label, **node_style(node))

    # Add edges
    for edge in spine.edges:
        edge_attrs: dict[str, str] = {}

        # Label: choice text + effects
        label_parts = []
        if edge.label:
            label_parts.append(edge.label)
        if edge.effects:
            eff_strs = []
            for e in edge.effects:
                if e.op == "set":
                    eff_strs.append(f"{e.key}={e.value}")
                elif e.op == "add":
                    eff_strs.append(f"{e.key}+={e.value}")
            if eff_strs:
                label_parts.append(f"[{', '.join(eff_strs)}]")

        if label_parts:
            edge_attrs['label'] = ' '.join(label_parts)

        # Color edges by destination type
        dst_node = spine.get_node(edge.dst)
        if dst_node and dst_node.id.startswith("DE"):
            edge_attrs.update(color='#c62828', fontcolor='#c62828', style='dashed')
        elif dst_node and dst_node.kind == "ending":
            edge_attrs.update(color='#2e7d32', fontcolor='#2e7d32', style='bold')
        elif dst_node and dst_node.kind == "bottleneck":
            edge_attrs.update(color='#e65100', fontcolor='#e65100')

        g.edge(edge.src, edge.dst, **edge_attrs)

    # Render
    output_base = os.path.join(project_dir, 'dag')
    try:
        g.render(output_base, cleanup=True)
        output_path = f"{output_base}.{fmt}"
        print(f"DAG rendered: {output_path}")
        return output_path
    except Exception as e:
        print(f"WARNING: Could not render DAG: {e}")
        # Try without graphviz binary (just write dot source)
        dot_path = f"{output_base}.dot"
        with open(dot_path, 'w', encoding='utf-8') as f:
            f.write(g.source)
        print(f"Wrote DOT source to {dot_path} (install graphviz to render)")
        return dot_path


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Render spine DAG from state.json")
    parser.add_argument("project_dir", help="Project directory containing state.json")
    parser.add_argument("--format", default="png", choices=["png", "svg", "pdf"],
                        help="Output format (default: png)")
    args = parser.parse_args()

    state_path = os.path.join(args.project_dir, "state.json")
    if not os.path.exists(state_path):
        print(f"ERROR: {state_path} not found")
        sys.exit(1)

    state = load_state(args.project_dir)
    output = render_spine_dag(state, args.project_dir, fmt=args.format)
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
