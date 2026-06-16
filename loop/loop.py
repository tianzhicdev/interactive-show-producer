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

def fast_verify():
    """Unit tests + fake full run + fake mini. Returns (ok, summary)."""
    rc, out = sh([sys.executable, "-m", "pytest", "harness/", "-q"], timeout=600)
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


def propose(context):
    """STEP 1 — opencode-qwen examines the last eval feedback + the code and proposes
    ONE concrete change. Read-only (no edits possible headless without skip-perms)."""
    prompt = f"""You improve the `harness/` story-generation engine toward loop/quality_eval.md.
Read harness/AGENTS.md and the context below, examine the relevant harness/ code, and
propose EXACTLY ONE small, concrete change (a real bug or a quality/conformance gap
that should raise the PLOT eval score). Output a short proposal: target file(s), the
change, and why. **PROPOSE ONLY — do not edit any file.**

The change MUST respect (state how in your proposal):
- Edit only harness/ source — NOT tests, validators, JSON schemas, instruction .md, or loop/.
- Do NOT change the JSON schema or the eval criteria (loop/quality_eval.md). No hardcoded story content.

CONTEXT (last eval deficiencies + backlog + already-tried — do not repeat tried items):
{context}

End your response with the proposal as a block beginning with a line `PROPOSAL:`
(name the target file(s), the concrete change, and the expected eval improvement)."""
    out = _oc_run(prompt, edit=False, timeout=900)
    idx = out.rfind("PROPOSAL:")
    block = out[idx:] if idx >= 0 else out[-2000:]
    # Stop at the first opencode tool-trace / session line so the proposal is clean.
    lines = []
    for ln in block.splitlines():
        if lines and (re.match(r"^\s*[>→✱✗•]", ln) or ln.startswith("Error:") or "qwen3-coder" in ln):
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def apply_change(proposal):
    """STEP 2 — opencode-qwen applies the proposed change (edits enabled)."""
    protected = "\n".join(protected_globs())
    prompt = f"""Apply EXACTLY the following proposed change to the `harness/` engine as the
smallest coherent diff, then stop. Do NOT run the pipeline.

PROPOSAL:
{proposal[:4000]}

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


def build_context(deficiencies, ledger):
    backlog = (STATE / "backlog.md")
    bl = backlog.read_text() if backlog.exists() else "(empty)"
    tried = "\n".join(f"- [{r['verdict']}] {r['proposal'][:120]}" for r in ledger[-12:])
    defs = "\n".join(f"- {d}" for d in deficiencies[:15]) or "(none from last eval)"
    return (f"## Last eval deficiencies (fix these first)\n{defs}\n\n"
            f"## Backlog (curated)\n{bl}\n\n## Already tried (do NOT repeat)\n{tried or '(none)'}")


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

    no_improve = 0
    for it in range(1, a.max_iters + 1):
        if no_improve >= a.patience:
            print(f"[loop] converged: {a.patience} iterations with no improvement."); break
        print(f"\n===== iteration {it}/{a.max_iters} (best_mean={best.get('mean')}, no_improve={no_improve}) =====")

        # STEP 1 — EXAMINE + PROPOSE (opencode-qwen, read-only)
        ctx = build_context(last_defs, ledger)
        proposal = propose(ctx)
        print(f"[loop] proposal: {' '.join(proposal.split())[:200]}")
        # STEP 2 — APPLY (opencode-qwen, edits enabled)
        apply_change(proposal)
        files = changed_files()
        if not files:
            print("[loop] apply made no change; skipping."); no_improve += 1
            ledger_append({"iter": it, "proposal": proposal, "verdict": "noop"}); continue

        # 3. GUARD: protected files + gate H
        prot = touches_protected(files)
        _, diff = git("diff", "HEAD")
        gh = gate_h_violation(diff)
        sch = schema_edit_violation(diff)
        if prot or gh or sch:
            reason = (("protected:" + ",".join(prot)) if prot
                      else ("gate-H:" + "; ".join(gh[:2])) if gh
                      else ("schema-edit:" + "; ".join(sch[:2])))
            print(f"[loop] REJECT ({reason}) — reverting"); revert_worktree()
            ledger_append({"iter": it, "proposal": proposal, "files": files,
                           "verdict": "rejected", "reason": reason}); no_improve += 1; continue

        # 4. VERIFY-FAST
        ok, summ = fast_verify()
        if not ok:
            print(f"[loop] REJECT (tests) — reverting\n{summ[:400]}"); revert_worktree()
            ledger_append({"iter": it, "proposal": proposal, "files": files,
                           "verdict": "rejected", "reason": "tests"}); no_improve += 1; continue

        # 5. VERIFY-REAL: all fixtures in parallel → mean + per-story scores
        if a.fast_only:
            new = {"mean": best.get("mean", 0.0), "per_story": best.get("per_story", {}),
                   "deficiencies": last_defs, "failed": []}
        else:
            new = real_eval_all(fixtures, a.model, not a.no_judge)
            if new["failed"]:  # a fix that breaks ANY genre's pipeline = reject
                print(f"[loop] REJECT (mini failed: {new['failed']}) — reverting"); revert_worktree()
                ledger_append({"iter": it, "proposal": proposal, "files": files,
                               "verdict": "rejected", "reason": "mini-failed"}); no_improve += 1; continue

        # 6. RATCHET: mean must not drop AND no genre may fall below its floor (best - ε)
        prev_mean = best.get("mean", 0.0)
        prev_per = best.get("per_story", {})
        floor_ok = all(new["per_story"].get(f, 0.0) >= prev_per.get(f, 0.0) - a.epsilon
                       for f in new["per_story"])
        if new["mean"] >= prev_mean and floor_ok:
            git("add", "-A")
            git("commit", "-q", "-m", f"loop iter {it}: {proposal} (mean {new['mean']} >= {prev_mean})")
            best = {"mean": new["mean"], "per_story": new["per_story"],
                    "commit": git("rev-parse", "HEAD")[1].strip(), "deficiencies": new["deficiencies"]}
            save_best(); last_defs = new["deficiencies"]
            print(f"[loop] ACCEPT — mean {new['mean']} (per_story {new['per_story']}), committed.")
            ledger_append({"iter": it, "proposal": proposal, "files": files,
                           "verdict": "accepted", "mean": new["mean"], "per_story": new["per_story"]})
            no_improve = 0 if new["mean"] > prev_mean else no_improve + 1
        else:
            reason = "mean" if new["mean"] < prev_mean else "per-story-floor"
            print(f"[loop] REJECT ({reason}: mean {new['mean']} vs {prev_mean}, "
                  f"per_story {new['per_story']}) — reverting"); revert_worktree()
            ledger_append({"iter": it, "proposal": proposal, "files": files, "verdict": "rejected",
                           "reason": reason, "mean": new["mean"], "per_story": new["per_story"]})
            no_improve += 1

    print(f"\n[loop] done. best mean = {best.get('mean')} on {best.get('commit','')[:8]} "
          f"(branch {a.branch}). Review and merge manually.")


if __name__ == "__main__":
    main()
