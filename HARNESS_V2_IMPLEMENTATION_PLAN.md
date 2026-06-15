# Harness v2 — Concrete Implementation Plan

> **Implementation status (2026-06-11)**: M0 report card — DONE. M3a same-target
> choices + state_delta — DONE. M3b convergent trunk + D13 — DONE.
> **7-pass pipeline wired (P0–P6)**: P0 parallel ingest + typed highlights +
> protagonist_goals; P1 outline pass (`generate_outline`, k=2 candidates +
> deterministic score, outline.json artifact); P2 trunk realizes the outline
> (sequence/arc_slot/scene-contract/goal_impacts fields end-to-end);
> P3 excursions get sequence obligations; P4/P6 IR validators
> (`ir.plan_from_graph` + pacing/dilemma/ledger/knowledge) wired as drama lint
> in the report card; P5 prose parallel (3 workers). M2 dramatic fields through
> models/schemas/parse/checkpoint. Dev velocity: `--model fake` full-pipeline
> smoke (~0.1s), `HARNESS_LLM_CACHE` disk cache (with invalidation on schema
> failure), `--until {phase1,outline,cornerstone,expansion}`,
> `HARNESS_READ_TIMEOUT_S`, `HARNESS_STRUCTURE_EFFORT`/`HARNESS_INGEST_EFFORT`
> reasoning knobs, VARIES sentinel made copy/pickle-proof. Skeleton-only output
> contract for structure calls (content mirrored locally, not re-emitted).
> Tests: 52 passing incl. IR suite + fake e2e. Remaining: M1 module split,
> trigger_beat/technique-slot emission (M4 deepening), M5 prose contract, M6.

Goal: a harness that **repeatedly** produces high-quality interactive play scripts.
"Repeatedly" means: every run is measured, every change is regression-tested against
golden runs, and quality is enforced by checkable constraints (per
`harness/DRAMATIC_STRUCTURE.md` and `QUALITY_UPGRADE_PLAN.md`), not by hoping the LLM
behaves.

## 0. Verdict: evolve the kernel, rebuild the failing layers

Two root causes were found **in code**, and both are repairable without a rewrite:

1. **`choose_expansion_type()` is broken** (`graph_ops.py:126-127`): D9 forces every
   non-ending node to exactly 2 choices, so `len(choices) >= 2` is always true and the
   function returns `LENGTH_EXTENDING` unconditionally. `BRANCH_ADDING` is dead code.
   All expansion stretches chains; no parallel path is ever added → **zero convergence
   is a mechanical certainty, not an LLM failure.**
2. **The choice schema mathematically inflates dead ends**: 2 choices to 2 *distinct*
   targets means any node that wants to reconverge at B must point its second edge
   somewhere else — cheapest legal target is a DEAD_END. One fork-and-rejoin costs 2
   dead ends → 18/43 dead ends in run_20260609_084046.

Keep (battle-tested, full of hard-won fixes):
| Module | Why keep |
|---|---|
| `guaranteed.py` | meet-over-paths state lattice, VARIES — correct and reusable for the knowledge matrix |
| `checkpoint.py` | resume works; add schema versioning only |
| `llm.py` transport layer (`_call_llm*`, `_parse_json_from_response`, `_extract_json_by_braces`, schema validation, debug dumps) | encodes months of gotchas (JSON-from-end, `"target"` alias, claude-code/fireworks backends) |
| `chunker.py`, `registry.py`, phase-1 map/reduce | works; only schema additions |
| `merge()` + seam validation (`graph_ops.py:168`) | correct; excursions reuse it |
| `compute_node_memories` / `_intersect_memories` (`validation.py:86-166`) | the DFS memory machine; extended, not replaced |
| `web_export.py`, `upload.py` | downstream contract; touch only for new fields |

Rebuild:
| Layer | Why |
|---|---|
| Phase 2 cornerstone → **trunk generator** | no structural template exists; DRAMATIC_STRUCTURE §1 is the spec |
| Phase 3 expansion → **excursion generator** | expansion-type logic dead; no reconvergence concept |
| Choice semantics | must support same-target choices with divergent state (the dead-end fix) |
| Validation | gains the dramatic layer (D13–D29, ledgers, pacing, knowledge matrix) |
| Prompt files | rewritten against the new schema (SKELETON v2 / PROSE v2) |
| `harness.py` + `llm.py` as files | 2k/3k-line monoliths; split before touching logic |

---

## M0 — Measure first: report card + golden runs  (size S, do immediately)

