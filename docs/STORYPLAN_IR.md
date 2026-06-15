# StoryPlan IR — Pass-by-Pass Design (Harness v2 target architecture)

Implementation: `harness/ir.py` (typed dataclasses + deterministic computations,
JSON round-trippable). Worked example: `harness/test_ir.py::example_plan()` —
a 替嫁王妃 mini-plan exercising every structure below. 52 tests green.

The plan is data; prose is rendering. Each pass = (input artifact, output
artifact, invariants preserved, validator). Every pass is checkpointable,
replayable against the fake backend, and model-routable.

```
P0 ingest → P1 outline-plan → P2 trunk-graph → P3 excursions×N → P4 pacing → P5 prose → P6 lint+report
```

---

## P0 — Ingest (novel → analysis artifacts)

**Out**: chapters index, bible (+`protagonist_goals`), typed highlights
(`satisfaction_type`/`hook_type`), fact registry.
**Parallel: YES** — map/reduce over chunks, embarrassingly parallel
(today it is sequential; 4× wall-clock available for free).
**Model**: mid-tier, `reasoning_effort=none` (extraction, not invention).

```json
{"id": "h004", "chapter": 2, "weight": 0.95,
 "satisfaction_type": "护短", "hook_type": "危机",
 "gloss": "折断颜松手臂，刀抵咽喉护住婆母"}
```

## P1 — Outline plan (the one artifact everything depends on)

**Out**: `sequences[]` + ledger PLANTS + 爽点 schedule + player-state model.
This is where dramatic structure is DECIDED; later passes only realize it.
**Parallel: k candidates in parallel, judged, best merged** (DOC-style rerank —
worth it precisely here because the artifact is small and leverage is maximal).
**Model**: best available, full reasoning. ~2-4k tokens out.

```json
{"sequences": [
   {"id": "A", "function": "hook",    "span_pct": [0.00, 0.11], "bottleneck": "t1"},
   {"id": "B", "function": "lock_in", "span_pct": [0.11, 0.25], "bottleneck": "t2",
    "question_id": "q.main"}],
 "ledger": [
   {"id": "q.main", "kind": "question",
    "gloss": "霍家能否活着走完流放路并翻案？", "planted_at": "n1.b1"},
   {"id": "irony.husband_identity", "kind": "irony",
    "gloss": "观众知道账房侄子是霍长鹤易容，颜如玉/颜松不知",
    "meta": {"revelation": "x1.b2", "recognition": "?"}}],
 "player": {
   "goals": [{"id": "守护霍家"}, {"id": "查明真相"}, {"id": "隐藏秘密"}],
   "stats": [{"id": "player.bold", "gloss": "勇烈", "low_effect": "谨慎线结局",
              "high_effect": "刚烈线结局"}]}}
```

**Why the ledger is useful**: every narrative obligation becomes a row that
must be CLOSED (`ledger_violations()` is a set check). The eavesdropping-bug
class — prose referencing a scene nobody planted — becomes impossible to miss:
if it wasn't planted, the reference has no ledger row; if planted and never
paid, export fails. Unfired setups, unanswered questions, unrecognized ironies
are all the same query.

**Why the player-state model is useful**: (a) `goals` are the reference frame
that makes "real dilemma" ARITHMETIC — `dilemma_violations()` rejects any
option non-negative across all goals (the investigate-now-vs-later signature
is two options impacting the same goal the same way); (b) `stats` connect
choice `state_delta` to the webapp runtime (thresholds.low/high already exist
there) — choices write state that endings/prose variants read.

## P2 — Trunk graph (sequences → bottlenecks + interiors)

**Out**: `nodes{}` for the trunk: every node carries the **scene contract**
(value, opening/closing charge, turning_type, expectation/result, tension),
beats with **roles** (buildup→payoff→surprise→decision_trigger), a **closed
cast**, and a Dilemma whose `trigger_beat` must sit in the final 2 beats.
**Parallel: YES per sequence** — the outline froze each sequence's entry state,
exit contract, assigned highlights, and ledger obligations, so interiors are
independent contract-fills. (The outline is what BUYS this parallelism.)
**Model**: big model, `reasoning_effort=low`.

