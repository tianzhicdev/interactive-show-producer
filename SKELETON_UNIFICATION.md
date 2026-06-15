# Skeleton Unification Design

## Problem

Current architecture has **two representations** of a node's plot: `summary` (free text) and `content`/thin_content (structured beats). These can and do drift apart:

- `n2_forest_confront` summary says "颜如玉脑中浮现透过窗纸听到的翼王原话" but thin content barely references it
- `n1_forest_medicine` produces `char.大夫人.hand_injured` but 大夫人 never appears in the scene
- Phase 3.5 validates thin_content + summary agreement, but can't catch ungrounded back-references that only exist in summary language
- Phase 4.5 validates prose against `reader_has_seen` (built from summaries), but prose pulls from summary too — the same ungrounded source

Root cause: **denormalized state.** Two documents describe the same plot; they can contradict each other and the validator has no single source of truth.

## Proposal

**Merge `summary` and `content` into a single `skeleton` field.** Every node has one canonical description of what happens. Prose is pure aesthetic expansion — no new plot, no new facts, no new characters beyond what skeleton specifies.

---

## 1. Skeleton Schema

### Beat structure

Each skeleton beat is a content element (same types as today: `scene_header`, `action`, `dialogue`, `narration`, `namecard`) **plus** an optional `facts` field linking to produces/requires.

```json
{
  "skeleton": [
    {
      "type": "scene_header",
      "location": "营地外小树林深处",
      "time": "拂晓",
      "characters": ["颜如玉", "账房侄子（霍长鹤）"]
    },
    {
      "type": "action",
      "text": "颜如玉穿入密林，发现账房侄子背靠大树，手搭刀柄，早已等候。",
      "shot": "中景",
      "facts": []
    },
    {
      "type": "dialogue",
      "speaker": "霍长鹤",
      "line": "姑娘好深的夜路。庄园那边火光冲天……",
      "emotion": "声音平静",
      "facts": []
    },
    {
      "type": "narration",
      "text": "颜如玉心思一转，落在空间深处精铁箱上。私囤精铁数量足以武装整支偏师，移祸于人——这条逻辑链走到头只有一个答案。",
      "facts": ["world.yi_wang.motive_revealed"]
    },
    {
      "type": "action",
      "text": "四面树叶沙响，颜松搜索队火把光自三面逼近。",
      "shot": "全景",
      "facts": []
    }
  ]
}
```

### Produces/Requires with beat references

```json
{
  "produces": [
    {"fact": "player.suspects_accountant_nephew", "value": true, "beat": 2},
    {"fact": "char.霍长鹤.assessed_颜如玉", "value": true, "beat": 5},
    {"fact": "world.yi_wang.motive_revealed", "value": true, "beat": 4}
  ],
  "requires": []
}
```

`beat` is a 1-based index into the `skeleton` array. This makes grounding machine-checkable: validator confirms beat N exists and its text establishes the claimed fact.

### Eliminated fields

- `summary` — **removed**. Replaced by `skeleton` beats concatenated (or a derived `get_summary()` method that renders beats to text).
- `content` (thin content) — **renamed to `skeleton`**. Same structure, just unified with what was in summary.

### Derived `summary` for backward compat

Some consumers need a text summary (web export titles, DFS memory). This is derived, not stored:

```python
def get_summary(self) -> str:
    """Render skeleton beats to a compact summary string."""
    # Concatenate beat texts, skipping scene_header/namecard
    parts = []
    for beat in self.skeleton:
        if beat["type"] == "scene_header":
            continue
        if beat["type"] == "namecard":
            continue
        text = beat.get("text", "") or beat.get("line", "")
        if text:
            parts.append(text)
    return "。".join(parts)
```

Or: the skeleton generation LLM also outputs a `summary_text` field that's verified against the beats. This preserves the current summary quality (which is hand-crafted narrative, not just concatenated beat texts) while ensuring it doesn't contradict the beats.

**Decision: keep `summary` as a stored field, but add a deterministic check that it doesn't contradict skeleton beats.** The summary is useful as a human-readable narrative arc. But if it references events not in the skeleton beats, it's a validation error.

---

## 2. reader_has_seen Changes

### Current

```python
reader_has_seen = [
    {"node": nid, "summary": summ}
    for nid, summ in memory.ancestor_summaries[-5:]
]
```

Summaries only — no structured beat data.

### Proposed

