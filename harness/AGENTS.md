# AGENTS.md — What This Harness Is


## The One Rule

**The harness is a story-agnostic creative writing engine. It knows NOTHING about
any specific story — no characters, no settings, no plot points, no fallback prose.**

Every word of story content comes from exactly two sources:
1. **The source novel** (raw text fed in at runtime)
2. **The LLM** (generating from that source novel)

The harness code itself NEVER:
- Contains character names, place names, or dialogue in any language
- Provides "default" or "fallback" prose content, not even empty strings
- Pads short content by repeating generic paragraphs
- Invents filler text to meet length requirements
- Uses placeholder strings like "主角", "此地", "当前" or even "" as content the reader sees

## Structured LLM Boundary

Every LLM call that returns machine-consumed data MUST use a predefined JSON
schema at the call boundary. This applies to bible extraction, highlights,
cornerstone skeletons, expansions, repair calls, semantic validation, plot
fixes, question fixes, and prose generation.

The harness must not accept loosely parsed JSON for machine data:
- No ad-hoc "return any JSON object" calls for production pipeline outputs.
- No JSON arrays encoded as strings inside object fields.
- No fallback from schema output to free-text extraction when a schema was requested.
- Parsed output must be validated against the schema before checkpointing,
  merging, exporting, or uploading.

If schema output fails, retry or fail/skip according to the pipeline phase. Do
not coerce malformed reader-visible content into shape by inventing prose.

## Long-Context Compression Boundary

Long source text MUST be compressed before later creative phases consume it.
Prefer more small schema-validated calls over one large call that mixes many
chapters, many objectives, or large outputs.

Phase 1 extraction uses map/reduce:
- Split by natural story boundaries first: chapter, scene break, then paragraph.
- Target extraction chunks around 4,000-8,000 Chinese characters for narrative
  source text. Keep a small adjacent-context window when a split may lose setup.
- For bible extraction, run a schema call per chapter/window, then merge the
  compact outputs deterministically into the final bible shape.
- For highlights, run a schema call per chapter/window, then dedupe and reduce
  to the strongest globally useful beats before ranking expansion edges.
- Never send the full raw novel to later phases when a chapter index, highlights,
  compact bible, summaries, or weighted spans can provide the required context.
- Verbose logs must show chunk/window counts, sizes, chapter coverage, extracted
  item counts, and reduction counts so failures are diagnosable economically.

Chunk sizing is not a fixed law. If a call is slow, times out, returns malformed
schema, or produces oversized output, reduce chunk size before increasing retry
count.

Phase 4.5 semantic validation is intentionally lightweight:
- Prior phases already validated cornerstone shape, each expansion, DFS skeleton
  logic, thin content, prose schema, and final deterministic graph rules.
- Validate one node at a time using compressed DFS reader memory only.
- Pass rendered `content_text`, not the full structured `content[]`, unless a
  specific repair path needs structure.
- Cap reader memory before the LLM call: recent guaranteed ancestor summaries,
  guaranteed fact glosses, known characters, and the last scene context.
- Use Phase 4.5 to catch path-dependent references, choice/question mismatch,
  prose-vs-skeleton contradiction, and missing `produces` for newly dependent facts.
- Do not run a full-graph semantic audit here; that is too slow and less
  actionable than node-scoped feedback.

Skeletons also have a pre-prose semantic gate:
- Phase 3.5 runs DFS/memory + local contract checks over ALL skeleton nodes
  in topological order, using guaranteed reader memory. It validates:
  - `skeleton` beats (thin plot), `requires`, `produces` before prose
  - Path neutrality at convergence nodes
  - Local contract consistency: `skeleton` beats, unconditional
    `produces`, `question`, `planned_duration_min`, and `choice.resolution`
    must not contradict each other
  - If a choice can make a fact differ by branch, that fact must not be
    declared in the node's unconditional `produces`
- The fixer may edit the local skeleton contract AND propagate fixes upstream
  to parent nodes (e.g. moving a produce from the current node to a parent's
  choice edge). Deterministic validation must pass again before Phase 4.

## What the Harness DOES

