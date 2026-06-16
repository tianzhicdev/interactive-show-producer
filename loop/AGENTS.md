# loop/AGENTS.md — The Harness Auto-Improvement Loop

A supervised hill-climbing loop that incrementally improves the harness. Each round it
**proposes a ranked PLAN** of *every* improvement it considers important — any size, any
category (plot-quality, real bug-fixes, **speed, refactors, robustness, better-fit
models**) — **applies the whole plan** with a headless **`opencode-qwen`** agent
(Qwen3-Coder via OpenRouter), verifies it (unit + fake + a **real** `--mini` per fixture
**evaluated by Fireworks deepseek**), and **keeps the largest subset that didn't regress**
the measured plot quality.

It is NOT limited to small prompt tweaks, and it is NOT one-change-at-a-time. The whole
plan is applied as a bundle and evaluated in ONE pass (fast; reaches the big items).
**Only if the bundle regresses** does it **bisect** — splitting the plan to isolate and
drop the culprit while keeping the rest. Items are grouped by the files they touch so any
subset can be rebuilt conflict-free (file-disjoint groups, cherry-picked onto base).

Tooling split: **opencode-qwen** does the code edits (steps 1–2); **Fireworks
deepseek** runs the mini generations + the plot judge (step 3). They are separate
on purpose — the editor and the grader are different models.

It is NOT a "let an AI rewrite the codebase" loop. It is a ratcheted optimizer with
a fixed, human-owned objective and hard anti-cheating guardrails.

---

## The loop (one iteration)

```
0. Start clean on the `loop/auto` branch (or a worktree). Baseline = best-so-far.
1. PLAN     — when the queue is empty, `opencode-qwen run` (read-only: no
              --dangerously-skip-permissions, so it CANNOT edit headless) examines
              harness/AGENTS.md, quality_eval.md, the LAST eval's deficiencies, the
              tried-ledger, AND recent FAILURES (reason + detail), and emits a ranked
              JSON PLAN of every change worth doing now — each tagged with a category
              (plot-quality | bug-fix | speed | refactor | robustness | model), target
              files, the change, rationale, expected impact, priority. Saved to plan.json.
2. APPLY    — `opencode-qwen run ... --dangerously-skip-permissions` applies EVERY plan
              item (each its own cumulative commit). Items targeting only protected files
              are pre-filtered; no-op and guard-violating items are dropped + logged.
2b.GROUP    — group the surviving items by the files they touch (file-disjoint groups).
3. BISECT   — evaluate the whole bundle in ONE pass. If it holds (no regression, tests
              green, per-genre floor ok) → keep ALL. If it regresses → split groups and
              re-evaluate to isolate the culprit(s); keep the largest accepted subset.
              Memoized so no subset is evaluated twice; bounded eval budget.
3. GUARD    — if the diff touched any PROTECTED file → revert + log "protected".
              If gate H (no hardcoded story content) fails → revert + log "gate-H".
4. VERIFY-FAST — `pytest harness/` + a fake-LLM full run + fake mini.
              Any failure → revert + log "tests".
5. VERIFY-REAL — run a real `--mini` on **ALL** rotation stories **in parallel**
              (sub-runs forced to PROSE/INGEST workers = 1 to bound concurrency),
              then score each with `loop/eval.py` against quality_eval.md.
              The iteration's signal = the **mean** of the per-story scores.
              Any sub-run that crashes → automatic REJECT (broke a genre).
6. ACCEPT   — CATEGORY-AWARE (see below). Guards + tests + per-genre floor always
              required. ACCEPT → commit to `loop/auto`; else REVERT → `git reset
              --hard HEAD` + clean, and the failure (reason + detail) is logged.
7. Feed this round's deficiencies AND failures into the next PLAN. Repeat.
```

## Acceptance rule (category-aware ratchet)
The per-iteration quality signal is the **mean across the FULL rotating set, run in
parallel** (never one story — that overfits + is high-variance). Every accepted change
must keep tests green, pass the guards, and keep **no genre below its floor**
`best_per_story[g] − ε` (default ε=3, absorbs LLM-judge noise). On top of that:

- **plot-quality / bug-fix** items must **improve-or-hold** the mean (`new_mean ≥
  best_mean`). A strict improvement raises the bar (`best.mean`).
- **speed / refactor / robustness / model** items need only **NOT regress** quality
  (`new_mean ≥ best_mean − ε`, floor holds). They do NOT lower `best.mean` (the quality
  bar is a high-water mark). Their engineering benefit is the proposer's *claim*,
  recorded in the ledger and **verified by the human at merge** — auto-gating speed on a
  *real* mini's wall-clock is unreliable (network-latency noise).

This lets quality climb, lets the harness get faster/cleaner without quality loss, and
**forbids trading one genre for another**. Patience resets on any ACCEPT; everything
else is `git reset --hard`-reverted, zero residue. The anti-cheat guarantee is intact:
*the loop can never degrade measured output quality or weaken a test/validator/schema.*