```python
reader_has_seen = [
    {
        "node": nid,
        "summary": summary_text,          # still included for LLM readability
        "beats": [beat["text"] for beat in node.skeleton if beat["type"] not in ("scene_header", "namecard")],
        "produces": [{"fact": e.fact, "value": e.value} for e in node.produces]
    }
    for nid, summary_text in memory.ancestor_summaries[-5:]
]
```

This gives the validator both the narrative summary (for context) and the explicit beats (for grounding checks). When the validator sees "颜如玉脑中浮现透过窗纸听到的翼王原话" in the current node, it can check: does any ancestor beat text contain "窗纸" or "翼王原话"? If not, it's an ungrounded back-reference.

### Token cost

Each `reader_has_seen` entry grows from ~100 chars (summary) to ~300-500 chars (summary + beat texts + produces). For 5 entries, that's ~1.5-2.5K chars vs ~500 chars today. Acceptable — the semantic validation LLM call already sends ~4.5K chars of payload.

### Compression option

For convergence nodes where `reader_has_seen` intersects across multiple paths, send only **guaranteed** beats (those present in all parent paths). This is the same logic as today's `_intersect_memories`, just applied to beat sets instead of summaries.

---

## 3. Prose Generation Changes

### Current

Prose generation (`fill_prose`) takes both `summary` and `thin_content` (current `node.content`) as input. The LLM is told to "preserve every plot beat from thin_content and summary" but in practice draws freely from summary for events not in thin_content.

### Proposed

Prose generation takes **skeleton only**. The prompt says:

- "Expand from skeleton beats. Each beat must appear in the output prose."
- "Do not add new plot events, new characters, or new facts beyond what the skeleton specifies."
- "Atmosphere, camera language, sensory detail, fuller dialogue — these are your creative domain."
- "If a fact is tagged on a beat (facts field), the prose for that beat must clearly establish that fact."

The `violation_feedback` path stays the same, but now the LLM has a tighter contract: skeleton beats are the ceiling of what prose can contain. No more drawing from a generous summary to invent ungrounded flashbacks.

### Skeleton must be comprehensive enough

This is the key tradeoff. Currently skeleton (thin content) can be sparse because prose fills gaps from summary. Under the new model, skeleton must contain **every plot beat** that prose needs to render.

Concretely: `n2_forest_confront`'s skeleton must include a beat for the motive deduction (from iron crates), because that's what the prose will render. If the skeleton only says "颜如玉与账房侄子对峙" without the deduction beat, prose has no basis to include it.

**Minimum beat count per node:** increase from 3 to 5 for non-ending nodes. This ensures skeleton covers: scene_header + at least 4 plot beats (setup, escalation, tension peak, choice setup).

---

## 4. Validation Changes

### Phase 3.5 (Skeleton validation) — enhanced

New deterministic checks:

1. **Beat-fact grounding**: every `produces` entry with a `beat` reference must have that beat exist in skeleton, and the beat's text must plausibly establish the fact. (LLM-assisted for plausibility; deterministic for existence.)

2. **No orphan produces**: every `produces` entry must have a `beat` reference. If `beat` is missing or out of range, it's a D-check violation.

3. **Summary-skeleton consistency**: if `summary` is kept as a stored field, it must not reference events/characters/facts that don't appear in any skeleton beat. Deterministic substring check for named entities + LLM check for semantic equivalence.

4. **Beat completeness for produces**: if a beat has a `facts` tag, that fact must also appear in the node's `produces` array. (No tagging without declaring.)

5. **No ungrounded references**: skeleton beat text must not reference events/characters not in `requires`, ancestor beats (from `reader_has_seen`), or earlier beats in the same node. This is the check that would catch "透过窗纸听到的翼王原话" — no ancestor beat depicts this eavesdropping.

### Phase 4.5 (Prose validation) — simplified

Prose validation now checks against skeleton beats, not summaries:

1. **Prose coverage**: every skeleton beat must have a corresponding prose element. (Deterministic: match beat text substrings.)
2. **No new plot**: prose must not introduce events, characters, or facts not present in skeleton beats. (LLM-assisted.)
3. **Fact establishment**: if a beat is tagged with a fact, the corresponding prose section must clearly establish it. (LLM-assisted.)

The key simplification: prose validation no longer needs to guess whether a back-reference is grounded. It just checks: does the current node's skeleton contain this event? If not, does any ancestor's skeleton contain it? Binary, no ambiguity.

---

## 5. Migration Path

### Old checkpoint → new schema

