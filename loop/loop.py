#!/usr/bin/env python3
"""Harness auto-improvement loop. See loop/AGENTS.md for the design.

A ratcheted hill-climber, per loop/AGENTS.md:
  STEP 1 propose (opencode-qwen, read-only) → STEP 2 apply (opencode-qwen, edits)
  → verify (tests + fake + a real --mini per fixture, evaluated by Fireworks deepseek)
  → score vs loop/quality_eval.md → keep ONLY if mean >= best-so-far AND per-genre
  floor holds AND green AND no protected/schema edits, else git revert.

Runs on branch `loop/auto`, never main, never pushes. Ctrl-C safe (state is on disk).

    python -m loop.loop [--max-iters 30 --patience 5 --branch loop/auto
                         --fast-only --model deepseek --dry-run]
"""
from __future__ import annotations

import argparse
import atexit
import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOP = ROOT / "loop"
STATE = LOOP / "state"


def sh(cmd, cwd=ROOT, timeout=None, check=False):
    # Run in its OWN process group so a timeout can kill the whole tree. Otherwise a hung
    # grandchild (e.g. a `python -m harness` spawned by a test) keeps the stdout pipe open
    # and `communicate()` blocks long past our timeout — the pytest-hang we kept hitting.
    p = subprocess.Popen(cmd, cwd=cwd, shell=isinstance(cmd, str),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)  # kill the whole group
        except (ProcessLookupError, PermissionError):
            pass
        try:
            out, err = p.communicate(timeout=15)           # reap; pipes close once dead
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return 124, f"TIMEOUT after {timeout}s: {cmd}"
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {cmd}\n{(err or '')[-2000:]}")
    return p.returncode, (out or "") + (err or "")


def git(*args):
    return sh(["git", *args])


# ---------- guards ----------

