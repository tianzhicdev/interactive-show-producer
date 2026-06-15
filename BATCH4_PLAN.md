# Batch 4 Plan — bug fixes, quality batch, cleanup, then the overdue refactor

Inputs: user review of v2.3 (run_20260611_164014), discussion decisions, and a
full code audit (findings cited by file:line below). Ordering principle:
correctness first, quality second, deletions third, structural refactor last —
each stage gated by the test ladder (52 unit tests + fake e2e ~0.1s).

## A. Correctness bugs (audit-confirmed; fix first)  [S each]

1. **`creative_writing_fix` context drift** (llm.py:2305, harness.py:1526/1684):
   the fix call lacks `registry`/`extra_context`/`target_candidates`/
   `dead_end_allowed` that the generator received — fixes can violate the very
   contract being repaired. Pass identical context to gen and fix.
2. **Cache not invalidated on prose length-floor rejection** (llm.py:3615):
   a too-short cached response replays forever across runs. Call
   `invalidate_cached_response` before the floor-retry.
3. **`allowed_external` missing in the merge-path shape check**
   (harness.py:1658): valid candidate-menu edges get falsely rejected after
   merge repair. Pass the same `between` set as the generation path.
4. **`_llm_calls_used` unlocked read** (harness.py:531): use the lock or a
   getter; workers increment it concurrently.
5. **`_prose_cast_context` recomputed per regen call** (4.5 loop): full-graph
   memory recompute on every fix iteration. Compute once per node visit,
   refresh only after fixes mutate the graph.
6. **Resume dir typo ⇒ silent fresh run** (build/_build_resume): if
   `--resume` path lacks checkpoints, ERROR out (and add `--resume latest`).
   Cost us a wasted launch on 2026-06-11.

## B. Quality batch (from the v2.3 review discussion)

1. **Goal-vocabulary discipline** [S-M]
   - Inject the bible's `protagonist_goals` ids verbatim into ALL choice-writing
     calls: 4.5 fix family (fix_skeleton_node_semantics, fix_summary_violations,
     s4_fix), expansion gen+fix. P2.5 already filters.
   - Parser drops unknown `goal_impacts` keys (log them); P2.5 refills emptied
     impacts. The dominated-option gate becomes trustworthy again.
2. **Post-prose duration model** [S] — measured on v2.3: prose+avg-aftermath ≈
   **7.6× skeleton chars** (median; range 2.8–13.6).
   `estimate_minutes` for thin nodes: `max(planned_duration_min,
   skeleton_cjk × 7.5 / words_per_min)`. Expansion then budgets finished-show
   minutes; "--total 30" stops meaning "62 happens".
3. **Aftermath ↔ target-node no-overlap** [M] (the duplicate-heist bug)
   - Prompt contract: fill_prose receives each choice's TARGET opening beats:
     "下一场从X开始；aftermath 必须停在X之前，零事件重叠".
   - Deterministic check: bigram similarity between each aftermath and its
     target node's prose → violation → regen (same machinery as
     similar-question metric).
4. **P2.5 upgrades** [S]
   - `value` = a 2–4字 value AXIS (生死/尊严/掌控/信任…) with examples; reject
     plot-summary strings (v2.3 produced "绝境立威遭弃").
   - Add `expectation`/`result` to the P2.5 schema (the Gap data is currently
     never populated anywhere).
   - Charge-alternation context: pass path-neighbor charges into each P2.5
     call ("前一节点收于−") so monotone runs stop at the source.
5. **Post-prose shortest-path floor** [S]: after Phase 4, if shortest
   root→ENDING playthrough < 85% of target_playthrough_min, log loudly + report
   gate (extension excursion routing = later).
6. **Metric mutes** [S]: fork-reconvergence exempts forks whose non-rejoining
   branch is terminal (the designed mediate shape); ledger "question never
   deliberated" sub-check off until deliberation refs are actually wired.
7. **trigger_beat verification** [S]: with beat_roles now required in P2.5,
   assert on the next run that Dilemma.trigger_beat maps and the
   choice-at-peak check produces signal (it has been inert so far).

## C. Dead code deletions (audit-verified safe)  [S total]

- `_contexts_contradict` (validation.py:166–195) — D11 retired.
- `write_prose` (llm.py:3047–3080) — superseded by fill_prose, uncalled.
- `_parallel_generate` (harness.py:1380–1420) — superseded by
  `_parallel_generate_and_commit`.
- `choose_expansion_type`'s BRANCH_ADDING arm (graph_ops) — unreachable since
  the binary contract; collapse to LENGTH_EXTENDING and delete the enum plumbing.
- Legacy `CREATIVE_WRITING.md` (no consumers).

## D. Refactor (the overdue M1) — separate pass AFTER a good banked run

Audit's top targets, in value order:
1. **Split harness.py (~2500 lines)** into `pipeline/expansion_loop.py`,
   `pipeline/prose_phase.py`, `pipeline/semantic_phase.py`; harness.py stays
   the orchestrator. [L]
2. **Schema consolidation** in llm.py: collapse the three near-duplicate pairs
   (_NODE/_SKELETON_NODE, _CORNERSTONE/_SKELETON_CORNERSTONE,
   _SUBGRAPH/_SKELETON_SUBGRAPH). [M]
3. **`_choice_to_dict()` helper** replacing 8+ hand-built choice payloads. [S]
4. **`ProseContext` dataclass** replacing fill_prose's 9-param signature. [S-M]
5. **Params cleanup**: delete legacy `max_fix_attempts`; group into
   budget/output/gates sub-structures. [M]

Guardrails for D: mechanical moves only, fake e2e byte-comparison on
graph_final of a fixed-seed fake run before/after, full unit suite green at
every step. (The patch-script editing era ends here — the lost-edit incident
and duplicate-schema risk are symptoms of files too big to patch safely.)

## Sequencing & verification

A (bugs) → B (quality) → C (deletions) → fake gauntlet + 52 tests →
**fresh run with `--live-upload`** (watch in webapp; compare report card vs
run_20260611_164014; verify: no duplicate scenes, goal vocab clean, total
minutes ≈ budget, trigger_beat firing) → upload final → THEN D in a separate
session against the banked artifact.
