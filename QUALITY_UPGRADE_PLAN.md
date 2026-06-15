# Quality Upgrade Plan — High-Quality Interactive Play Scripts, Automatically

Synthesis of: codebase analysis (harness/), SKELETON_UNIFICATION.md, DRAMA_RESTORATION_PLAN.md,
and the research literature (citations at bottom). Verified against run_20260609_084046.

> **Companion doc**: `harness/DRAMATIC_STRUCTURE.md` — the canonical dramaturgy rulebook
> extracted page-by-page from McKee's *Story*, Gulino's *Sequence Approach*, and the Save the
> Cat beat sheet. It supplies the precise trunk template, scene contract, dilemma contract,
> pacing rules, continuity ledgers, and the D16–D29 validator spec that Phases A/C/D below
> reference. Where this plan and that doc differ on specifics, the rulebook wins (it is
> sourced from the primary texts).

## Ground truth from the latest run

- 43 nodes, **0 convergence nodes** (no node has >1 parent) — the graph is a pure time cave,
  the worst structural pattern per Ashwell's taxonomy. Confirms DRAMA problem #1.
- 4 ENDING vs **18 DEAD_END** — 42% of nodes are punishment terminals.
- Choice sample: 15/15 questions are "investigate now vs investigate later" variants
  (追问/逼问/潜入/静观/绕行...). Confirms DRAMA problem #5 — zero dilemmas with value trade-offs.
- Phase 3.5 convergence validation code exists (`_intersect_memories`, VARIES, D4) but never
  fires because expansion never produces a convergence node.

Root cause across all three: **nothing in the pipeline states or checks the intended graph
shape or dramatic shape.** D-checks enforce state coherence; nothing enforces story structure.

---

## Phase A — Structural Spine (branch-and-bottleneck by construction)

*Highest leverage, lowest cost: prompt + validator changes only. Fixes DRAMA #1, #2.*

### A1. Sequence-based trunk in cornerstone
Replace the freeform cornerstone with the **sequence approach** (Gulino): a 60–90 min piece is
6–8 trunk segments of ~10 min, each a mini-arc that ends at a **bottleneck node** posing a new
dramatic question. The bottleneck IS the convergence point; the dramatic question IS the choice.

- `get_cornerstone_nodes()` (llm.py): prompt now demands `trunk: [seq1_bottleneck, ..., seqN_bottleneck]`
  with each bottleneck tagged with its arc slot (Save-the-Cat positions: catalyst ~10%,
  midpoint reversal ~50%, all-is-lost ~75%, climax 85%+). GENEVA showed models satisfy
  **numeric** graph-shape constraints far better than vibes like "make it converge" —
  so state it numerically: "trunk of N bottlenecks; every branch re-merges into the trunk
  within ≤3 nodes; endings fan out only after the final bottleneck."

### A2. Expansion must reconverge
- `choose_expansion_type()` (graph_ops.py): BRANCH_ADDING currently adds a parallel path —
  keep, but require the new path to terminate at an existing trunk node (it already targets B;
  the bug is LENGTH_EXTENDING chains that never share nodes across the first fork — verify and
  constrain: a branch excursion may not exceed 3 nodes before hitting a trunk node).
- Per-branch **accommodate-vs-mediate label** (Riedl narrative mediation): each generated branch
  declares which trunk event the choice perturbs and whether it (a) accommodates — writes a
  lasting `state_delta` then reconverges, or (b) is mediated — fails in-fiction at a cost
  (this is what DEAD_END should be reserved for). Gives every branch a principled reason to
  exist and a principled merge point.

### A3. New deterministic checks (validation.py)
- **D13 convergence floor**: ≥1 convergence node per trunk segment after the first;
  whole-graph convergence count ≥ (bottleneck count − 1). Blocking.
- **D14 excursion cap**: no root→ending path may avoid more than 1 trunk bottleneck;
  max branch depth before re-merge = 3. Blocking.