Nothing else lands without this; it is the regression harness for every later milestone.

**New `harness/metrics.py`**
- `report(graph, registry, highlights, params) -> dict` computing:
  - structure: node count, ENDING/DEAD_END counts + ratio, convergence-node count,
    parent-count histogram, max branch excursion depth, bottleneck coverage per path;
  - pacing: `planned_duration_min` distribution + variance, per-path total minutes,
    shortest/longest playthrough;
  - choices: question-similarity clusters (char-bigram cosine — catches the 15×
    "追问/逼问/潜入" menu), label prefix dupes, dilemma-type distribution (when M2
    fields exist — sections degrade gracefully on v1 graphs);
  - drama (post-M2): tension curve per path, charge-alternation violations, 爽点 gap
    in minutes, ledger closure stats.
- `render_markdown(report) -> str`.

**CLI + wiring**
- `python -m harness report <run_dir|graph.json>` → writes `report.json` + `report.md`
  into the run dir; `_build_phase3_5_onwards()` calls it at final export.
- `scripts/golden_run.py`: run the pipeline on a pinned source novel + pinned params,
  then `diff` the new `report.json` against `golden/baseline_report.json` with
  tolerance bands. This is the per-milestone acceptance gate.

**Acceptance**: report on `run_20260609_084046` reproduces the known numbers
(43 nodes, 0 convergence, 18 DE / 4 E, ~99 min).

---

## M1 — Split the monoliths (size M, no behavior change)

Every later milestone edits prompts and validators; that is unsafe inside two
2-3k-line files.

```
harness/
  llm/
    client.py      # _call_llm*, retries, _parse_json_from_response, _validate_json_schema, debug dumps
    schemas.py     # all *_SCHEMA dicts
    parsing.py     # _parse_node, _parse_subgraph_response, _parse_effects, ...
    prompts/       # one builder module per phase: extract.py, trunk.py, excursion.py, prose.py, judge.py
    calls.py       # thin per-phase call functions (get_story_bible_chunk, fill_prose, ...)
  pipeline/
    phase1_extract.py   # from _build_fresh: chapters/bible/highlights/registry
    phase2_trunk.py     # replaces get_cornerstone_nodes + stabilize_cornerstone
    phase3_excursions.py# replaces _build_phase3/_generate_subgraph/expand_edge
    phase4_prose.py     # fill-prose topo walk
    fixloops.py         # _validate_and_fix_* loops, _auto_fix
    run.py              # build(), resume — the only public entry, re-exported by harness/__init__
  validation/
    deterministic.py    # D1–D15 (from validation.py)
    dramatic.py         # D16–D29 (M4)
    ledgers.py          # ledger closure checks (M4)
    memory.py           # NodeMemory, compute_node_memories, knowledge matrix (M4)
    semantic.py         # LLM-judge entry points
```

Mechanical moves only; `build()` signature and checkpoint format unchanged.

**Acceptance**: `test_harness.py` green; load an existing checkpoint, run final
validation + export, byte-identical `web_app_export.json`.

---

## M2 — Data model v2 + checkpoint versioning  (size M)

### 2a. Finish skeleton unification (it is half-done in code)
`models.py` already has `skeleton` + `Effect.beat` + summary marked "legacy compat".
Complete it per SKELETON_UNIFICATION.md:
- skeleton beats get **stable ids** `b1..bn` (`{"id": "b3", "type": "action", ...}`)
  and optional `facts: []` hints; `produces[].beat` becomes required for new graphs (D-check).
- **Delete the drift source**: `Node.__post_init__` lines 151-152 copy
  `skeleton → content` when content is empty. After this, `content` strictly means
  "prose exists"; add `Node.has_prose()` and make Phase-4 gating use it.
- `summary`: stored, but validated against beats (existing `fix_skeleton_summary`
  path becomes the enforcement loop).