## PROTECTED files — the loop may NEVER auto-edit these
The loop is graded against these; letting it edit them = moving the goal posts /
deleting the exam. Listed in `loop/protected.txt`; enforced by the GUARD step.
- `loop/quality_eval.md` — the objective
- `loop/**` — the loop's own machinery (no self-modification)
- `harness/test_*.py` — can't pass tests by weakening them
- `harness/fake_llm.py` — can't force green by tweaking canned output
- `harness/validation.py` — D-check gates; can't loosen to "pass"
- `harness/VALIDATION.md` (S-judge rules), `harness/CHOICE_DESIGN.md` &
  `harness/DRAMATIC_STRUCTURE.md` (rules the judge/validators grade against),
  `harness/AGENTS.md` — the GRADING and the spec; can't soften what's measured
- JSON schema definitions in `harness/llm.py` — locked by the schema-edit guard

**Editable** (the generation dials the loop SHOULD turn to raise plot quality — it
can't cheat, since weakening them lowers the judge's score and gets reverted):
`harness/CREATIVE_WRITING_PROSE.md`, `harness/CREATIVE_WRITING_SKELETON.md`, and the
prompt builders in `harness/llm.py` / `harness/metadata_fill.py`.

> The loop MAY *propose* changes to protected files — those go to a human-review
> queue (`loop/state/needs_human.md`), never auto-applied.

## Scope of changes (what the loop works on)
Anything important to the harness. The proposer ranks across these categories:
1. **plot-quality** — raise the `quality_eval.md` score (prose/skeleton instructions,
   prompt builders, eval-driven deficiencies from the last `--mini`).
2. **bug-fix** — real correctness bugs producing wrong/broken output; AGENTS.md
   conformance (hardcoded content, non-skeleton plot source, fallback prose).
3. **speed** — faster/cheaper generation (fewer/parallel LLM calls, caching, less work).
4. **refactor** — code health / maintainability with no behavior change.
5. **robustness** — error handling, retries, resumability.
6. **model** — use a better-fitting model for a phase.

Each item still edits **harness/ source only**, never the protected grading/spec/schema
files. Engineering items (3–6) are gated on quality non-regression + green tests, with
the benefit confirmed at human review.

## Anti-reward-hacking invariants (non-negotiable)
- The fitness signal lives in PROTECTED files; the loop can't touch them.
- A change that makes tests pass by removing/weakening a test or validator is
  caught by the GUARD step (protected) and reverted.
- The hard gate H (no hardcoded story content) runs every iteration across the
  rotation; a one-genre hack that regresses another story is rejected.
- Reverts are real `git` reverts — a rejected change leaves zero residue.

## Isolation & safety
- Runs on the `loop/auto` branch (or a git worktree), **never `main`**, **never
  pushes**. A human reviews/merges `loop/auto` later.
- Every accepted change is its own commit with the proposal + score in the message.
- The harness's `--cc`/Fireworks calls bill the usual way; see cost below.

## Termination
Stop when ANY of:
- `MAX_ITERS` reached (default 30), or
- the time/credit budget is spent, or
- **K consecutive iterations with no accepted improvement** (default K=5) →
  converged; nothing left to climb with the current rubric/backlog.

## Cost & cadence (be honest)
A real `--mini` is ~15–25 min + Fireworks/Agent-SDK credit. With fix + eval, one
iteration ≈ 25–40 min. Overnight ≈ 15–30 iterations. The ratchet matters *more*
the slower each iteration is — a wrongly-accepted regression is expensive to
discover. Use `--fast-only` (skip the real `--mini`, gate on tests + deterministic
eval only) for cheap dry-runs while developing the loop itself.

## State (loop/state/)
- `best.json` — best score so far + the commit that achieved it
- `ledger.jsonl` — every proposal: {iter, proposal, files, verdict, reason, score}
- `backlog.md` — curated work items (human-editable)
- `needs_human.md` — proposals that would touch protected files (for human review)
- `iter_NNN/` — per-iteration artifacts (diff, eval json, mini run dir pointer)

## Files
- `loop.py` — the orchestrator (the while loop above)
- `eval.py` — runs/parses a `--mini`, scores vs quality_eval.md → (score, deficiencies)
- `fixtures.txt` — the rotating story set (one path per line; `#` comments)
- `protected.txt` — glob list of files the loop may not edit
- `quality_eval.md` — the objective (PROTECTED)

## For the human operator
- Read `loop/state/ledger.jsonl` to see what was tried and why each was kept/cut.
- Review `loop/auto` before merging to `main`; the loop never merges for you.
- Edit `quality_eval.md` to change what "better" means; edit `backlog.md` to
  steer what it works on; edit `fixtures.txt` to change the genre coverage.
- Kill it anytime; state is checkpointed each iteration and it resumes from
  `best.json` + `ledger.jsonl`.