- **D15 dead-end ratio**: DEAD_END ≤ 25% of nodes and never 2 in a row on a path. Blocking.
- **Branch-writes-must-be-read** (Ashwell's warning: branch-and-bottleneck without state
  tracking collapses into cosmetic choice): every branch's `state_delta`/produces must be
  consumed (requires / label_requires / stat-conditioned prose) by some downstream node.
  Warning first, blocking once stable.

---

## Phase B — Skeleton Unification (adopt SKELETON_UNIFICATION.md, amended)

*The grounding refactor. Fixes DRAMA #3, #6 and the eavesdropping-bug class.*

Adopt the plan as written, with these resolutions to its open questions:

1. **Summary**: keep stored + consistency-checked (its own recommendation). Long term, derive.
2. **Beat IDs**: stable string IDs (`b1`, `b2`...), not indices — its recommendation; required
   because fix loops reorder beats.
3. **reader_has_seen token budget**: truncate beat texts to 50 chars, cap 8 beats/ancestor.
4. **facts tags on beats**: optional hint for prose; only `produces.beat` is validated.
5. **Per-choice conditional produces**: yes — Phase A's accommodate branches need exactly this
   (`{"fact":..., "value":..., "beat":..., "choice": 1}`).

Amendments from the literature:

- **FactTrack-style path intersection** (arXiv:2407.16347): each node's usable-fact set =
  intersection of post-fact sets over all inbound paths. Convergence path-neutrality becomes a
  **set operation**, not an LLM judgment. This replaces most of Phase 3.5's LLM round-trips —
  important because Flawed Fictions (arXiv:2504.11900) shows LLM judges are bad at holistic
  consistency over long text; per-fact set checks are exactly the decomposition that works.
- **Closed cast roster** (DOC, arXiv:2212.10077): skeleton declares `characters[]` per node
  (already in scene_header); make it a deterministic Phase 4.5 check — any speaker/namecard in
  prose not in the roster = blocking violation. Catches the `大夫人 never appears` bug class
  without an LLM.