### 2b. Dramatic fields (all optional/nullable → old checkpoints load)
```python
# Node
sequence: str = ""            # "A".."H" trunk segment
arc_slot: str = ""            # inciting_incident|lock_in|midpoint|main_culmination|crisis|climax|resolution
intensity: int = 0            # 1-5, Façade-style declared tension
value: str = ""               # value at stake (信任/生死/自由)
opening_charge: str = ""      # "+"|"-"
closing_charge: str = ""      # "+"|"-"  → D16 nonevent check
turning_type: str = ""        # action|revelation
expectation: str = ""         # the Gap (McKee)
result: str = ""
scene_objective: str = ""
antagonism_desire: str = ""
techniques: list[str]         # 悬念|反转|讽刺|... critic-verified in prose phase
suppression: bool = False     # 压抑 beat; must pay off ≤2 nodes downstream
payoff_of: str = ""           # highlight id this node pays off

# Choice
dilemma_type: str = ""        # irreconcilable_goods|lesser_of_two_evils|combined
cost: str = ""                # what is irreversibly risked/lost (triangular cost)
goal_impacts: dict[str, int]  # {"复仇": +1, "隐藏身份": -1} → dominated-option check
state_delta: list[Effect]     # per-choice conditional produces (same-target choices differ here)

# Highlight
satisfaction_type: str = ""   # 打脸|身份揭露|逆袭|反杀|护短|夺宝|隐藏实力
hook_type: str = ""           # 悬念|危机|情感|反转

# Bible
protagonist_goals: list[{id, gloss}]   # 2-3 standing goals, the dilemma reference frame
```

### 2c. Ledgers (new `models` additions)
```python
@dataclass class LedgerEntry:  # dangling_cause | irony | question | motif | setup
    kind: str; id: str; gloss: str
    planted_at: NodeId; refs: list[NodeId]; closed_at: NodeId | ""
    meta: dict   # irony: revelation/recognition; question: posed/deliberated/answered
Graph.ledger: list[LedgerEntry]
```

### 2d. Checkpoint versioning
`schema_version: 2` in checkpoint JSON; `checkpoint.migrate_v1(data)` fills defaults.

**Acceptance**: every v1 checkpoint in `harness_output/` loads, validates, exports
identically; round-trip serialization tests for all new fields.

---## M3 — Trunk-first generation + excursions  (size L — the core rebuild)

### 3a. Fix choice semantics first (the dead-end fix)
- **Allow both choices to share a target** when their `state_delta`/`resolution`
  differ (Choice-of-Games "stats over forks"). D9 update: distinct targets OR
  (same target AND non-identical `state_delta` AND distinct resolutions).
- Reconvergence no longer costs dead ends: `n2 → {B(delta₁), B(delta₂)}` is legal.
- DEAD_END is reserved for **mediated** branches (in-fiction failure, priced);
  D15 caps DEAD_END at 25% of nodes and forbids 2-in-a-row per path.
- `web_export.py`: emit `state_delta` per edge (webapp stats integration point).

### 3b. `pipeline/phase2_trunk.py` — replaces cornerstone
1. **One trunk call** (`llm/prompts/trunk.py`): produce 6–8 sequences per
   DRAMATIC_STRUCTURE §1 — for each: bottleneck node (skeleton, arc_slot, intensity,
   dramatic question lifecycle entry), `main_dramatic_question`, ledger plants
   (dangling causes, irony brackets), 爽点 schedule mapping `satisfaction_type`
   highlights onto sequence positions (~15% / ~40% 卡点 anchors). Shape constraints
   stated **numerically** (GENEVA result: models obey numbers, not vibes).
2. **Per-sequence interior fill**: 2–4 nodes per sequence, generated
   sequence-by-sequence with adjacent context only (Dramatron: spine carries
   coherence, not context length). Each call receives: bible, this sequence's
   bottleneck contract, previous sequence's exit state, the sequence's assigned
   highlights + ledger obligations.
3. `stabilize_trunk()` (adapted `stabilize_cornerstone`, harness.py:1733): existing
   D-checks + new trunk checks: D18 (II ≤25%), D19 (≥3 majors), D26 (main
   culmination 65–85% + third-act tension), D20 (penultimate charge ≠ ending charge).

### 3c. `pipeline/phase3_excursions.py` — replaces expansion
- Unit of work: **excursion** = fork at trunk/branch node A, ≤3 interior nodes,
  mandatory reconvergence at a declared trunk node B (existing `merge()` handles the
  seam — B simply gains a parent).
- Each excursion declares: perturbed trunk event, `accommodate` (writes state_delta,
  reconverges) or `mediate` (DEAD_END, priced) — Riedl mediation made concrete.
- `rank_edges()` survives as **excursion-site ranking** (unplaced-highlight density,
  length deficit); `choose_expansion_type()` is deleted.
- `_validate_expansion_shape()` gains: reconvergence-required, depth ≤3,
  branch-writes-must-be-read (every excursion `state_delta` consumed downstream —
  warning first, blocking once stable).
