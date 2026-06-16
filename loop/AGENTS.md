# loop/AGENTS.md — The Harness Auto-Improvement Loop

A supervised hill-climbing loop that incrementally improves the harness toward
`loop/quality_eval.md`. It **proposes** one change and **applies** it with a headless
**`opencode-qwen`** agent (Qwen3-Coder via OpenRouter), verifies it (unit + fake +
a **real** `--mini` per fixture **evaluated by Fireworks deepseek**), scores the
result against the goal post, and **keeps the change only if it didn't regress**.

Tooling split: **opencode-qwen** does the code edits (steps 1–2); **Fireworks
deepseek** runs the mini generations + the plot judge (step 3). They are separate
on purpose — the editor and the grader are different models.

It is NOT a "let an AI rewrite the codebase" loop. It is a ratcheted optimizer with
a fixed, human-owned objective and hard anti-cheating guardrails.

---

## The loop (one iteration)

```
0. Start clean on the `loop/auto` branch (or a worktree). Baseline = best-so-far.
1. PROPOSE  — `opencode-qwen run` (read-only: no --dangerously-skip-permissions, so
              it CANNOT edit headless) examines harness/AGENTS.md, quality_eval.md,
              the LAST eval's deficiencies, and the tried-ledger, and outputs ONE
              concrete, scoped proposal (target files + change + why).
2. APPLY    — `opencode-qwen run ... --dangerously-skip-permissions` applies exactly
              that proposal as the smallest coherent diff. Edits harness/ only.
3. GUARD    — if the diff touched any PROTECTED file → revert + log "protected".
              If gate H (no hardcoded story content) fails → revert + log "gate-H".
4. VERIFY-FAST — `pytest harness/` + a fake-LLM full run + fake mini.
              Any failure → revert + log "tests".
5. VERIFY-REAL — run a real `--mini` on **ALL** rotation stories **in parallel**
              (sub-runs forced to PROSE/INGEST workers = 1 to bound concurrency),
              then score each with `loop/eval.py` against quality_eval.md.
              The iteration's signal = the **mean** of the per-story scores.
              Any sub-run that crashes → automatic REJECT (broke a genre).
6. RATCHET  — keep iff  new_mean ≥ best_mean  AND no genre fell below its floor
              (best_per_story[g] − ε)  AND tests green AND guards passed:
                 ACCEPT → commit to `loop/auto`, update best mean + per-story
                 else:   REVERT → `git reset --hard HEAD` + clean
7. Feed this round's deficiencies into the next EXAMINE. Repeat.
```

## Acceptance rule (the ratchet)
The per-iteration signal is the **mean across the FULL rotating set, run in
parallel** (never one story — that overfits + is high-variance). Keep a change
ONLY if **both**:
- `new_mean ≥ best_mean` (the average doesn't drop), AND
- **no individual genre falls below its own floor** `best_per_story[g] − ε`
  (default ε=3, absorbs LLM-judge noise; deterministic dims have zero variance).

This lets the average climb while **forbidding a fix that trades one genre for
another** — the core anti-overfit guarantee. Patience resets only on a *strict*
mean improvement. Everything else is `git reset --hard`-reverted, zero residue.

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
1. **AGENTS.md conformance** — code that violates the harness's own invariants
   (hardcoded story content, non-skeleton plot source, missing schema at a
   boundary, fallback prose, padding/duplication).
2. **Curated bug checklist** — seeded in `loop/state/backlog.md` (e.g. deferred
   items B16/R1/R4 from the manual review). Real, bounded work.
3. **Eval-driven deficiencies** — whatever the last `--mini` eval flagged as below
   target in quality_eval.md.

NOT in scope: open-ended "find any bug", broad refactors, dependency bumps,
performance work without a correctness/quality payoff in the rubric.

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