Migration function converts old nodes:

1. `node.skeleton = node.content` (thin content becomes skeleton)
2. Add `facts` tags to skeleton beats by matching `produces` against beat text (LLM-assisted or heuristic)
3. Add `beat` references to `produces` entries (heuristic: match fact to first beat that mentions related keywords)
4. `node.content = []` (cleared; Phase 4 will regen from skeleton)
5. `summary` stays as-is; Phase 3.5 will validate consistency and fix

### Incremental rollout

- Phase 1: Add `skeleton` field to Node (parallel to `content`). Both exist during migration.
- Phase 2: Change skeleton generation prompts to produce `skeleton` with `facts` tags + beat references in `produces`.
- Phase 3: Change `reader_has_seen` to include beats.
- Phase 4: Change `fill_prose` to read from `skeleton` instead of `content`/`summary`.
- Phase 5: Add deterministic beat-fact grounding checks to Phase 3.5.
- Phase 6: Remove `summary` as a stored field (keep as derived) and rename `content` → `skeleton` during skeleton phase.

---

## 6. Affected Code Paths

### High-impact (schema + prompt changes)

| File | Function | Change |
|------|----------|--------|
| `models.py` | `Node` | Add `skeleton` field, add `facts` to ContentElement, add `beat` to Effect |
| `llm.py` | `_SKELETON_NODE_SCHEMA` | New schema: `skeleton` replaces `content`, `produces.beat` required |
| `llm.py` | `_NODE_SCHEMA` | Same |
| `llm.py` | `creative_writing_skeleton` | Prompt: output `skeleton` with `facts` tags |
| `llm.py` | `fill_prose` | Read from `skeleton`, not `content`+`summary` |
| `CREATIVE_WRITING_SKELETON.md` | — | Rewrite for skeleton-with-tags format |
| `CREATIVE_WRITING_PROSE.md` | — | Rewrite: expand skeleton only, no new plot |

### Medium-impact (validation + memory)

| File | Function | Change |
|------|----------|--------|
| `validation.py` | `_post_memory` | Store beat texts in memory, not just summaries |
| `validation.py` | `_validate_thin_content_contract` | Rename → `_validate_skeleton_contract`, add beat-fact checks |
| `llm.py` | `validate_semantic_node` | `reader_has_seen` includes beats |
| `llm.py` | `_skeleton_node_payload` | Send skeleton beats, not thin_content |
| `harness.py` | `_validate_and_fix_skeleton_dfs_semantics` | Add beat-fact grounding check |
| `harness.py` | `_validate_and_fix_semantic_topo` | Simplify: check prose against skeleton |

### Low-impact (derived consumers)

| File | Function | Change |
|------|----------|--------|
| `budget.py` | `estimate_minutes` | Read from `skeleton` |
| `web_export.py` | `_node_title`, `_scene_script` | Read from `skeleton` or derived summary |
| `checkpoint.py` | `_serialize_graph` | Serialize `skeleton` |
| `harness.py` | `_backfill_structured_fields` | Backfill `skeleton` instead of `content` |

---

## 7. Open Questions

1. **Summary as stored or derived?** Keeping summary as stored + validated against skeleton is simpler for backward compat but maintains two sources. Deriving it from beats saves storage but loses narrative quality (concatenated beat texts ≠ hand-crafted summary). Recommend: **keep stored, add consistency check.**

2. **beat index stability?** If skeleton beats are reordered during fix attempts, `produces.beat` references break. Need to either: (a) use stable beat IDs instead of indices, or (b) re-index after every fix. Recommend: **stable string IDs** (`b1`, `b2`, ...) that survive reordering.

3. **Token budget for reader_has_seen?** Adding beats to each of 5 ancestor entries increases payload. May need to truncate beat texts (first 50 chars each) or cap at 8 beats per ancestor.

4. **LLM reliability for facts tagging?** The skeleton generation LLM must correctly tag which beat produces which fact. If it gets it wrong, the grounding check produces false positives. Mitigation: make `facts` on beats optional (validator only checks `produces.beat`, not `beat.facts`). The `beat.facts` tag is a hint for the prose generator, not a validation requirement.

5. **Choice resolution fact linkage?** Currently `produces` is unconditional (applies regardless of which choice the player takes). Should conditional produces (per-choice) also link to beats? This is a separate feature (conditional produces) but the beat-based schema makes it natural: `"produces": [{"fact": ..., "value": ..., "beat": ..., "choice": 1}]`.