```json
{"id": "t1", "kind": "bottleneck", "sequence": "B", "arc_slot": "lock_in",
 "value": "生死", "opening_charge": "+", "closing_charge": "-",
 "turning_type": "action", "tension": 5,
 "expectation": "熬到驿站便能喘息", "result": "颜松夜里要对霍家下死手",
 "cast": ["颜如玉", "颜松"],
 "beats": [
   {"id": "t1.b1", "type": "action",   "role": "recap",
    "text": "清点伤情与处境：流放第三日，颜松步步紧逼"},
   {"id": "t1.b2", "type": "action",   "role": "surprise",
    "text": "颜如玉撞破颜松向井中投毒", "facts": ["world.poison_plot"]},
   {"id": "t1.b3", "type": "dialogue", "role": "decision_trigger",
    "speaker": "颜松", "uses": ["world.poison_plot"],
    "text": "毒已入井：你敢声张，先死的是你婆母"}],
 "dilemma": {
   "question": "井水已被投毒——当场揭发还是暗中换水？",
   "dilemma_type": "lesser_of_two_evils", "trigger_beat": "t1.b3",
   "options": [
     {"label": "当场揭发", "to": "e1", "cost": "撕破脸，再无转圜",
      "goal_impacts": {"查明真相": 1, "守护霍家": -1}},
     {"label": "暗中换水", "to": "e2", "cost": "罪证沉默，颜松逍遥",
      "goal_impacts": {"守护霍家": 1, "查明真相": -1}}]}}
```

Note what is now *checkable for free*: nonevent (`opening==closing` charge),
choice-at-peak (`trigger_beat ∈ last 2 beats`), dominated options, identical
goal impacts, cast closure, beat-fact grounding.

## P3 — Excursions ×N (branch insertion, transactional)

**Out**: branch nodes between trunk points, `accommodate` (state_delta +
reconverge) or `mediate` (priced DEAD_END).
**Parallel: generation YES / commit SEQUENTIAL** — threads read a frozen
snapshot; each result merges + revalidates (lattice + knowledge recompute) +
checkpoints as it completes (already implemented: commit-as-completed).
**Model**: big model, `reasoning_effort=low`.

**Why the knowledge matrix is useful** — the worked example's exact case:
the x1 excursion reveals 账房侄子=霍长鹤 to 颜如玉 (`reveals_to`), but only on
that path. At convergence node t1 `compute_knowledge()` gives:

```
entry["t1"][("颜如玉", "world.nephew_is_husband")] == VARIES
entry["t1"][("audience", "world.nephew_is_husband")] == VARIES
```

Any t1 beat that `uses` that fact → deterministic violation ("uses fact that
is VARIES on some inbound path"). This is the 窗纸/眼线 bug class — a character
acting on knowledge their branch never gave them — caught by set operations,
no LLM. It generalizes the world-state lattice to *epistemic* state, including
the audience (irony brackets read the audience row).

## P4 — Pacing pass (deterministic, then targeted regen)

**Out**: violations list → constrained regeneration of offending nodes only.
`pacing_violations()`: tension≥4 peak every ≤5 estimated minutes per path,
no 3 consecutive same-sign closing charges, nonevent detection.
**Parallel: validation instant; fixes YES per offending node.**
**Model**: none for detection; mid-tier for fixes.

## P5 — Prose codegen (the only pass that writes 台词/atmosphere)

**Out**: rendered content per node. Contract: every beat realized, no plot
beyond beats, cast closed, recap-opening at convergence nodes, final element
before the question IS the `decision_trigger` beat.
**Parallel: FULLY** — prose is a pure function of (node, frozen IR context);
the IR precomputes reader-memory so no topo-order dependency remains. This is
the biggest wall-clock win vs today's sequential Phase 4 (~10× on large graphs).
**Model**: big model, full reasoning — this is where creativity belongs.

## P6 — Lint + report

Deterministic: ledger closure, knowledge, pacing, dilemma gates, cast lint,
report card (metrics.py). Narrow LLM judges (gap test, technique-realized) —
**parallel per node**, short inputs, one property per call.

---

## Parallelization summary

| Pass | Parallel? | Unit | Why safe |
|---|---|---|---|
| P0 ingest | YES | chunk | map/reduce, no shared state |
| P1 outline | k-candidates | candidate | judged + merged once |
| P2 trunk | YES | sequence | outline froze per-sequence contracts |
| P3 excursions | gen YES / commit seq | site | snapshot reads; transactional merge revalidates |
| P4 pacing | fix-stage YES | offending node | constraints local after detection |
| P5 prose | FULLY | node | pure function of frozen IR |
| P6 lint | YES | node/property | read-only |

The serial spine is short: outline → trunk-merge → excursion-commits →
pacing-detect. Everything expensive (token-wise) is parallel.

## Migration mapping (existing code → IR)

| Today | IR |
|---|---|
| `Node.skeleton` ContentElements | `PlanNode.beats` (roles, uses, reveals_to added) |
| `Node.summary` | deleted — beats ARE the plan |
| `Choice` + `state_delta` | `DilemmaOption` (+cost, goal_impacts) |
| `question` | `Dilemma.question` + `trigger_beat` + `dilemma_type` |
| `guaranteed.py` lattice | unchanged (world-state); `compute_knowledge` reuses the meet pattern |
| Phase 3.5 LLM path-neutrality | `knowledge_violations()` — set ops |
| VALIDATION.md S-checks | P6 narrow judges (reduced scope) |
