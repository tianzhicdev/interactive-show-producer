# Review Fixes Plan — from the first human review of a v2.1 production run

Source: user review of https://hudongju.net/project/268ec0f8 (run_20260611_033159).
Eight issues → seven workstreams. Theme consistent with everything so far:
every issue found by reading becomes a constraint found by computing.

## The issues (as found)

1. Prose is blander than the source novel (humor, dialogue rhythm lost)
2. Node title duplicates the choice question
3. ep01's two choices both point to ep02 (same-target pair survived to prod)
4. ep02 references 血书/爪牙 never introduced on any path
5. 阮仙藻 appears with no introduction
6. Labels/questions use abstract strategy words (以智控局), inconsistently
7. 颜大小姐 gets no namecard on first appearance
8. Climactic beats (夫妻相认) live in 2-line choice-resolution stubs nobody plays

## Design decisions made in discussion

- **Prose borrows TEXTURE from the source, never PLOT**: skeleton owns structure
  (grounded), original chapters own dialogue/humor/detail. S2 + beat-grounding
  remain the guard against drift.
- **Aftermath blocks live at the END of the choosing node** (not on edges as
  entities): node script = 正文 → 问题/选择 → per-choice dramatized aftermath
  (3–6 elements, played after selection). Matches the existing ━━━ EP04-A
  script format exactly → no DB/webapp schema change. Consequences:
  - convergence neutrality by construction (path-specific content stays in the
    source node's branch sections; persistent effects only via state_delta);
  - ending nodes become pure denouement (crisis+climax played in node+aftermath).
- **First-appearance is computed, not guessed**: `compute_node_memories()`
  already tracks `known_characters` with meet-over-paths; surface it to prose
  and validators.
- **Ledger plants ride the fact lattice**: each ledger entry gets a fact id;
  the plant node produces it (beat-anchored); references require/use it;
  D1 + knowledge matrix enforce plant-before-reference with zero new machinery.

## Workstreams

### W1 — Source text into prose (issue 1) — biggest quality lever  [S-M]
- `fill_prose(node, bible, params, graph, chapters_index)` — include the node's
  chapter-span text (cap ~6k chars) in the prompt. Callsites all in
  `_build_phase3_5_onwards` (phase 4 loop, 4.5 regens, final self-heal) which
  already holds `chapters`.
- `CREATIVE_WRITING_PROSE.md`: borrow contract — 原文对白/比喻/幽默/场景细节
  可直接借用或改写，但仅限骨架已含事件；禁止从原文引入新剧情/新人物。
- No validator changes needed (S2/beat-grounding already guard drift).

### W2 — Pair-breaking completion gate (issue 3)  [S]
- `rank_edges()`: root-proximity bonus for same-target pair edges (break the
  first impression first).
- `_build_phase3` exit condition: may NOT exit while same-target pairs remain
  (root's pair mandatory; others while budget lasts) — pairs-broken joins
  minutes as completion criteria.
- `metrics.py`: new gate `residual_same_target_pairs` (root must be 0).

### W3 — Aftermath blocks (issue 8, simplified)  [M-L]
- `models.Choice.aftermath: list[ContentElement]` — skeleton phase still plans
  2-beat `resolution`; prose phase expands each into a 3–6 element dramatized
  aftermath (same `fill_prose` call — it already receives choices).
- `_PROSE_FILL_SCHEMA`: per-choice `aftermath` arrays in the output.
- Validators: D9 "resolution exactly 2 beats" (skeleton-time) unchanged;
  new prose-time check: every choice has a dramatized aftermath (length floor
  ~150 chars), aftermaths into convergence targets establish no facts outside
  `state_delta`. S1 distinctness reads aftermath texts.
- `budget.estimate_minutes`: 正文 + avg(aftermath durations).
- `web_export`: render aftermath elements as the ━━━ branch sections
  (replaces the 2 stub lines); ending-node prompt note: denouement only.
- Pre-check: confirm webapp player shows the branch section after selection
  before jumping (display format already supports it).

### W4 — First-appearance + namecards (issues 5/7, 爪牙 half of 4)  [M]
- Compute once per run from `compute_node_memories()` (exists):
  `first_appearing(node) = node.cast − memory.known_characters`.
- P3.5 deterministic check: new bible character in cast with no intro beat.
- `fill_prose` payload: 「首次出场（必须 namecard+引入）:[…]」「已认识（禁止
  重复介绍）:[…]」.
- P4.5 deterministic pre-check (before LLM judge): namecard present for every
  first-appearing bible character, absent for repeats → regen feedback.
- Expansion prompt: include known-characters context.
- Convergence falls out of meet semantics (mixed-path characters → neutral intro).

### W5 — Ledger plants as facts (血书 half of 4)  [S-M]
- `_OUTLINE_SCHEMA` ledger entries gain `fact_id`.
- P2/P3 prompts: the node playing a plant `produces` its fact (with `beat`
  anchor); any later reference declares `requires`/`uses`.
- Enforcement: existing D1 + knowledge matrix — no new validator.
- Report-card ledger attribution switches from sequence-heuristic to
  fact-producer lookup (fixes the false "never closed" rows).

### W6 — Concrete labels, consistent questions (issue 6)  [S]
- `CREATIVE_WRITING_SKELETON.md` + cornerstone/expansion prompts: label = 具体
  动作（对象+手段，如 贿银五十两 / 割舌立威）; question poses the same two
  concrete acts.
- NO story-specific blocklists (user: the harness must stay genre-generic;
  a future "category/genre profile" will own genre conventions). Enforcement:
  generic prompt rule (concrete action = object+means, no abstract strategy
  category) + S4 judge checks abstractness and question↔label consistency.

### W7 — Dedicated titles (issue 2)  [S]
- `metadata_fill.py` (P2.5): add `title` (章节式, ≤12字, ≠question) to the
  per-node schema; `Node.title` through models/checkpoint/parse.
- `web_export._node_title`: prefer `node.title`.

## Order & verification

Order: W1 → W2 → W3 → W4 → W5 → W6 → W7 (quality lever first, correctness
gate second, structural change third, then the deterministic-check batch).

Per workstream: unit tests + `--model fake` e2e (fake backend gains aftermath
arrays + title field in W3/W7). After all: one full cached run on 替嫁王妃,
report-card diff against run_20260611_033159, re-upload for review.

RESOLVED (user): the webapp script view shows BOTH branch sections — fine for
review; no player-side change needed for W3.