def protected_globs():
    out = []
    for line in (LOOP / "protected.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()  # drop full-line AND inline comments
        if line:
            out.append(line)
    return out


def changed_files():
    _, out = git("status", "--porcelain")
    return [ln[3:].strip() for ln in out.splitlines() if ln.strip()]


def touches_protected(files):
    globs = protected_globs()
    hit = []
    for f in files:
        if any(fnmatch.fnmatch(f, g) for g in globs):
            hit.append(f)
    return hit


_CJK = re.compile(r"[一-鿿]")
# Tokens that are legitimately allowed in code (format markers, log/structural).
_ALLOWED_CJK_TOKENS = set("场景时人选择问题旁白结局")


def gate_h_violation(diff_text):
    """Heuristic for AGENTS.md 'The One Rule': flag added .py lines that embed
    story-ish Chinese content outside comments / log() / error strings / format
    tokens. Conservative — false positives just cost an iteration."""
    bad = []
    cur_file = None
    for ln in diff_text.splitlines():
        if ln.startswith("+++ b/"):
            cur_file = ln[6:]
        if not (cur_file and cur_file.endswith(".py")):
            continue
        if not ln.startswith("+") or ln.startswith("+++"):
            continue
        body = ln[1:]
        if not _CJK.search(body):
            continue
        stripped = body.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\blog\.\w+\(|logger\.\w+\(|raise \w*Error|print\(", body):
            continue  # log / error / print messages are allowed
        # allow lines whose only CJK are format/structural tokens
        cjk_chars = set(_CJK.findall(body))
        if cjk_chars and cjk_chars <= _ALLOWED_CJK_TOKENS:
            continue
        bad.append(f"{cur_file}: {stripped[:80]}")
    return bad


_SCHEMA_MARKERS = ('"minItems"', '"maxItems"', '"minContains"', '"maxContains"',
                   '"required":', '"enum":', '"additionalProperties"', '"properties":')


def schema_edit_violation(diff_text):
    """Flag any diff line that adds/removes a JSON-schema definition in llm.py.
    The format contract (the schema) is fixed — the loop optimizes prose/plot, not
    the schema. Prompts (plain strings) don't contain these structural keys, so this
    lets the loop edit prompts in llm.py while locking the schemas."""
    bad, cur = [], None
    for ln in diff_text.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        if cur != "harness/llm.py":
            continue
        if not (ln.startswith("+") or ln.startswith("-")) or ln.startswith(("+++", "---")):
            continue
        body = ln[1:]
        if re.search(r"_SCHEMA\b\s*=", body) or any(m in body for m in _SCHEMA_MARKERS):
            bad.append(body.strip()[:80])
    return bad


def guard_violation(files, diff):
    """Return a reason string if a change touches protected files / schema / gate-H,
    else None. Used both per-item (drop the offending item) and on any diff."""
    prot = touches_protected(files)
    if prot:
        return "protected:" + ",".join(prot)
    gh = gate_h_violation(diff)
    if gh:
        return "gate-H:" + "; ".join(gh[:2])
    sch = schema_edit_violation(diff)
    if sch:
        return "schema-edit:" + "; ".join(sch[:2])
    return None


def targets_all_protected(item):
    """True if EVERY declared target_file is protected — skip applying it (saves an
    opencode call) since the guard would reject it anyway. (A real edit may differ, so
    this only fires when the proposer itself says it will only touch protected files.)"""
    tf = item.get("target_files") or []
    if not isinstance(tf, list) or not tf:
        return False
    globs = protected_globs()
    return all(any(fnmatch.fnmatch(str(f), g) for g in globs) for f in tf)


# ---------- verification ----------

def _pytest(timeout):
    # Deselect the ONE end-to-end test that spawns a `python -m harness` subprocess: it is
    # redundant here (fast_verify runs its own fake full + fake mini pipeline right after,
    # with hard timeouts) and is the lone source of the intermittent pytest hang under the
    # loop's subprocess context. The other 51 unit tests run in ~0.1s.
    return sh([sys.executable, "-m", "pytest", "harness/", "-q", "-p", "no:cacheprovider",
               "--deselect", "harness/test_trunk_v2.py::test_fake_pipeline_end_to_end"],
              timeout=timeout)


def fast_verify():
    """Unit tests + fake full run + fake mini. Returns (ok, summary).

    pytest is flaky under the loop's nohup subprocess context (it passes in ~0.3s
    standalone but has intermittently hung to the timeout). Since a genuine test
    failure is deterministic and fast, a TIMEOUT is treated as infra flakiness and
    retried ONCE on a shorter budget before we reject the iteration."""
    rc, out = _pytest(180)
    if rc == 124:  # timed out → flaky infra, not a real failure; retry once clean
        print("[loop] pytest timed out; retrying once...", file=sys.stderr)
        rc, out = _pytest(180)
    if rc != 0:
        return False, "pytest failed:\n" + out[-1500:]
    fix = "harness/fixtures/tijiawangfei_10ch.txt"
    rc, out = sh([sys.executable, "-m", "harness", fix, "--model", "fake",
                  "--playthrough", "12", "--total", "40", "--min-endings", "2",
                  "--no-upload"], timeout=600)
    if rc != 0:
        return False, "fake full run failed:\n" + out[-1500:]
    rc, out = sh([sys.executable, "-m", "harness", fix, "--model", "fake",
                  "--mini", "--no-upload"], timeout=600)
    if rc != 0:
        return False, "fake mini failed:\n" + out[-1500:]
    return True, "fast verify green"


_ACTIVE_MINIS: list = []  # Popen children — killed on loop exit/signal so a kill
                          # of the loop never orphans minis that keep hitting Fireworks.


def _kill_active_minis(*_a):
    import signal as _sig
    for p in _ACTIVE_MINIS:
        try:
            os.killpg(os.getpgid(p.pid), _sig.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    _ACTIVE_MINIS.clear()


def _launch_mini(story, model):
    """Start one real --mini as a detached process group. Returns (story, Popen, logpath)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(story))[:40]
    logpath = STATE / f"mini_{safe}.log"
    env = {**os.environ, "HARNESS_PROSE_WORKERS": "1", "HARNESS_INGEST_WORKERS": "1"}
    lf = open(logpath, "w")
    p = subprocess.Popen([sys.executable, "-m", "harness", story, "--mini", "--model",
                          model, "--no-upload", "-v"], cwd=ROOT, stdout=lf,
                         stderr=subprocess.STDOUT, text=True, env=env,
                         start_new_session=True)  # own process group → killable as a unit
    _ACTIVE_MINIS.append(p)
    return story, p, logpath, lf


def real_eval_all(fixtures, model, use_judge):
    """Run ALL fixtures' --mini in PARALLEL, then eval each. Returns dict:
       {mean, per_story: {fixture: score}, deficiencies, failed: [stories]}.
       The combined per-iteration signal = mean of the rotating set (see AGENTS.md)."""
    from loop.eval import evaluate
    procs = [_launch_mini(s, model) for s in fixtures]
    per_story, deficiencies, failed = {}, [], []
    for story, p, logpath, lf in procs:
        try:
            p.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            p.kill()
        lf.close()
        out = Path(logpath).read_text()
        if p.returncode != 0:
            failed.append(story); per_story[story] = 0.0
            deficiencies.append(f"[{os.path.basename(story)}] --mini run FAILED"); continue
        m = re.findall(r"harness_output/run_[0-9_]+", out)
        run_dir = m[-1] if m else None
        gf = os.path.join(ROOT, run_dir, "graph_final.json") if run_dir else ""
        if not run_dir or not os.path.exists(gf):
            failed.append(story); per_story[story] = 0.0
            deficiencies.append(f"[{os.path.basename(story)}] no graph_final.json"); continue
        res = evaluate(os.path.join(ROOT, run_dir), out, min_ch=1, use_judge=use_judge, model=model)
        base = os.path.basename(story)
        if not res["format_ok"]:
            # Format is schema/validator-enforced; a failure here means a loop change
            # broke something the protected gates don't cover → treat as a hard fail.
            failed.append(story); per_story[story] = 0.0
            deficiencies.append(f"[{base}] FORMAT GATE FAILED (schema/validator regression)")
            deficiencies += [f"[{base}] {d}" for d in res["deficiencies"] if d.startswith("F")]
            continue
        # use_judge=False → no plot score; fall back to format-gate-only (=100 pass).
        per_story[story] = res["score"] if res["score"] is not None else 100.0
        deficiencies += [f"[{base}] {d}" for d in res["deficiencies"]]
    mean = round(sum(per_story.values()) / len(per_story), 1) if per_story else 0.0
    _ACTIVE_MINIS.clear()  # all waited on above; none left to orphan
    return {"mean": mean, "per_story": per_story, "deficiencies": deficiencies, "failed": failed}


def _run_full_fixture(story, chapters, model):
    """Run one full fixture and score it with the deterministic report card."""
    from loop.eval import evaluate_full

    slug = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(story))[:24].strip("_") or "story"
    digest = hashlib.sha1(f"{story}|{chapters or ''}".encode("utf-8")).hexdigest()[:8]
    safe = f"{slug}_{digest}"
    logpath = STATE / f"full_{safe}.log"
    env = {**os.environ, "HARNESS_PROSE_WORKERS": "1", "HARNESS_INGEST_WORKERS": "1"}
    cmd = [sys.executable, "-m", "harness", story]
    if chapters:
        cmd += ["--chapters", chapters]
    cmd += ["--playthrough", "55", "--total", "100", "--min-endings", "3",
            "--model", model, "--no-upload"]
    lf = open(logpath, "w")
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT,
                         text=True, env=env, start_new_session=True)
    _ACTIVE_MINIS.append(p)
    try:
        p.wait(timeout=7200)
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
    lf.close()
    _ACTIVE_MINIS[:] = [x for x in _ACTIVE_MINIS if x.pid != p.pid]
    out = Path(logpath).read_text()
    label = os.path.basename(story)
    if p.returncode != 0:
        return story, 0.0, [f"[{label}] full run FAILED"], True
    m = re.findall(r"harness_output/run_[0-9_]+", out)
    run_dir = m[-1] if m else None
    gf = os.path.join(ROOT, run_dir, "graph_final.json") if run_dir else ""
    if not run_dir or not os.path.exists(gf):
        return story, 0.0, [f"[{label}] no graph_final.json"], True
    res = evaluate_full(os.path.join(ROOT, run_dir))
    return story, res["score"] if res["score"] is not None else 0.0, \
        [f"[{label}] {d}" for d in res["deficiencies"]], False


def real_eval_full_all(fixtures, model):
    """Run the full regression set and score each run with the deterministic
    full-run report card."""
    from concurrent.futures import ThreadPoolExecutor

    per_story, deficiencies, failed = {}, [], []
    if not fixtures:
        return {"mean": 0.0, "per_story": per_story, "deficiencies": deficiencies, "failed": failed}
    with ThreadPoolExecutor(max_workers=min(3, len(fixtures))) as pool:
        futs = [pool.submit(_run_full_fixture, fx["path"], fx.get("chapters"), model)
                for fx in fixtures]
        for f in futs:
            story, score, defs, bad = f.result()
            per_story[story] = score
            deficiencies.extend(defs)
            if bad:
                failed.append(story)
    mean = round(sum(per_story.values()) / len(per_story), 1) if per_story else 0.0
    return {"mean": mean, "per_story": per_story, "deficiencies": deficiencies, "failed": failed}


# ---------- propose (step 1) + apply (step 2): both via opencode-qwen ----------

OPENCODE = "opencode-qwen"  # opencode run, Qwen3-Coder via OpenRouter


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _oc_run(prompt, edit, timeout):
    """Run opencode-qwen headless. edit=False → read-only (no skip-permissions, so
    it CANNOT modify files headless); edit=True → autonomous edits."""
    cmd = [OPENCODE, "run", prompt, "--dir", str(ROOT)]
    if edit:
        cmd.append("--dangerously-skip-permissions")
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        # opencode hang / network outage → return empty; the loop treats a no-change
        # apply as a skipped iteration rather than crashing.
        print(f"[loop] opencode-qwen failed ({e}); treating as no-op", file=sys.stderr)
        return ""
    return _ANSI.sub("", (p.stdout or "") + (p.stderr or ""))


# Categories the proposer may use. PLOT_CATS are graded on the quality ratchet
# (must improve-or-hold the judge mean); the rest are ENGINEERING changes graded on
# score NON-REGRESSION + green tests (their benefit is verified by a human at merge).
PLOT_CATS = {"plot-quality", "bug-fix"}
ENG_CATS = {"speed", "refactor", "robustness", "model"}
ALL_CATS = PLOT_CATS | ENG_CATS


def _extract_json_array(text):
    """Pull the PLAN array out of an opencode-qwen response (which may be fenced, wrapped
    in prose, and contain unrelated bracket literals like `["harness/llm.py"]` in quoted
    code). Returns the parseable array with the MOST dict objects — that's the plan, not a
    stray string-list. Fenced ```json blocks are tried first so they win ties. [] if none."""
    fences = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidates = list(fences)
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
    best, best_dicts = [], 0
    for cand in candidates:
        try:
            v = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(v, list):
            continue
        ndict = sum(1 for x in v if isinstance(x, dict))
        if ndict > best_dicts:  # the array carrying the most objects is the plan
            best, best_dicts = v, ndict
    return best


def propose_plan(context, n=6, attempts=3):
    """STEP 1 — opencode-qwen examines the harness + the context and proposes a RANKED
    PLAN of ALL improvements it considers critical — any size, any category (not just
    small prompt tweaks). Read-only (no edits possible headless without skip-perms).
    Returns a list of item dicts: {title, category, target_files, change, rationale,
    expected_impact, priority}. Retries on a transient empty/unparseable response so a
    single flaky opencode call doesn't end the whole loop."""
    protected_list = "\n".join(f"    {g}" for g in protected_globs())
    prompt = f"""You are improving the `harness/` interactive-story generation engine. Read
harness/AGENTS.md and the context below, examine the relevant harness/ code, and propose
a RANKED PLAN of EVERY change you consider important enough to be worth doing now.

Do NOT limit yourself to small prompt tweaks. Propose whatever genuinely improves the
harness — each item may be large or multi-file. Use these categories:
- "plot-quality"  raise the loop/quality_eval.md PLOT score (prose/skeleton instructions, prompt builders)
- "bug-fix"       a real correctness bug producing wrong/broken output
- "speed"         make generation faster or cheaper (fewer/parallel LLM calls, caching, less redundant work)
- "refactor"      code-health / maintainability with no behavior change
- "robustness"    better error handling, retries, resumability
- "model"         use a better-fitting model for a phase (state which phase + which model + why)

Rank by importance (priority 1 = do first). Prefer high-impact items. It is fine to
return just 1–3 items if only those are truly worth doing.

HARD CONSTRAINTS every item must respect (state how in "change"):
- Edit ONLY harness/ source. These files are PROTECTED — do NOT target them (an item
  that does is dropped without being tried, wasting the slot):
{protected_list}
- NEVER change the JSON schema (`_*_SCHEMA`/minItems/required/enum/properties in llm.py) or the
  eval criteria (loop/quality_eval.md). NEVER hardcode story content. NEVER weaken a test/validator.
- The editable generation dials are: harness/CREATIVE_WRITING_PROSE.md,
  harness/CREATIVE_WRITING_SKELETON.md, the prompt builders in harness/llm.py (NOT its
  schemas) and harness/metadata_fill.py, plus any harness/ source for speed/refactor/robustness.

CONTEXT (last eval deficiencies + backlog + already-tried + recent failures to learn from):
{context}

**PROPOSE ONLY — do not edit any file.** End your response with a single fenced ```json block:
```json
[
  {{"title": "...", "category": "plot-quality|bug-fix|speed|refactor|robustness|model",
    "target_files": ["harness/..."], "change": "concrete what-to-do",
    "rationale": "why it matters", "expected_impact": "what improves", "priority": 1}}
]
```"""
    for attempt in range(1, attempts + 1):
        out = _oc_run(prompt, edit=False, timeout=900)
        items = _extract_json_array(out)
        plan = []
        for it in items[:n]:
            if not isinstance(it, dict) or not it.get("change"):
                continue
            cat = str(it.get("category", "")).strip().lower()
            it["category"] = cat if cat in ALL_CATS else "plot-quality"
            it["title"] = str(it.get("title", it["change"]))[:160]
            plan.append(it)
        if plan:
            plan.sort(key=lambda x: x.get("priority", 99))
            return plan
        print(f"[loop] propose attempt {attempt}/{attempts}: no valid plan parsed "
              f"(raw len={len(out)}); retrying...", file=sys.stderr)
    return []


def _item_text(item):
    """One-line human summary of a plan item for logs/commits."""
    return f"[{item.get('category','?')}] {item.get('title','')}".strip()


def apply_change(item):
    """STEP 2 — opencode-qwen applies ONE plan item (edits enabled). The item may be a
    large/multi-file change, but only this one item is applied per iteration so its
    effect on the eval is attributable and cleanly revertable."""
    protected = "\n".join(protected_globs())
    spec = (item if isinstance(item, str) else
            f"TITLE: {item.get('title')}\nCATEGORY: {item.get('category')}\n"
            f"TARGET FILES: {item.get('target_files')}\nCHANGE: {item.get('change')}\n"
            f"RATIONALE: {item.get('rationale')}\nEXPECTED IMPACT: {item.get('expected_impact')}")
    prompt = f"""Apply EXACTLY the following proposed change to the `harness/` engine as one
coherent diff, then stop. Do NOT run the pipeline. Make the change as large as the proposal
requires, but do not bundle in unrelated edits.

{spec[:4000]}

HARD RULES (the iteration is reverted if any is violated):
- Edit ONLY harness/ source. NEVER edit these:
{protected}
- NEVER change a JSON schema (any `_*_SCHEMA` / minItems / required / enum / properties in llm.py).
- NEVER change the eval criteria (loop/quality_eval.md) or weaken tests/validators.
- NEVER hardcode story content (names/places/dialogue) or fallback prose in code."""
    return _oc_run(prompt, edit=True, timeout=1800)


# ---------- state ----------

def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def ledger_append(rec):
    with open(STATE / "ledger.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _ledger_label(r):
    return r.get("title") or (r.get("proposal", "") or "")[:120]


def build_context(deficiencies, ledger):
    backlog = (STATE / "backlog.md")
    bl = backlog.read_text() if backlog.exists() else "(empty)"
    tried = "\n".join(f"- [{r.get('verdict')}] {_ledger_label(r)}" for r in ledger[-15:])
    # Self-recovery: surface WHY recent attempts were rejected (reason + a detail
    # excerpt) so the next plan doesn't repeat a failing approach and can fix the cause.
    fails = []
    for r in ledger[-20:]:
        if r.get("verdict") == "rejected":
            line = f"- {_ledger_label(r)} → FAILED: {r.get('reason','?')}"
            if r.get("detail"):
                line += f" — {str(r['detail'])[:200]}"
            fails.append(line)
    failblock = "\n".join(fails[-8:]) or "(none)"
    defs = "\n".join(f"- {d}" for d in deficiencies[:15]) or "(none from last eval)"
    return (f"## Last eval deficiencies (PLOT gaps — these raise the score)\n{defs}\n\n"
            f"## Backlog (curated priorities)\n{bl}\n\n"
            f"## Recent FAILURES — learn from these; fix the cause or avoid the approach\n{failblock}\n\n"
            f"## Already tried (do NOT repeat verbatim)\n{tried or '(none)'}")


def _load_fixtures(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        chapters = None
        if "|" in line:
            line, chapters = [p.strip() for p in line.split("|", 1)]
            chapters = chapters or None
        abs_path = line if os.path.isabs(line) else str(ROOT / line)
        if os.path.exists(abs_path):
            items.append({"path": abs_path, "chapters": chapters, "label": os.path.basename(abs_path)})
    return items


def revert_worktree():
    git("reset", "--hard", "HEAD")
    git("clean", "-fd", "harness")


# ---------- bundle + bisect (apply the whole plan, keep the maximal good subset) ----------

def apply_plan_as_commits(base, plan, ledger_append, rnd):
    """Apply EVERY plan item from `base`, each as its own commit (cumulative). Returns a
    list of metas: {item, idx, commit, files, violation}. Items that the proposer says
    target only protected files, that the agent leaves as a no-op, or that introduce a
    guard violation are recorded (violation set) and excluded from the kept-subset search
    — their failure is logged so the next plan learns. The tree ends at the last commit."""
    git("reset", "--hard", base); git("clean", "-fd", "harness")
    metas = []
    for idx, item in enumerate(plan):
        if targets_all_protected(item):
            ledger_append({"round": rnd, "title": _item_text(item), "category": item.get("category"),
                           "verdict": "rejected", "reason": "protected-target",
                           "detail": str(item.get("target_files"))[:200]})
            continue
        before = git("rev-parse", "HEAD")[1].strip()
        apply_change(item)
        files = changed_files()
        if not files:
            ledger_append({"round": rnd, "title": _item_text(item), "verdict": "noop"})
            continue
        _, diff = git("diff", "HEAD")
        violation = guard_violation(files, diff)
        git("add", "-A")
        git("commit", "-q", "-m", f"round {rnd} item {idx}: {_item_text(item)}")
        commit = git("rev-parse", "HEAD")[1].strip()
        if violation:
            # roll this item back out of the cumulative line so it can't taint the rest
            git("reset", "--hard", before); git("clean", "-fd", "harness")
            ledger_append({"round": rnd, "title": _item_text(item), "category": item.get("category"),
                           "files": files, "verdict": "rejected", "reason": violation})
            continue
        metas.append({"item": item, "idx": idx, "commit": commit, "files": files})
    return metas


def group_by_files(metas):
    """Group metas that edit overlapping files (union-find). File-disjoint groups can be
    cherry-picked in any combination WITHOUT conflicts — that's what makes bisection safe
    even though items were applied cumulatively. Returns list of groups (each a meta list,
    kept in original idx order)."""
    parent = list(range(len(metas)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i in range(len(metas)):
        for j in range(i + 1, len(metas)):
            if set(metas[i]["files"]) & set(metas[j]["files"]):
                union(i, j)
    groups = {}
    for i, m in enumerate(metas):
        groups.setdefault(find(i), []).append(m)
    return [sorted(g, key=lambda m: m["idx"]) for g in groups.values()]


def _accept(metas, new, prev_mean, prev_per, eps):
    """Category-aware acceptance for a subset: plot/bug-fix must improve-or-hold the mean;
    a pure-engineering subset need only NOT regress (mean >= best-ε). Floor always holds."""
    floor_ok = all(new["per_story"].get(f, 0.0) >= prev_per.get(f, 0.0) - eps
                   for f in new["per_story"])
    is_plot = any(m["item"].get("category") in PLOT_CATS for m in metas)
    quality_ok = (new["mean"] >= prev_mean) if is_plot else (new["mean"] >= prev_mean - eps)
    return quality_ok and floor_ok


def bisect_groups(base, groups, evaluate_subset, prev_mean, prev_per, eps, max_tests=8):
    """Find the largest set of file-disjoint groups whose combined change is ACCEPTED.
    evaluate_subset(metas) -> (err, new): err is a string if tests/mini broke (or a
    cherry-pick conflict), else None with `new` = the eval dict. Tries the whole set
    first (the common, fast path = 1 eval); on failure splits and recurses, re-testing
    each new union to catch interactions. Memoized by item-set so no subset is ever
    evaluated twice; bounded by max_tests *distinct* evals."""
    budget = [max_tests]
    memo = {}

    def flat(gs):
        return [m for g in gs for m in g]

    def key(gs):
        return frozenset(m["idx"] for m in flat(gs))

    def test(gs):
        k = key(gs)
        if k in memo:
            return memo[k]          # already evaluated this exact subset — free
        if budget[0] <= 0:
            return "budget", None   # out of eval budget → treat as fail (conservative)
        budget[0] -= 1
        memo[k] = evaluate_subset(flat(gs))
        return memo[k]

    def ok(gs, res):
        err, new = res
        return err is None and _accept(flat(gs), new, prev_mean, prev_per, eps)

    def score(res):
        return res[1]["mean"] if res and res[1] else -1e9

    def rec(gs):
        if not gs:
            return [], None
        res = test(gs)
        if ok(gs, res):
            return gs, res[1]
        if len(gs) == 1:
            return [], None         # a single group that doesn't hold on its own → drop it
        mid = len(gs) // 2
        L, lnew = rec(gs[:mid])
        R, rnew = rec(gs[mid:])
        union = L + R
        if not union:
            return [], None
        if L and R and len(union) < len(gs):   # a genuinely new combination → test it
            ures = test(union)
            if ok(union, ures):
                return union, ures[1]
        # union interacts badly (or equals gs) → keep the better passing half
        lr, rr = (None, lnew), (None, rnew)
        if L and R:
            return (L, lnew) if score(lr) >= score(rr) else (R, rnew)
        return (L, lnew) if L else (R, rnew)

    return rec(groups)


def main():
    # Never orphan mini subprocesses if the loop is interrupted/killed.
    atexit.register(_kill_active_minis)
    for _s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(_s, lambda *_a: (_kill_active_minis(), sys.exit(130)))

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-iters", type=int, default=30)
    ap.add_argument("--patience", type=int, default=5, help="stop after N no-improve iters")
    ap.add_argument("--branch", default="loop/auto")
    ap.add_argument("--model", default="deepseek", help="model for real --mini + judge")
    ap.add_argument("--fast-only", action="store_true", help="skip real --mini; gate on tests + det eval")
    ap.add_argument("--epsilon", type=float, default=3.0,
                    help="per-story floor tolerance: a genre may dip this far below its best (absorbs judge noise)")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="don't call the fixer; just baseline + exit")
    a = ap.parse_args()

    STATE.mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT))

    # Isolation: require a clean tree, then move to the loop branch.
    if changed_files():
        print("ERROR: working tree not clean. Commit/stash before running the loop.")
        sys.exit(1)
    git("rev-parse", "--verify", a.branch)
    rc, _ = git("checkout", a.branch)
    if rc != 0:
        git("checkout", "-b", a.branch)
    print(f"[loop] on branch {a.branch}")

    best = load_json(STATE / "best.json", {})
    ledger = [json.loads(l) for l in (STATE / "ledger.jsonl").read_text().splitlines()] \
        if (STATE / "ledger.jsonl").exists() else []

    fixtures = [l.strip() for l in (LOOP / "fixtures.txt").read_text().splitlines()
                if l.strip() and not l.strip().startswith("#")]
    fixtures = [f for f in fixtures if os.path.exists(f if os.path.isabs(f) else ROOT / f)]
    if not fixtures:
        print("ERROR: no usable fixtures in loop/fixtures.txt"); sys.exit(1)
    full_fixtures = _load_fixtures(LOOP / "full_fixtures.txt")

    def save_best():
        (STATE / "best.json").write_text(json.dumps(best, ensure_ascii=False, indent=2))

    if full_fixtures:
        current_full = {fx["path"] for fx in full_fixtures}
        saved_full = set((best.get("full_per_story") or {}).keys())
        if saved_full and saved_full != current_full:
            for key in ("full_mean", "full_per_story", "full_deficiencies"):
                best.pop(key, None)
            save_best()

    # Baseline: run ALL fixtures in parallel; the combined signal is their mean.
    if "mean" not in best and not a.fast_only:
        print(f"[loop] establishing baseline ({len(fixtures)} fixtures in parallel)...")
        r = real_eval_all(fixtures, a.model, not a.no_judge)
        best = {"mean": r["mean"], "per_story": r["per_story"],
                "commit": git("rev-parse", "HEAD")[1].strip(), "deficiencies": r["deficiencies"]}
        save_best()
        print(f"[loop] baseline mean={best['mean']} per_story={best['per_story']}")
    last_defs = best.get("deficiencies", [])
    last_full_defs = best.get("full_deficiencies", [])

    if full_fixtures and "full_mean" not in best and not a.fast_only:
        print(f"[loop] establishing full-run baseline ({len(full_fixtures)} fixture(s))...")
        fr = real_eval_full_all(full_fixtures, a.model)
        best["full_mean"] = fr["mean"]
        best["full_per_story"] = fr["per_story"]
        best["full_deficiencies"] = fr["deficiencies"]
        last_full_defs = fr["deficiencies"]
        save_best()
        print(f"[loop] baseline full_mean={best.get('full_mean')} full_per_story={best.get('full_per_story')}")

    if a.dry_run:
        print("[loop] dry-run: baseline only, exiting."); return

    # Each ROUND: propose the full plan → apply EVERY item (cumulative commits) → drop
    # guard-violating / no-op / protected-target items → group file-disjoint items →
    # BISECT for the maximal subset that holds quality → commit it. Bundle holds ⇒ 1 eval
    # (fast, reaches the big items); only a regression triggers bisection (extra evals) to
    # isolate and drop the culprit while keeping the rest. Failures feed the next plan.
    def save_plan(plan):
        (STATE / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))

    no_improve = 0
    for rnd in range(1, a.max_iters + 1):
        if no_improve >= a.patience:
            print(f"[loop] converged: {a.patience} rounds with no quality improvement."); break
        base = git("rev-parse", "HEAD")[1].strip()

        ctx = build_context(last_defs + last_full_defs, ledger)
        plan = propose_plan(ctx)
        if not plan:
            print("[loop] proposer returned no actionable items; stopping."); break
        save_plan(plan)
        print(f"\n===== round {rnd}/{a.max_iters} (best_mean={best.get('mean')}, "
              f"no_improve={no_improve}) =====")
        print(f"[loop] plan ({len(plan)} items): " + " | ".join(_item_text(p) for p in plan))
        ledger_append({"round": rnd, "verdict": "plan", "items": [_item_text(p) for p in plan]})

        # Apply every item as its own cumulative commit; drop violators/no-ops.
        metas = apply_plan_as_commits(base, plan, ledger_append, rnd)
        git("reset", "--hard", base); git("clean", "-fd", "harness")
        if not metas:
            print("[loop] no applicable items (all protected-target / no-op / guard) — next round.")
            no_improve += 1; continue

        # Group file-disjoint items so any subset can be cherry-picked conflict-free.
        groups = group_by_files(metas)
        prev_mean = best.get("mean", 0.0); prev_per = best.get("per_story", {})
        prev_full_mean = best.get("full_mean", 0.0); prev_full_per = best.get("full_per_story", {})
        print(f"[loop] {len(metas)} item(s) in {len(groups)} disjoint group(s); "
              f"applying the bundle and bisecting if it regresses...")

        def evaluate_subset(subset_metas):
            """Reset to base, cherry-pick this subset (file-disjoint ⇒ no conflicts),
            verify + eval. Returns (err, new); err set on conflict / tests / mini fail."""
            git("reset", "--hard", base); git("clean", "-fd", "harness")
            for m in sorted(subset_metas, key=lambda m: m["idx"]):
                rc, _ = git("cherry-pick", m["commit"])
                if rc != 0:
                    git("cherry-pick", "--abort")
                    return "cherry-pick-conflict", None
            ok, summ = fast_verify()
            if not ok:
                return "tests:" + summ[-200:], None
            if a.fast_only:
                return None, {"mean": prev_mean, "per_story": prev_per,
                              "deficiencies": last_defs, "failed": [],
                              "full_mean": prev_full_mean, "full_per_story": prev_full_per,
                              "full_deficiencies": last_full_defs}
            new = real_eval_all(fixtures, a.model, not a.no_judge)
            if new["failed"]:
                return "mini-failed:" + str(new["failed"]), None
            if full_fixtures:
                fr = real_eval_full_all(full_fixtures, a.model)
                new["full_mean"] = fr["mean"]
                new["full_per_story"] = fr["per_story"]
                new["full_deficiencies"] = fr["deficiencies"]
            else:
                new["full_mean"] = prev_full_mean
                new["full_per_story"] = prev_full_per
                new["full_deficiencies"] = last_full_defs
            return None, new

        def accept_subset(metas_subset, new):
            mini_ok = _accept(metas_subset, new, prev_mean, prev_per, a.epsilon)
            if not full_fixtures:
                return mini_ok
            full_prev = prev_full_mean
            full_per = prev_full_per
            full_ok = all(new["full_per_story"].get(f, 0.0) >= full_per.get(f, 0.0) - a.epsilon
                          for f in new["full_per_story"])
            is_plot = any(m["item"].get("category") in PLOT_CATS for m in metas_subset)
            full_quality_ok = (new["full_mean"] >= full_prev) if is_plot else (new["full_mean"] >= full_prev - a.epsilon)
            return mini_ok and full_ok and full_quality_ok

        def bisect_groups_full(base, groups, evaluate_subset, prev_mean, prev_per, eps, max_tests=8):
            # Wrapper around the existing bisection that also respects the full-run gate.
            def _accept_full(gs, res):
                err, new = res
                return err is None and accept_subset(flat(gs), new)

            # Reuse existing recursion by temporarily swapping the acceptance predicate
            budget = [max_tests]
            memo = {}

            def flat(gs):
                return [m for g in gs for m in g]

            def key(gs):
                return frozenset(m["idx"] for m in flat(gs))

            def test(gs):
                k = key(gs)
                if k in memo:
                    return memo[k]
                if budget[0] <= 0:
                    return "budget", None
                budget[0] -= 1
                memo[k] = evaluate_subset(flat(gs))
                return memo[k]

            def score(res):
                return res[1]["mean"] if res and res[1] else -1e9

            def rec(gs):
                if not gs:
                    return [], None
                res = test(gs)
                if _accept_full(gs, res):
                    return gs, res[1]
                if len(gs) == 1:
                    return [], None
                mid = len(gs) // 2
                L, lnew = rec(gs[:mid])
                R, rnew = rec(gs[mid:])
                union = L + R
                if not union:
                    return [], None
                if L and R and len(union) < len(gs):
                    ures = test(union)
                    if _accept_full(union, ures):
                        return union, ures[1]
                lr, rr = (None, lnew), (None, rnew)
                if L and R:
                    return (L, lnew) if score(lr) >= score(rr) else (R, rnew)
                return (L, lnew) if L else (R, rnew)

            return rec(groups)

        kept_groups, new = bisect_groups_full(base, groups, evaluate_subset,
                                              prev_mean, prev_per, a.epsilon)
        kept = sorted([m for g in kept_groups for m in g], key=lambda m: m["idx"])
        kept_idx = {m["idx"] for m in kept}
        dropped = [m for m in metas if m["idx"] not in kept_idx]

        # Finalize: rebuild the kept subset cleanly on base.
        git("reset", "--hard", base); git("clean", "-fd", "harness")
        if not kept or new is None:
            print(f"[loop] REJECT round {rnd}: no subset held quality — staying at {base[:8]}.")
            ledger_append({"round": rnd, "verdict": "rejected", "reason": "no-subset-held",
                           "tried": [_item_text(m["item"]) for m in metas]})
            no_improve += 1; continue
        for m in kept:
            git("cherry-pick", m["commit"])
        commit = git("rev-parse", "HEAD")[1].strip()
        print(f"[loop] ACCEPT round {rnd}: kept {len(kept)}/{len(metas)} item(s) "
              f"(mean {new['mean']} vs {prev_mean}, per_story {new['per_story']}" +
              (f", full_mean {new.get('full_mean')} vs {prev_full_mean}, full_per_story {new.get('full_per_story')}" if full_fixtures else "") +
              "); "
              f"dropped {len(dropped)}; committed {commit[:8]}.")
        if new["mean"] > prev_mean:        # quality improvement → raise the bar, reset patience
            best = {"mean": new["mean"], "per_story": new["per_story"], "commit": commit,
                    "deficiencies": new["deficiencies"],
                    "full_mean": new.get("full_mean", prev_full_mean),
                    "full_per_story": new.get("full_per_story", prev_full_per),
                    "full_deficiencies": new.get("full_deficiencies", last_full_defs)}
            last_defs = new["deficiencies"]; no_improve = 0
        else:                              # engineering / neutral hold → keep bar, count toward patience
            best["commit"] = commit; no_improve += 1
            if full_fixtures:
                best["full_mean"] = new.get("full_mean", prev_full_mean)
                best["full_per_story"] = new.get("full_per_story", prev_full_per)
                best["full_deficiencies"] = new.get("full_deficiencies", last_full_defs)
                last_full_defs = new.get("full_deficiencies", last_full_defs)
        save_best()
        for m in kept:
            ledger_append({"round": rnd, "title": _item_text(m["item"]),
                           "category": m["item"].get("category"), "files": m["files"],
                           "verdict": "accepted", "commit": commit,
                           "mean": new["mean"], "per_story": new["per_story"],
                           "full_mean": new.get("full_mean"), "full_per_story": new.get("full_per_story")})
        for m in dropped:
            ledger_append({"round": rnd, "title": _item_text(m["item"]),
                           "category": m["item"].get("category"), "files": m["files"],
                           "verdict": "rejected", "reason": "bisected-out",
                           "detail": f"regressed or broke tests inside the bundle (target mean {prev_mean})"})

    print(f"\n[loop] done. best mean = {best.get('mean')} on {best.get('commit','')[:8]} "
          f"(branch {a.branch}). Review and merge manually.")


if __name__ == "__main__":
    main()