The harness is the **deterministic control plane**. It:
- Chunks, indexes, and routes source material to the LLM
- Validates LLM output (structure, state coherence with IO checks, graph shape)
- Retries when the LLM fails
- Gives up on an edge and moves to the next one when retries are exhausted
- Exports the validated graph to the webapp

## If the LLM Fails

When the LLM produces garbage or nothing:
- **Retry** with feedback (up to `max_fix_attempts`)
- **Skip the edge** and try the next one (`_non_expandable_edges`)
- **Never fill in fake content** — a missing node is better than a garbage node

The harness prefers a smaller, well-written graph over a larger graph padded with
generic filler. 5 excellent nodes > 15 nodes where 8 are copy-pasted garbage.

## Runtime and Timeout Policy

The harness is allowed to run for a long time when that is required to produce a
deterministically valid graph and web-app export. Do not shorten validation,
skip semantic gates, or replace LLM output with fallback content just to finish
quickly.

Default Claude Code subprocess behavior:
- Timeout per `claude -p` call: 20 minutes (`CLAUDE_CODE_TIMEOUT_S=1200`)
- Timeout retries per `claude -p` call: 10 (`CLAUDE_CODE_TIMEOUT_RETRIES=10`)
- Harness repair/validation loops also default to at least 10 attempts for
  schema, cornerstone, expansion, skeleton semantic, and prose repair paths.

CLI model selection:
- Prefer `--model cc`, `--model deepseek`, or `--model glm`.
- `--cc` remains a compatibility alias for `--model cc`.
- `--model deepseek` uses Fireworks `accounts/fireworks/models/deepseek-v4-pro`.
- `--model glm` uses Fireworks `accounts/fireworks/models/glm-5p1`.
- A raw Fireworks model id beginning with `accounts/` may also be passed to
  `--model`.

Long waits are acceptable. The preferred failure mode is an explicit, logged,
actionable validation or timeout error after exhausting the configured attempts,
not a premature skip or partial export.

## For the Coding Agent

When modifying this codebase:

1. **Never hardcode prose** — no Chinese text in Python files except log messages,
   error descriptions, and structural format tokens (场, 景, 时, 人, ▲, 选择, etc.)
2. **Never add padding loops** — if content is short, that's fine
3. **Never duplicate content** — `content + content` is always wrong
4. **Format tokens are structural, not content** — `场：`, `时：`, `▲` are format
   markers the webapp parser needs. They are NOT story content.
5. **Fallback = skip, not fill** — if you can't generate good content, mark the
   edge non-expandable and move on. Don't invent prose.
6. **Test with multiple stories** — any change must work on wuxia, horror, esports,
   sci-fi, romance. If your code mentions a character name, it's wrong.
7. **Update AGENTS.md** — when making critical architectural changes (adding/removing
   phases, changing the pipeline flow, modifying instruction files), update this file
   to reflect the new reality.

## Architecture

