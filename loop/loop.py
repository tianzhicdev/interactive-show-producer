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
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Don't let a hung/slow subprocess (e.g. pytest during a network outage)
        # crash the whole loop — surface it as a non-zero result the caller handles.
        return 124, f"TIMEOUT after {timeout}s: {cmd}"
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {cmd}\n{p.stderr[-2000:]}")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


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


# ---------- verification ----------

def _pytest(timeout):
    return sh([sys.executable, "-m", "pytest", "harness/", "-q",
               "-p", "no:cacheprovider"], timeout=timeout)


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
    """Pull the LAST top-level JSON array out of an opencode-qwen response (it may be
    fenced, prefixed with prose, or followed by a tool trace). Returns [] on failure."""
    # Prefer a ```json fenced block; else scan for the last balanced [...] array.
    fences = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidates = list(fences)
    # Also try every '[' as a start of a balanced array (last one wins).
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
    for cand in reversed(candidates):
        try:
            v = json.loads(cand)
            if isinstance(v, list) and v:
                return v
        except json.JSONDecodeError:
            continue
    return []


def propose_plan(context, n=6):
    """STEP 1 — opencode-qwen examines the harness + the context and proposes a RANKED
    PLAN of ALL improvements it considers critical — any size, any category (not just
    small prompt tweaks). Read-only (no edits possible headless without skip-perms).
    Returns a list of item dicts: {title, category, target_files, change, rationale,
    expected_impact, priority}."""
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
- Edit ONLY harness/ source. NEVER tests, validators, JSON schemas, the grading .md files, or loop/.
- NEVER change the JSON schema (`_*_SCHEMA`/minItems/required/enum/properties in llm.py) or the
  eval criteria (loop/quality_eval.md). NEVER hardcode story content. NEVER weaken a test/validator.

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
    plan.sort(key=lambda x: x.get("priority", 99))
    return plan


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