- Budget loop unchanged (`total_minutes >= total_budget_min`), but the loop now also
  exits on "all sequences have ≥1 excursion" coverage floor.

### 3d. Convergence safety — why merged excursions can't introduce logic bugs

Principle: the LLM never decides whether convergence is correct; correctness is
recomputed by set operations after every merge. Six layers:

1. **By construction**: excursion generated against a frozen contract — entry =
   `guaranteed(A)`, exit = fixed trunk node B (its `requires` + `entry_context` +
   invariants); `varying_state` facts forbidden in the interior. B is an input,
   never a choice.
2. **Shape check pre-merge** (`_validate_expansion_shape` v2, exhaustive on the
   closed subgraph): all interior reachable from A; all paths end at B or a priced
   DEAD_END; depth ≤3; no edges to other graph nodes; acyclic.
3. **Lattice recompute post-merge** (the load-bearing layer): `compute_guaranteed()`
   meet-over-paths re-runs on the merged copy. Excursion fails to supply a fact the
   old A→B edge supplied → fact becomes VARIES at B → D1/D4 fires anywhere in B's
   subtree → repair or reject. Exhaustive over paths because it is lattice math,
   not path sampling. D7 catches invariant flips; D11 catches context teleports.
4. **B stays path-neutral**: B's skeleton already restricted to `guaranteed(B)`
   facts (Phase 3.5); knowledge matrix (D25) extends the same meet to
   (character × fact); B's prose opens with a recap beat restating only guaranteed
   facts.
5. **Divergence is guarded, never presupposed**: excursion `state_delta` must be
   read downstream (else cosmetic choice — violation), and any downstream reference
   to a VARIES fact must be conditional (`label_requires` / stat-conditioned text);
   unconditional reference = D4.
6. **Transactional commit**: validate on a copy; fix-retry ≤N with subgraph-scoped
   feedback; on failure discard + mark `_non_expandable_edges`. Checkpoint only
   after a clean commit — a bad excursion costs tokens, never correctness.

Known limit: the lattice only sees *declared* state. Narrative nuance never produced
as a fact is invisible — hence the dilemma gate forces every choice to declare
`goal_impacts`/`state_delta`, pushing meaningful divergence into the fact system
where the math can see it.

**Acceptance (report-card gates on golden run)**: convergence nodes ≥ bottlenecks−1;
DEAD_END ratio ≤25%; every path crosses ≥80% of bottlenecks; max excursion depth ≤3;
playthrough minutes within ±15% of target.

---

## M4 — Dramatic validation layer  (size L)

### 4a. `validation/dramatic.py` — D16–D29 (spec: DRAMATIC_STRUCTURE §7)
Deterministic, skeleton-time, zero LLM cost:
- D16 nonevent (`opening_charge == closing_charge`) — blocking
- D17 risk/intensity monotone-with-relief per path (alternation per M-p.289: dips
  after act climaxes allowed, each peak tops the last)
- D18–D22, D26–D29 position/charge/length checks (per §7 list)
- D24 twist-references-telegraph + retardation distance
- 爽点 cadence: peak (intensity≥4) every ≤5 estimated minutes; `suppression` pays
  off within ≤2 nodes (new `validation/pacing_curve.py`, consumed by metrics too)

### 4b. `validation/ledgers.py` — D23
Closure at export: dangling causes paid/`intentionally_open`, irony brackets have
both revelation+recognition, question lifecycle complete (posed/deliberated/answered),
orphan payoffs. Branch semantics: each root→ending path must close its inherited copies.

### 4c. Knowledge matrix — D25 (extend `validation/memory.py`)
Reuse the `guaranteed.py` meet-over-paths pattern over `(character, fact)` pairs:
`knows[char][fact]` propagated through nodes (a character present in a scene_header
where a fact's beat occurs learns it; explicit `reveals_to` on beats for off-scene
learning). Intersection at convergence, VARIES sentinel reused. Check: no dialogue/
action by a character uses a fact their branch never gave them. This generalizes
path-neutrality from world-state to epistemic state — a bug class the current fact
system cannot express.

### 4d. Dilemma gate (deterministic, in `validation/deterministic.py`)
On `goal_impacts`: reject dominated options (one option ≥0 on all goals); reject
both-options-same-goal-same-direction (the "investigate now vs later" signature).
Requires `protagonist_goals` from Phase 1 (schema added in M2).