- **Beat/location caps** (fixes DRAMA #3 bottleneck-dumps): max 2 locations per node
  (scene_header count), max ~8 beats. Exceeding = D-violation telling the LLM to **split the
  node** — climaxes become playable scenes instead of narration. "If a downstream node
  references it, the player must have played it" then falls out of beat-grounding for free.

---

## Phase C — Dramatic Enforcement (implement DRAMA_RESTORATION_PLAN with mechanisms)

*Fixes DRAMA #4 + the 3–5 min peak cadence. Mostly skeleton-schema metadata + deterministic curve checks.*

### C1. 爽点/hook taxonomy at the source
Phase 1d highlight mining (`get_highlights_chunk`) adds two enum fields:
- `satisfaction_type`: 打脸 | 身份揭露 | 逆袭 | 反杀 | 护短 | 夺宝 | 隐藏实力
- `hook_type`: 悬念 | 危机 | 情感 | 反转
Highlight placement (`rank_edges`) and node `covers[]` then carry dramatic *type*, not just weight.

### C2. Per-node dramatic metadata (models.py Node)
```
tension: int (1-5)            # Façade-style declared tension contribution
value: str                    # McKee: the value at stake, e.g. "信任", "生死"
charge_shift: "+→−" | "−→+"   # scene must TURN; no shift = exposition = reject
techniques: ["悬念","反转",...]  # named technique slots
payoff_of: highlight_id|null  # which 爽点 this node pays off
suppression: bool             # 压抑 beat that must be paid off downstream
```
The ACL 2025 interactive-drama result (arXiv:2502.17878) is the key evidence: GPT-4o applies
"twist" spontaneously 6% of the time; named-technique slots + a critic that verifies the
technique was actually realized got 74%. **Prompting alone will not produce drama; declared
slots + verification will.** Add the "was the named technique realized in prose?" check to
Phase 4.5.

### C3. Tension-curve validator (new: pacing.py)
Deterministic, runs at skeleton time (Phase 3.5) per root→ending path, using
`planned_duration_min` as the clock — the Left 4 Dead director loop at script timescale:
- a `tension ≥ 4` peak at most every 5 estimated minutes;
- build→peak→release alternation (no 3 consecutive same-direction charge_shifts — monotony);
- every `suppression` node pays off (`payoff_of` downstream) within ≤2 nodes / ≤5 minutes
  (短剧 压抑→释放 cycle);
- biggest reveals placed near the ~15% and ~40% marks (short-drama 卡点 positions, where
  craving empirically peaks).
Violations route through the existing fix loop with the curve as feedback.

### C4. Per-node episode template (the Dev's Note, answered)
Adopt build-up → 爽点/hook → surprise → dilemma as the **default skeleton scaffold for scene
nodes**, with variants instead of one rigid template:
- prologue: hook → build-up → dilemma (no payoff yet — open a debt instead);
- bottleneck: payoff (converging branches' debts) → reversal → new question;
- DEAD_END: build-up → catastrophe (truncated, as suspected);
- "surprise" need not be a twist every node — any `charge_shift` qualifies; the C2 metadata
  makes this checkable without feeling forced.
4 mandatory beats fits the 8-beat cap: template beats are roles, not extra beats.

---

## Phase D — Choice Quality (dilemmas, mechanically checked)

*Fixes DRAMA #5.*

### D1. Goal-impact matrices (Mawhorter's Choice Poetics — the one formal dilemma model)
- Bible gains 2–3 **standing protagonist goals** (e.g. 复仇 / 守护家人 / 隐藏身份).
- Every choice node outputs a goal-impact matrix:
  `option A: {复仇:+1, 隐藏身份:-1}, option B: {复仇:-1, 守护家人:+1}`.
- **Dilemma check (deterministic)**: reject if any option is non-negative across all goals
  (dominated option = obvious choice = not a dilemma). Reject if both options impact the
  same single goal in the same direction (that's the current "investigate now vs later").
- This turns the five tension modes from prompt vibes into an arithmetic gate.

### D2. Choice-of-Games discipline: stats over forks
Most choices should **write state, not fork the graph**; few fork. With Phase A's convergence,
choices at non-bottleneck nodes write `state_delta` (stats/flags) and reconverge; bottleneck
choices fork for real. Convergence-node prose gets **stat-conditioned variants** (the web app
already has player stats with thresholds — currently unused by the harness). This is how the
player "hits the same pivotal moments; only stakes and flavor differ" — exactly the DRAMA
plan's stated goal, and it's cheap: conditional paragraphs keyed to thresholds.low/high.

### D3. Choice linter (extends S1/S4 with Emily Short's anti-patterns)
Blind choice (stakes not telegraphed in question), false choice (same outcome), dead-end
option (strictly dominated), spoiler label. Mostly deterministic on the goal-impact matrix +
resolution beats; LLM only for telegraphing.

---

## Phase E — Measurement (trust judges only for checkable properties)

- TTCW (arXiv:2309.14556) negative result: LLM judges do **not** correlate with experts on
  "is this good writing". So: never add an "is this dramatic?" judge. Encode quality as the
  checkable constraints above; keep LLM judges for narrow per-node verifiable questions with
  short inputs (current per-node architecture is already right per Flawed Fictions).
- Add a **graph report card** to summary_final.txt: convergence count, dead-end ratio,
  max excursion depth, tension curve per path (sparkline), 爽点 cadence (max gap in minutes),
  choice-type distribution (dilemma/stat-write/fork), branch-state-read coverage. Every run
  becomes regression-testable; today the only quantitative output is total minutes.

---

## Recommended order

| # | Phase | Why this order | Effort |
|---|-------|----------------|--------|
| 1 | **A** Structural spine | Zero convergence breaks the product premise; prompt+validator only, no schema migration | S–M |
| 2 | **C1–C3** 爽点 typing + tension curve | Needs only additive Node metadata; immediate drama gains; informs where branches/payoffs go before the big refactor | M |
| 3 | **D1** Goal-impact dilemma gate | Additive schema; kills investigation-menu choices | S |
| 4 | **B** Skeleton unification | The deep refactor — do it once A/C/D have stabilized the target shape, so you migrate the schema once | L |
| 5 | **C4 + D2** Episode template + stat-conditioned prose | Builds on B's beat structure and A's convergence | M |
| 6 | **E** Report card | Alongside everything; cheap | S |

A note on interaction: SKELETON_UNIFICATION (B) fixes *grounding*; DRAMA_RESTORATION fixes
*shape*. B without A produces a perfectly grounded time cave. A without B produces a
well-shaped graph that still hallucinates back-references. Do A first because it's 10× cheaper
and the shape constraints change what Phase B has to migrate.

## Key references

- Dramatron (hierarchical script co-writing): arXiv:2209.14958
- Façade beat-based drama management: users.soe.ucsc.edu/~michaelm/publications/mateas-gdc2003.pdf
- Riedl & Young narrative mediation / branching from causal-link perturbation: AAMAS'03, AIIDE'05
- L4D AI Director (build/sustain/release pacing loop): Booth, Valve 2009
- WHAT-IF (invariant plot points, state+goal-grounded choices): arXiv:2412.10582
- GENEVA (numeric graph-shape constraints in prompt): arXiv:2311.09213
- ACL'25 interactive drama (named techniques + critic, 6%→74%): arXiv:2502.17878
- DOC detailed outline control (closed rosters, candidate rerank): arXiv:2212.10077
- FactTrack (pre/post-fact intervals, set-operation consistency): arXiv:2407.16347
- Flawed Fictions (LLMs bad at holistic plot-hole detection): arXiv:2504.11900
- TTCW / Art-or-Artifice (LLM judges ≠ experts on creativity): arXiv:2309.14556
- Ashwell, Standard Patterns in Choice-Based Games (branch-and-bottleneck + state warning)
- Mawhorter, Choice Poetics (FDG'14) — formal dilemma = goal-impact matrix
- Choice of Games, "By the Numbers" — delayed branching, stats over forks
- 短剧 pacing: woshipm.com/share/6191708.html; iResearch 2024 微短剧报告
- McKee *Story*, Gulino *The Sequence Approach*, Snyder *Save the Cat* beat sheet — obtained
  and extracted into `harness/DRAMATIC_STRUCTURE.md` (with page citations)

## Addendum — what the primary texts changed vs. the first draft of this plan

1. **The "all is lost" low point is optional.** Gulino (p.19) shows only 4 of his 12 case
   films use it; the real invariant is the **main culmination at 65–85%** — the main dramatic
   question gets *answered* there, and a NEW third-act tension takes over. Phase A's trunk
   template should enforce culmination position + third-act tension, not mandatory despair.
2. **Two genuinely new mechanisms** not in Phases A–E, both high-leverage for a DAG:
   - **Knowledge matrix** (Gulino's hierarchies of knowledge): track who-knows-what per
     fact — audience and each character. Generalizes the VARIES/path-neutrality machinery
     from world-state to epistemic state; "character acts on knowledge their branch never
     gave them" becomes a deterministic check (D25). This catches a bug class the current
     fact system can't express.
   - **Continuity ledgers** (dangling causes, irony brackets, question lifecycle, motif
     plant/payoff): plant during skeleton, validate closure deterministically at export
     (D23). Branch semantics: branches inherit the ledger and must close their copies.
3. **Recap-at-convergence** (Gulino p.31-32) solves the convergence-node prose problem
   elegantly: every convergence node opens with an in-world recapitulation beat that
   restates only guaranteed facts — orientation duty and path-neutrality in one device.
4. **McKee's nonevent test is the single most checkable rule found**: every scene carries
   opening/closing value charge; equal charges = exposition, not a scene (D16). It subsumes
   the earlier `charge_shift` idea with a firmer source and a crisper failure mode.
5. **Crisis staging rules are deterministic**: dilemma type required, played static and
   onscreen with a content floor, no subplot between crisis and climax, penultimate-climax
   charge must contradict the ending's charge (you cannot set up an up-ending with an
   up-ending), last act shortest, resolution beat after every climax (D20–D22).
6. **The choice prompt is a telegraph** (Gulino p.9): each option label must imply a
   concrete future — gives the existing 问题/选择 format a theoretical job description and
   a lint (options that imply nothing are blind choices).