The pipeline runs in two stages. **Stage A (Skeleton)** designs the whole
branching story as thin plot — structure, facts, and choices, but no
reader-facing prose. **Stage B (Prose)** writes the narrative on top of the
accepted skeleton. See [Terminology](#terminology) for what each term means.

**Phase-numbering convention** (the log strings in `harness.py` use these exact
labels — keep the doc in sync with the logs):
- **Whole numbers** (`1`, `2`, `3`, `4`) are *build* phases that create or grow content.
- **`.5` suffix** (`3.5`, `4.5`) is the *semantic gate* that validates the build
  phase before it. `3.5` gates the skeleton before prose; `4.5` gates the prose.
- **Letter `C`** is the *competing-goods choice* quality gate. It runs once,
  graph-wide, after expansion and before prose.

### Stage A — Skeleton (structure + thin plot, no prose)

```
  Phase 1 — Extraction (harness.py:267-417)
  Reads raw novel text and extracts the building blocks:
  - 1a  Chapter index from text markers
  - 1b  Chunk the text (map/reduce prep)
  - 1c  Story bible (characters + world) — per-chunk in parallel, then merged.
        Each character gets a 250-350 Chinese-character background blurb
        (出身/性格/处境/关系, no plot spoilers).
  - 1d  Highlights — per-chunk parallel, then reduced.
  - Outline — generate the outline plan -> outline.json (see Terminology).

  Phase 2 — Cornerstone (harness.py:419-437)
  Builds the cornerstone skeleton (the trunk: main-spine nodes) from the
  outline via get_cornerstone_nodes(), then stabilize_cornerstone() loops
  validate->auto-fix->LLM-repair until deterministic (D*) and LLM violations
  are both clean. Skeleton beats + facts + question + 2 choices per node.
  No prose.

  Phase 3 — Expansion (harness.py:546-657)
  Grows branches off the trunk. Iteratively ranks edges (rank_edges), picks
  an expansion type (fork/excursion), and expands edges in parallel --
  merging + revalidating after each. Expansion nodes are also full skeleton
  (question + 2 choices included; choices are CREATED here, not later).
  Loops until the time budget is met or no expandable same-target pairs
  remain; anti-spin guard stops after 3 no-progress rounds. No prose.

  Phase C — Choice Quality Gate / competing goods (harness.py:768-789)
  Graph-wide pass over the finished skeleton. Does NOT create choices --
  it only REPAIRS existing ones: detects choice defects (dominated option /
  no-pull / method-question) and recasts the question + both options into
  genuine competing goods. Runs once, before prose.

  Phase 3.5 — Skeleton Semantic Gate (harness.py:791-793)
  DFS validation of skeleton semantics (computes reader-known facts at each
  node entry) and fixes D and S violations -- still no prose. Last gate
  before Stage B.
```

### Stage B — Prose (narrative writing + final validation)

```
  Phase 4 — Prose Generation (harness.py:795-884)
  Topological order, then parallel fill_prose() across worker threads to
  write reader-facing content[] per node, expanding the accepted skeleton
  beats into prose. Each call carries compressed DFS reader-memory from
  parent nodes. Resume skips already-prosed nodes; first-episode mode fills
  only the root.

  Phase 4.5 — Prose Semantic Gate (harness.py:887-921)
  Validates prose + skeleton constraints in topological/DFS order, computes
  reader memory at convergence points, fixes semantic (S*) violations, and
  auto-fixes terminal markers (ENDING/DEAD_END).

  Final — Validation & Export (harness.py:923-957)
  Full validate(); self-heals D9 prose-length violations by re-filling with
  length feedback if the LLM budget allows; writes the report card, then
  exports + uploads deterministically.
```

### Terminology

One canonical meaning per term. Use these consistently in code, logs, and docs.

| Term | Meaning |
|------|---------|
| **Outline** (`outline.json`) | The Phase-1 story-architecture plan: `main_dramatic_question`, 5-7 `sequences` (Gulino units with span %, local dramatic question, scheduled highlights), a `ledger` of narrative obligations (question/setup/dangling_cause/irony/motif), and 2-4 `player_stats` axes. Later phases *realize* the outline; they never redesign it. |
| **Skeleton** | A node's thin plot record: an ordered list of beat elements (`scene_header` / `action` / `dialogue` / `narration` / `namecard`) plus its facts (`requires` / `produces`), `question`, and 2 `choices`. **No prose.** Created in Phases 2-3. It is the single, authoritative plot source for the node. |
| **Cornerstone** | The *trunk* skeleton — the main-spine nodes built directly from the outline in Phase 2 (`get_cornerstone_nodes`). "Cornerstone" = the subset of the skeleton that forms the backbone; Phase 3 expansion adds branches off it. |
| **Trunk / branch / expansion** | Trunk = cornerstone nodes (Phase 2). Branches = nodes added by expansion (Phase 3). "Expansion" is the act of growing a branch off an existing edge. |
| **Prose** | The reader-facing narrative `content[]` written in Phase 4 by expanding the accepted skeleton beats. `content` is initialized as a deep copy of `skeleton`, then enriched. |
| **`summary`** | NOT a stored field. `Node.get_summary()` derives a plain-text plot digest on demand by concatenating the skeleton beats. See ["Skeleton is the Sole Plot Source"](#skeleton-is-the-sole-plot-source-no-separate-summary) below. |
| **Fact** (`requires` / `produces`) | A named story state a node consumes (`requires`) or guarantees (`produces`). Drives convergence path-neutrality and semantic validation. |
| **Convergence node** | A node with >1 parent. Its skeleton/prose must be path-neutral — true regardless of which branch the reader arrived from. |
| **Choice / question** | Every non-terminal node has exactly 2 choices and one `question`. Both are CREATED during skeleton (Phases 2-3) and only REPAIRED in Phase C. |

### Time Budget

Two independent budgets — do not conflate them.

**1. Time budget** — controls how *big* the story graph gets (target runtime minutes).
- `total_budget_min` (default 100, `--total`): target total runtime summed across
  all nodes. Phase 3 expansion loops until `total_minutes(graph) >= total_budget_min`.
- `words_per_min` (default 300): Chinese reading speed used to convert characters → minutes.
- `planned_duration_min`: each node's *declared* minute budget, set during skeleton.
  Range: non-DEAD_END 3.0-5.0 min, DEAD_END 1.0-1.5 min.
- The **same metric (minutes) is measured differently in each stage** (`budget.estimate_minutes`):
  - **Skeleton stage** (thin content): minutes are *projected* —
    `max(planned_duration_min, skeleton_chars × 7.5 / words_per_min)`. The 7.5×
    factor projects how much the thin skeleton will grow once prose is written
    (measured empirically; budgeting on `planned_duration_min` alone ran ~2× short).
  - **Prose stage** (filled content): minutes are *measured* from the actual prose
    char count (counting one average aftermath branch per choice).

### Instruction Files

| File | Phase | Purpose |
|------|-------|---------|
| `CREATIVE_WRITING_SKELETON.md` | 2, 3 | Skeleton generation: structure, facts, choices, plot beats (skeleton is the sole plot source) |
| `CREATIVE_WRITING_PROSE.md` | 4 | Per-node prose enrichment: content array with elements |
| `CREATIVE_WRITING.md` | (legacy) | Original combined instructions, kept as reference |
| `VALIDATION.md` | Final | Semantic validation rules for LLM-based S-checks |

### Why Skeleton-First?

The previous approach generated prose inline during cornerstone and expansion.
This caused structure collapse: D9 content checks triggered during stabilization,
the LLM rewrote entire graphs to "fix" missing content, destroying the structure.

Skeleton-first separates concerns:
- **Phases 2-3**: Focus on graph structure, facts, choices, and thin plot content
- Skeleton nodes must include `planned_duration_min`; budget/ranking use this
  planned final duration until Phase 4 expands prose.
- `planned_duration_min` range: non-DEAD_END nodes 3.0-5.0 minutes; DEAD_END
  nodes 1.0-1.5 minutes.
- **Phase 3.5**: Validate skeleton story logic before expensive prose
- **Phase 4**: Focus on writing quality from the accepted thin content

Every arrow is LLM-generated content validated by deterministic code. The harness
never authors content — it only validates, retries, and routes.

### Skeleton is the Sole Plot Source (no separate `summary`)

A node's `skeleton` (list of beat elements: scene_header / action / dialogue /
narration / namecard) is the single, authoritative record of the node's plot.
There is **no** stored `summary` field on `Node`. `Node.get_summary()` ALWAYS
derives a plot summary from the skeleton beats, so it can never drift from the
plot the prose is generated against.

Consequences for anyone editing the pipeline:
- Skeleton/expansion/fix prompts must NOT ask the LLM for a `summary` field; the
  beats themselves must carry every character, event, dialogue point, item, and
  turn. The node JSON schema has no `summary` property.
- Convergence path-neutrality and semantic "ungrounding" fixes rewrite the
  **skeleton** (via `_rewrite_skeleton_from_fixed_summary`) and clear `content`,
  never a `summary` field.
- Anything needing a node's plot text (semantic judge payloads, prose context,
  metadata fill, display/export) calls `node.get_summary()` — the derived value.
- The webapp `dag_nodes.summary` column is fed by `web_export._node_summary()`,
  a separate scene-metadata subtitle (location · time · characters), unrelated to
  plot. The whole-story `story_summary` is also separate and unaffected.