### 4e. Narrow judges (`validation/semantic.py`) — wired into existing fix loops
One property per call, short inputs (Flawed-Fictions lesson): gap test
(expectation≈result?), equal-weight options, technique-realized, ammunition/as-you-know
scan, circumstance-caused reversals. All route through the existing
`violation_feedback` → regen path (`fixloops.py`); never a holistic "is this good" judge
(TTCW negative result).

**Acceptance**: every new violation type has a fix-loop path that converges on the
golden run within existing attempt caps; final graph: 0 blocking, ≤N warnings.

---

## M5 — Prose v2  (size M)

- `fill_prose` reads **skeleton only** (summary no longer an input — SKELETON_UNIFICATION
  §3); beats are the ceiling of prose content.
- Deterministic post-checks (no LLM): **closed cast roster** (speakers/namecards ⊆
  scene_header characters ∪ summary-mentioned), beat coverage (every skeleton beat id
  matched in prose), terminal markers (existing).
- Structural beats by node type: convergence nodes open with a **recap beat**
  (restates only guaranteed facts — Gulino p.31; solves path-neutral openings);
  `preparation` beat before culminations (`payoff_mode: direct|contrast`);
  `aftermath` beat after intensity-5 nodes and all endings.
- Rewrite `CREATIVE_WRITING_SKELETON.md` → v2 (trunk + excursion sections, scene
  contract fields, dilemma contract) and `CREATIVE_WRITING_PROSE.md` → v2 (subtext/
  indirection, ammunition exposition, recap/preparation/aftermath); both reference
  DRAMATIC_STRUCTURE.md as source of truth; delete legacy `CREATIVE_WRITING.md`.

**Acceptance**: golden run with 0 cast-roster violations, ≥95% beat coverage,
all convergence nodes open with recap, S2-class regen count drops vs baseline.

---

## M6 — Repeatability loop  (size M, ongoing)

- **StoryProfile** config file (TOML/JSON): genre, 爽点 taxonomy weights, trunk shape
  (sequence count, budget, ending count), model profile, technique palette.
  `Params` loads from it; `editor_notes` folds in. One file = one reproducible recipe.
- **Candidate-rerank where it pays** (DOC pattern): k=3 trunk candidates scored by a
  structure-adherence judge + report-card preview, best merged; k=2 for crisis/dilemma
  nodes. Everything else stays single-shot (cost control).
- **Run database**: append every `report.json` to `harness_output/runs.jsonl` with
  prompt-file hashes + model + profile; `python -m harness trends` renders the table.
  Prompt changes become A/B-able: same profile, two prompt hashes, diff report cards.
- **Feedback ingest**: per-node human ratings (webapp `steering_notes` column exists)
  → targeted re-generation of flagged nodes via the existing fix loops.

---

## Sequencing & effort

| Order | Milestone | Size | Depends on |
|---|---|---|---|
| 1 | M0 report card + golden run | S | — |
| 2 | M1 split monoliths | M | M0 (regression safety) |
| 3 | M2 data model v2 | M | M1 |
| 4 | M3 trunk + excursions + choice semantics | L | M2 |
| 5 | M4 dramatic validation | L | M2 (fields), M3 (shape to validate) |
| 6 | M5 prose v2 | M | M2; benefits from M4 |
| 7 | M6 repeatability loop | M | M0; rest incremental |

M3 and M4 can interleave: D16–D22 checks can land as warnings against trunk output
while excursions are still in progress.

## Explicit non-goals (for now)

- No multi-agent orchestration rewrite; the single-pipeline + fix-loop design stays.
- No model swap; `glm-5p1`/Fireworks + claude-code backends as-is (VISION.md rule:
  never silently downgrade).
- Stat-conditioned prose **variants** at convergence nodes (CoG full pattern):
  deferred until webapp can render conditional paragraphs; `state_delta` export (M3a)
  is the forward-compatible hook.
- Online webapp pipeline (workers/) parity: harness-first; port once stable.

## Open questions (decide before M3)

1. **Trunk granularity**: bottleneck-only trunk call then per-sequence interiors
   (planned, cheaper, Dramatron-style) vs one giant trunk call (simpler, riskier on
   long outputs). Plan assumes the former.
2. **Same-target choices in the webapp**: DAG viz currently assumes distinct edges —
   confirm `@xyflow` rendering of parallel edges before M3a export changes.
3. **Knowledge matrix scope**: main cast only (bible characters) or all named
   characters? Plan assumes main cast (registry stays bounded).
4. **Golden source novel**: pick one fixed novel + profile as the canonical golden run
   (suggest the current 翼王 story since its failure modes are documented).
