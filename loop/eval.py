#!/usr/bin/env python3
"""Score a --mini run against loop/quality_eval.md.

Two buckets (judge the OUTPUT, not the process):
  FORMAT  (deterministic): F1 structure/schema, F2 scene format, F3 language.
  PLOT    (LLM judge, the real goal): P1 node-turns, P2 build-to-peak, P3 hook,
          P4 endings, P5 game-mechanics, P6 craft  — rubric in loop/quality_eval.md.

Returns {score 0-100, dimensions, deficiencies}. With --no-judge only the FORMAT
bucket is scored (normalized over its weight).

    python -m loop.eval <run_dir> [--log <p>] [--min-ch N] [--no-judge] [--model M] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Weights mirror quality_eval.md. Keep in sync if you edit the rubric.
WEIGHTS = {"F1": 15, "F2": 10, "F3": 5, "P1": 18, "P2": 12, "P3": 10, "P4": 12, "P5": 12, "P6": 6}
FORMAT = {"F1", "F2", "F3"}
PLOT = {"P1", "P2", "P3", "P4", "P5", "P6"}


def _load_graph(run_dir):
    from harness.checkpoint import load_graph, find_latest_checkpoint
    gf = os.path.join(run_dir, "graph_final.json")
    cp = gf if os.path.exists(gf) else find_latest_checkpoint(run_dir)
    if not cp:
        raise FileNotFoundError(f"no graph_final.json or checkpoint in {run_dir}")
    return load_graph(cp)


def _headers(n):
    return [e for e in n.content if isinstance(e, dict) and e.get("type") == "scene_header"]


def _score(pts, total):
    return round(10 * pts / total, 1) if total else 0.0


# ---------- FORMAT (deterministic) ----------

def _f1_structure(graph, log_text, min_ch):
    """F1 — structure & schema conformance (0-10)."""
    defs, pts, total = [], 0, 0
    nodes = list(graph.nodes.values())
    root = graph.nodes[graph.root]
    endings = [n for n in nodes if n.ending == "ENDING"]

    def chk(ok, msg):
        nonlocal pts, total
        total += 1
        if ok:
            pts += 1
        else:
            defs.append("F1: " + msg)

    chk(all(len(n.choices) == 2 for n in nodes if n.ending == "NONE"),
        "every non-ending node must have exactly 2 choices")
    chk(all(len(n.choices) == 0 for n in endings), "ENDING nodes must have 0 choices")
    tg = [c.to for c in root.choices]
    chk(len(tg) == 2 and tg[0] != tg[1], f"prologue choices must reach 2 different endings (got {tg})")
    chk(bool((root.question or "").strip()), "prologue has no question")
    chk(all(0 < len(c.label) <= 8 for c in root.choices),
        f"choice labels must be <=8字 ({[c.label for c in root.choices]})")
    chk(not any(n.ending == "DEAD_END" for n in nodes), "mini should have 0 DEAD_END")
    chk(min_ch is None or (root.chapters and root.chapters[0] == min_ch),
        f"root.chapters[0] should == opening chapter {min_ch}")
    # terminal markers on endings
    ok_term = all(any(isinstance(e, dict) and "结局：" in str(e.get("text", "")) for e in n.content)
                  for n in endings)
    chk(ok_term, "each ENDING must contain a 结局：… marker")
    # namecards present, none duplicated within a node
    dup = False
    for n in nodes:
        names = [e.get("name") for e in n.content if isinstance(e, dict) and e.get("type") == "namecard"]
        if len(names) != len(set(names)):
            dup = True
    chk(not dup, "duplicate 【人名字幕条】 within a node")
    return _score(pts, total), defs


def _f2_scene_format(graph):
    """F2 — scene format (场) (0-10).

    The webapp format tokens (场：/景：/时：/人：/▲) are produced deterministically by
    the export renderer from scene_header/action elements, so we check the element
    types that yield them rather than re-rendering."""
    defs, pts, total = [], 0, 0
    for nid, n in graph.nodes.items():
        if n.ending == "DEAD_END":
            continue
        total += 3
        if n.content and isinstance(n.content[0], dict) and n.content[0].get("type") == "scene_header":
            pts += 1
        else:
            defs.append(f"F2: node {nid} must start with a scene_header")
        if 3 <= len(_headers(n)) <= 5:
            pts += 1
        else:
            defs.append(f"F2: node {nid} has {len(_headers(n))} 场 (need 3-5)")
        # has action beats (→ ▲) and well-formed headers (→ 场/景/时/人)
        if any(isinstance(el, dict) and el.get("type") == "action" for el in n.content) and \
           all(h.get("location") and h.get("time") is not None for h in _headers(n)):
            pts += 1
        else:
            defs.append(f"F2: node {nid} missing action beats or headers lack location/time")
    return _score(pts, total), defs


def _f3_language(graph):
    """F3 — language hygiene (0-10)."""
    defs, pts, total = [], 0, 2
    bad = sum(1 for n in graph.nodes.values() for el in n.content
              if isinstance(el, dict) for v in el.values() if isinstance(v, str) and '"' in v)
    if bad == 0:
        pts += 1
    else:
        defs.append(f"F3: {bad} text field(s) contain raw double-quotes (use 「」)")
    text = "".join(str(el.get("text", "") or el.get("line", "")) for n in graph.nodes.values()
                   for el in n.content if isinstance(el, dict))
    if any("一" <= ch <= "鿿" for ch in text):
        pts += 1
    else:
        defs.append("F3: output does not appear to be Chinese")
    return _score(pts, total), defs


# ---------- PLOT (LLM judge: one focused call PER dimension, in parallel) ----------

def _plot_blocks():
    """Extract per-dimension rubric blocks {P1: text, ...} from quality_eval.md so
    each judge call sees ONLY its own dimension's self-contained criteria."""
    import re
    full = (Path(__file__).parent / "quality_eval.md").read_text()
    s, e = full.find("# Bucket 2"), full.find("## Scoring")
    plot = full[s:e] if (s >= 0 and e > s) else full
    blocks = {}
    for m in re.finditer(r"### (P\d) — .*?(?=\n### P\d|\Z)", plot, re.S):
        blocks[m.group(1)] = m.group(0).strip()
    return blocks