def revert_worktree():
    git("reset", "--hard", "HEAD")
    git("clean", "-fd", "harness")


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

    def save_best():
        (STATE / "best.json").write_text(json.dumps(best, ensure_ascii=False, indent=2))

    # Baseline: run ALL fixtures in parallel; the combined signal is their mean.
    if "mean" not in best and not a.fast_only:
        print(f"[loop] establishing baseline ({len(fixtures)} fixtures in parallel)...")
        r = real_eval_all(fixtures, a.model, not a.no_judge)
        best = {"mean": r["mean"], "per_story": r["per_story"],
                "commit": git("rev-parse", "HEAD")[1].strip(), "deficiencies": r["deficiencies"]}
        save_best()
        print(f"[loop] baseline mean={best['mean']} per_story={best['per_story']}")
    last_defs = best.get("deficiencies", [])

    if a.dry_run:
        print("[loop] dry-run: baseline only, exiting."); return

    # Work queue: the proposer surfaces ALL critical items up front (plan.json); the
    # loop applies ONE per iteration (attributable + revertable) and refreshes the plan
    # when the queue drains. A rejected item's failure detail is fed back via the ledger.
    plan = load_json(STATE / "plan.json", [])

    def save_plan():
        (STATE / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))

    def reject(it, item, reason, files=None, detail="", **extra):
        print(f"[loop] REJECT ({reason}) — reverting" + (f"\n{str(detail)[:400]}" if detail else ""))
        revert_worktree()
        ledger_append({"iter": it, "title": _item_text(item), "category": item.get("category"),
                       "files": files or item.get("target_files"),
                       "verdict": "rejected", "reason": reason, "detail": str(detail)[:600], **extra})

    no_improve = 0
    for it in range(1, a.max_iters + 1):
        if no_improve >= a.patience:
            print(f"[loop] converged: {a.patience} iterations with no improvement."); break

        # STEP 1 — PROPOSE A PLAN when the queue is empty (opencode-qwen, read-only).
        # All critical items are surfaced at once; failures feed back into the next plan.
        if not plan:
            ctx = build_context(last_defs, ledger)
            plan = propose_plan(ctx)
            save_plan()
            if not plan:
                print("[loop] proposer returned no actionable items; stopping."); break
            print(f"[loop] new plan ({len(plan)} items): " +
                  " | ".join(_item_text(p) for p in plan))
            ledger_append({"iter": it, "verdict": "plan", "items": [_item_text(p) for p in plan]})

        item = plan.pop(0); save_plan()
        print(f"\n===== iteration {it}/{a.max_iters} (best_mean={best.get('mean')}, "
              f"no_improve={no_improve}) =====\n[loop] item: {_item_text(item)}")

        # STEP 2 — APPLY one item (opencode-qwen, edits enabled)
        apply_change(item)
        files = changed_files()
        if not files:
            print("[loop] apply made no change; skipping."); no_improve += 1
            ledger_append({"iter": it, "title": _item_text(item), "verdict": "noop"}); continue

        # 3. GUARD: protected files + gate H + schema lock
        prot = touches_protected(files)
        _, diff = git("diff", "HEAD")
        gh = gate_h_violation(diff)
        sch = schema_edit_violation(diff)
        if prot or gh or sch:
            reason = (("protected:" + ",".join(prot)) if prot
                      else ("gate-H:" + "; ".join(gh[:2])) if gh
                      else ("schema-edit:" + "; ".join(sch[:2])))
            reject(it, item, reason, files=files); no_improve += 1; continue

        # 4. VERIFY-FAST (tests/fake). The full failure summary is logged so the next
        #    plan can see exactly what broke and self-correct.
        ok, summ = fast_verify()
        if not ok:
            reject(it, item, "tests", files=files, detail=summ); no_improve += 1; continue

        # 5. VERIFY-REAL: all fixtures in parallel → mean + per-story scores
        if a.fast_only:
            new = {"mean": best.get("mean", 0.0), "per_story": best.get("per_story", {}),
                   "deficiencies": last_defs, "failed": []}
        else:
            new = real_eval_all(fixtures, a.model, not a.no_judge)
            if new["failed"]:  # a change that breaks ANY genre's pipeline = reject
                reject(it, item, "mini-failed", files=files, detail=new["failed"],
                       per_story=new["per_story"]); no_improve += 1; continue

        # 6. ACCEPTANCE — category-aware (see PLOT_CATS / ENG_CATS):
        #    plot/bug-fix must improve-or-hold the mean; engineering changes need only
        #    NOT regress quality (mean >= best-ε, floor holds) — their benefit is the
        #    proposer's claim, verified by a human before merge.
        prev_mean = best.get("mean", 0.0)
        prev_per = best.get("per_story", {})
        is_plot = item.get("category") in PLOT_CATS
        floor_ok = all(new["per_story"].get(f, 0.0) >= prev_per.get(f, 0.0) - a.epsilon
                       for f in new["per_story"])
        quality_ok = (new["mean"] >= prev_mean) if is_plot else (new["mean"] >= prev_mean - a.epsilon)

        if quality_ok and floor_ok:
            git("add", "-A")
            git("commit", "-q", "-m",
                f"loop iter {it}: {_item_text(item)} (mean {new['mean']} vs {prev_mean})")
            commit = git("rev-parse", "HEAD")[1].strip()
            if new["mean"] > prev_mean:  # quality improvement → raise the bar
                best = {"mean": new["mean"], "per_story": new["per_story"], "commit": commit,
                        "deficiencies": new["deficiencies"]}
                last_defs = new["deficiencies"]
            else:                        # engineering / neutral hold → keep the bar, log commit
                best["commit"] = commit
            save_best()
            print(f"[loop] ACCEPT [{item.get('category')}] — mean {new['mean']} "
                  f"(per_story {new['per_story']}), committed {commit[:8]}.")
            ledger_append({"iter": it, "title": _item_text(item), "category": item.get("category"),
                           "files": files, "verdict": "accepted", "commit": commit,
                           "mean": new["mean"], "per_story": new["per_story"]})
            no_improve = 0  # any accepted improvement is progress
        else:
            reason = "regress-mean" if new["mean"] < prev_mean - (0 if is_plot else a.epsilon) \
                     else "per-story-floor"
            reject(it, item, reason, files=files,
                   detail=f"mean {new['mean']} vs {prev_mean}, per_story {new['per_story']}",
                   mean=new["mean"], per_story=new["per_story"])
            no_improve += 1

    print(f"\n[loop] done. best mean = {best.get('mean')} on {best.get('commit','')[:8]} "
          f"(branch {a.branch}). Review and merge manually.")


if __name__ == "__main__":
    main()
