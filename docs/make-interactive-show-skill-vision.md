# Make Interactive Show — Skill Vision

## Problem Statement

The current `/make-interactive-show` skill produces episode-level graphs that are **too linear**:

```
EP01 → [EP02 | EP03 | EP04] → EP05 → EP06 → EP07 → EP08
         (one fork)            (converge)  (linear to end)
```

All branching happens **within** episodes (scene-level), but the **episode flow itself** is a simple diamond-then-line. A player watching EP05→EP08 has the same episode sequence regardless of which route they chose earlier. This undermines replayability and makes the overview graph look like a railroad.

## Solution: Stats-Driven Episode Branching

### Core Concept

Every choice modifies **numeric stats** (e.g., courage, wealth, affection, reputation). When stats cross **thresholds**, the player is routed to **different episodes** — not just different scenes within the same episode.

This turns the episode graph from a diamond into a **web**:

```
         ┌─ EP02a ─┐     ┌─ EP05a ─┐
EP01 ─┬──┤         ├──┬──┤         ├──┬── EP07 ── EP08 (multiple endings)
      │  └─ EP02b ─┘  │  └─ EP05b ─┘  │
      │                │               │
      └── EP03 ───────┴── EP06 ───────┘
```

### Stats System Design

Each show defines **3-5 stats** appropriate to the story. Stats are:

| Property | Description |
|----------|-------------|
| **Name** | e.g., `courage`, `wealth`, `affection_若涵`, `reputation` |
| **Initial value** | Starting value (default: 50, range: 0-100) |
| **Thresholds** | Levels that trigger episode branching (e.g., `< 30 = low`, `> 70 = high`) |

**How stats flow:**

1. **DESIGN phase** defines stats and thresholds for the story
2. **Each choice option** includes `stats_changes` (e.g., `courage +10, wealth -5`)
3. **Episode transitions** check stat values against thresholds
4. **Different episodes** are unlocked/locked based on accumulated stats

### Episode Graph Rules

Replace the rigid fork-converge-linear pattern with:

1. **Stat-gated episodes**: EP03a requires `wealth > 60`; EP03b is the fallback
2. **Multi-path convergence**: Multiple episodes can converge at different points, not just one
3. **Late divergence**: Stats can cause branching even in EP06/EP07, not just the early fork
4. **Dead-end episodes**: Extreme stat values (e.g., `reputation < 10`) can trigger early endings
5. **Shared episodes**: Some episodes play for all paths but with stat-conditional scenes within

### Example: 8-Episode Show with Stats

Stats: `courage`, `reputation`, `romance`

```
                    ┌── EP03a (courage > 60) ──┐
EP01 ── EP02 ──┬───┤                           ├───┬── EP05 ──┬── EP07a (romance > 70)
               │   └── EP03b (courage ≤ 60) ──┘   │          │
               │                                    │          ├── EP07b (default)
               └───── EP04 (reputation > 50) ──────┘          │
                                                               └── DEAD END (reputation < 20)
               EP06 unlocked only if EP04 was played
```

**Key differences from current system:**
- No single "fork point" — branching happens at **every episode transition**
- Stats accumulate across the whole show, creating **emergent paths**
- Player can't predict which episodes they'll see — creates genuine replayability
- Overview graph is a **directed acyclic graph**, not a diamond

---

## Three-Skill Architecture

### 1. `/make-interactive-show-preview`

**Purpose:** Quick iteration. Generate only the story bible, structure, and graphs — no scripts. Lets the creator review the interactive design before committing to full script generation.

**Input:**
- `--file` (required): Path to story text file
- `--episodes` (optional): Number of episodes (default: 6)
- `--user-selections-per-episode` (optional): Decisions per episode (default: 2-4)
- `--options-per-selection` (optional): Options per decision (default: 2-4)
- `--note` (optional): Creative direction notes
- `--lang` (optional): Language (default: zh)
- `--output` (optional): Output directory

**Pipeline:**
```
CHUNK → DISTILL → BIBLE → DESIGN (with stats system) → RENDER (summary + graphs only)
```