def _judge_payload(graph, bible):
    from harness.models import render_content_to_text
    root = graph.nodes[graph.root]
    return {
        "opening_scene": (bible or {}).get("opening_scene", ""),
        "question": root.question,
        "choices": [{"label": c.label, "to": c.to} for c in root.choices],
        "nodes": {nid: {"kind": n.kind, "ending": n.ending,
                        "script": render_content_to_text(n.content)[:2200]}
                  for nid, n in graph.nodes.items()},
    }


def _judge_one(dim, dim_rubric, payload, params):
    """One focused call scoring a single plot dimension → (dim, score, deficiencies)."""
    from harness.llm import _call_json
    schema = {"type": "object",
              "properties": {"score": {"type": "number"},
                             "deficiencies": {"type": "array", "items": {"type": "string"}}},
              "required": ["score", "deficiencies"]}
    system = (f"You are a harsh script editor. Score ONLY dimension {dim} of one interactive "
              f"--mini output (a prologue choice node + 2 endings): 0-10 (10=festival-grade, "
              f"5=competent-but-generic, 0=broken). List specific, actionable deficiencies for "
              f"{dim} only. Judge the output alone; ignore other dimensions.\n\n{dim_rubric}")
    user = f"Score this output on {dim}. JSON only.\n" + json.dumps(payload, ensure_ascii=False)[:8000]
    data = _call_json(system, user, params, context=f"loop_judge_{dim}", cacheable=False, schema=schema)
    return dim, float(data.get("score", 0)), [f"{dim}: {d}" if not str(d).startswith(dim) else d
                                              for d in data.get("deficiencies", [])]


def _judge_plot(graph, bible, params):
    """6 focused per-dimension calls in parallel → {dim: (score, defs)}."""
    from concurrent.futures import ThreadPoolExecutor
    blocks = _plot_blocks()
    payload = _judge_payload(graph, bible)
    out = {}
    with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
        futs = [pool.submit(_judge_one, d, r, payload, params) for d, r in blocks.items()]
        for f in futs:
            dim, sc, defs = f.result()
            out[dim] = (sc, defs)
    return out


def evaluate(run_dir, log_text="", min_ch=1, use_judge=True, model="deepseek"):
    """Score = PLOT (P1-P6) normalized to 0-100. FORMAT (F1-F3) is a 0-weight
    PRECONDITION gate: a valid --mini already passed the harness schema + protected
    validators, so a format failure here means something upstream broke → hard reject."""
    graph = _load_graph(run_dir)
    bible = {}
    p1 = os.path.join(run_dir, "phase1_complete.json")
    if os.path.exists(p1):
        bible = json.load(open(p1)).get("bible", {})

    # FORMAT gate (not scored) — should always pass on a valid run.
    dims, fmt_defs = {}, []
    for key, fn in (("F1", lambda: _f1_structure(graph, log_text, min_ch)),
                    ("F2", lambda: _f2_scene_format(graph)),
                    ("F3", lambda: _f3_language(graph))):
        s, d = fn()
        dims[key] = s
        fmt_defs += d
    format_ok = all(dims[k] >= 9.999 for k in FORMAT)

    deficiencies = list(fmt_defs)
    score, judged = None, False
    if use_judge:
        from harness.__main__ import _load_dotenv
        _load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))  # FIREWORKS_API_KEY etc.
        from harness.llm import set_model_profile
        from harness.models import Params
        set_model_profile(model)
        try:
            j = _judge_plot(graph, bible, Params())
            for k in PLOT:
                dims[k] = j[k][0]
                deficiencies += j[k][1]
            wsum = sum(WEIGHTS[k] for k in PLOT)
            score = round(10 * sum(dims[k] * WEIGHTS[k] for k in PLOT) / wsum, 1)
            judged = True
        except Exception as e:  # noqa: BLE001
            print(f"[eval] plot judge failed ({e})", file=sys.stderr)

    return {"score": score, "format_ok": format_ok, "dimensions": dims,
            "deficiencies": deficiencies, "judged": judged}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--log", default="")
    ap.add_argument("--min-ch", type=int, default=1)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--model", default="deepseek")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    log_text = Path(a.log).read_text() if a.log and os.path.exists(a.log) else ""
    res = evaluate(a.run_dir, log_text, a.min_ch, use_judge=not a.no_judge, model=a.model)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        sc = res["score"]
        print(f"PLOT SCORE: {sc if sc is not None else 'n/a (--no-judge)'}/100  "
              f"| format_gate: {'PASS' if res['format_ok'] else 'FAIL'}  | judged={res['judged']}")
        for k in sorted(res["dimensions"]):
            print(f"  {k}: {res['dimensions'][k]}")
        for d in res["deficiencies"]:
            print(f"  - {d}")


if __name__ == "__main__":
    main()