**Output:**
```
project_dir/
├── args.json
├── state.json          ← Contains bible + structure, NO scripts
├── story_bible.json
├── structure.json      ← Includes stats definitions + thresholds + episode gating
├── chunks/
│   └── ...
└── output/
    └── 互动剧本_[Title]_预览.pdf   ← Cover + summary + graphs (no scripts section)
```

**Key behavior:**
- Fast — skips script writing, verification, evaluation, revision
- The preview PDF shows the **episode-level graph** prominently so creator can evaluate branching
- Graph should visualize stat thresholds on edges (e.g., "courage > 60" labels)
- State.json is saved and can be passed to `/make-interactive-show` for full generation

---

### 2. `/make-interactive-show`

**Purpose:** Full pipeline. Can start from scratch OR continue from a preview's output.

**Input:**
- `--file` (required): Path to story text file **OR** path to a preview's `state.json` / project directory
- `--min-duration` / `--max-duration` (optional): Total duration range
- `--episodes` (optional): Number of episodes
- `--user-selections-per-episode` (optional): Decisions per episode
- `--options-per-selection` (optional): Options per decision
- `--note` (optional): Creative direction notes
- `--lang` (optional): Language
- `--output` (optional): Output directory

**Pipeline:**

*From scratch:*
```
CHUNK → DISTILL → BIBLE → DESIGN → SCRIPT → VERIFY → EVAL → REVISE → RENDER
```

*From preview state.json (has bible + structure but no scripts):*
```
SCRIPT → VERIFY → EVAL → REVISE → RENDER
```

**Detection logic:** If `--file` points to a `state.json` or directory containing one, check if `scripts` field is empty. If so, skip to SCRIPT phase using existing bible + structure.

**Output:** Same as current — full PDF + per-episode DOCX + state.json.

---

### 3. `/make-interactive-show-modify`

**Purpose:** Modify an existing completed project without full regeneration.

**Input:**
- `--file` (required): Path to `state.json` or project directory (must contain scripts)
- `--note` (required): Modification description
- `--episodes` (optional): Change episode count
- `--lang` (optional): Language

**Pipeline:**
```
ANALYZE → IDENTIFY affected components → REGENERATE affected scripts → VERIFY → EVAL → REVISE → RENDER
```

**Key behavior:** Same as current modify skill — loads completed state, applies targeted changes, re-verifies.

---

## Skill Input/Output Flow

```
                        Story text file
                              │
                              ▼
                ┌─────────────────────────┐
                │ /make-interactive-show-  │
                │        preview           │
                │                          │
                │ Phases: CHUNK → DISTILL  │
                │ → BIBLE → DESIGN         │
                └────────────┬────────────┘
                             │
                   state.json (no scripts)
                   + preview PDF (graphs)
                             │
                    Creator reviews graphs
                    and structure...
                             │
                             ▼
                ┌─────────────────────────┐
                │ /make-interactive-show   │
                │                          │
                │ Detects existing state → │
                │ Phases: SCRIPT → VERIFY  │
                │ → EVAL → REVISE → RENDER │
                │                          │
                │ OR from scratch:         │
                │ Full 9-phase pipeline    │
                └────────────┬────────────┘
                             │
                   state.json (with scripts)
                   + full PDF + DOCX files
                             │
                    Creator reviews full
                    scripts, wants changes...
                             │
                             ▼
                ┌─────────────────────────┐
                │ /make-interactive-show-  │
                │        modify            │
                │                          │
                │ Phases: ANALYZE →        │
                │ REGENERATE → VERIFY →    │
                │ EVAL → REVISE → RENDER   │
                └─────────────────────────┘
```

---

## Stats System Specification

### Stats Definition (in `structure.json`)

```json
{
  "stats": {
    "definitions": [
      {
        "id": "courage",
        "name": "勇气",
        "description": "面对危险和未知时的决断力",
        "initial_value": 50,
        "range": [0, 100],
        "thresholds": {
          "low": 30,
          "high": 70
        }
      },
      {
        "id": "wealth",
        "name": "财富",
        "description": "经济资源和商业影响力",
        "initial_value": 30,
        "range": [0, 100],
        "thresholds": {
          "low": 20,
          "high": 60
        }
      }
    ]
  }
}
```

### Episode Gating (in `structure.json`)

```json
{
  "episodes": [
    {
      "id": "EP03a",
      "title": "商战风云",
      "gate": {
        "condition": "wealth > 60",
        "fallback_episode": "EP03b"
      }
    },
    {
      "id": "EP03b",
      "title": "草根求生",
      "gate": {
        "condition": "default",
        "description": "Plays when EP03a gate is not met"
      }
    }
  ]
}
```

### Choice Stats Changes (already partially supported)

```json
{
  "options": [
    {
      "label": "A",
      "text": "冒险投资",
      "stats_changes": {
        "courage": 10,
        "wealth": -15,
        "reputation": 5
      },
      "leads_to": "EP02-C3.A"
    }
  ]
}
```

### Episode Transition Logic

At the end of each episode, before transitioning to the next:

```
1. Sum all stats_changes from choices made so far
2. Evaluate gate conditions for candidate next episodes
3. Route player to the first episode whose gate condition is met
4. If no gate is met, route to fallback/default episode
```

### Graph Visualization

The overview graph should show:
- **Episode nodes** as usual (boxes with title)
- **Stat-gated edges** with threshold labels (e.g., "勇气 > 70")
- **Fallback edges** as dashed lines (e.g., "default")
- **Dead-end nodes** for extreme stat values
- **Stat icons/colors** to visually distinguish which stat gates which path

---

## Episode Structure Templates

Replace the rigid fork-converge pattern with flexible templates:

### Template A: "Widening Web" (recommended for 6-8 episodes)

```
EP01 (shared) → EP02 (shared, choices set stats)
  → EP03a / EP03b (stat-gated fork)
    → EP04a / EP04b / EP04c (further stat-gated)
      → EP05 (partial convergence, stat-conditional scenes)
        → EP06a / EP06b (late divergence)
          → EP07/EP08 (endings, stat-determined)
```

### Template B: "Braided River" (for 8-12 episodes)

```
Multiple parallel strands that cross and re-cross:
EP01 → EP02a/b → EP03 (merge) → EP04a/b/c → EP05a/b → EP06 (merge) → EP07a/b → EP08 (endings)
```

### Template C: "Funnel" (for 4-6 episodes, high replayability)

```
Wide start, narrow end:
EP01a/b → EP02a/b/c → EP03a/b/c/d → EP04 (convergence) → EP05 (stat-determined ending)
```

The DESIGN phase should pick the template based on episode count and story structure, then customize it with story-specific stat gates.

---

## Evaluation Criteria Updates

The eval criteria dimension **D5 (System Depth)** already requires:
- 2+ cross-episode variables
- 1+ threshold trigger
- 1+ conditional outcome

The stats system makes this **structural** rather than something tacked on. Additional eval focus:

- **Episode-level branching score**: How many distinct episode sequences exist? (Target: at least 3 unique paths through the show)
- **Stats meaningfulness**: Do stats actually change the story, or just cosmetic differences?
- **Replayability**: What % of total content does a single playthrough see? (Target: ≤ 50%)

---

## Preview PDF Spec

The preview PDF contains:

1. **Cover page** — Title, episode count, stat definitions
2. **Story summary** — One-line summary, world, characters, plot
3. **Stats overview** — Table of stats with thresholds and what they gate
4. **Episode-level graph** — Full DAG showing all possible episode paths with stat gates on edges
5. **Per-episode structure** — For each episode: title, scenes list, choices list, stat changes summary, gate conditions
6. **Replayability analysis** — Number of distinct paths, content ratio estimate

No scripts. No per-episode scene graphs. Just the high-level design for quick review.

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| Episode graph | Diamond → line | Stats-driven DAG (web) |
| Branching mechanism | Single fork point | Stat thresholds at every transition |
| Replayability | ~3 routes (A/B/C) | Combinatorial paths from accumulated stats |
| Preview capability | None (full pipeline or nothing) | Dedicated preview skill |
| Iteration speed | Regenerate everything | Preview → approve → generate → modify |
| Stats | Mentioned in scripts but decorative | Structural — gates entire episodes |
