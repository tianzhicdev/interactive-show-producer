# Problems

---
guide:
we are trying to produce interactive movies about 60 mins (with all the forks it is 90 mins or so); coz it is short we expect every 3 to 5 mins a dramatic peak to seize the attention of the viewers/players (feel free to do some research on this).  


## 1. No Main Line — First Fork Never Converges

The very first choice splits the graph into two completely separate stories that never rejoin. Zero convergence points in the entire DAG. The player picks a branch at the root and rides it to an ending — no moment where different paths intersect.

What we want: a main trunk carrying the core plot, with side branches that fork off and **converge back**. The player should hit the same pivotal moments regardless of earlier choices; only the *stakes* and *flavor* differ by path.

---

## 3. Bottleneck Nodes Dump Entire Arcs as Narration

A single node can span 4+ locations and dozens of beats, compressing what should be playable scenes into narration. The player reads about the climax instead of playing through it. Key dramatic events — heists, confrontations, discoveries — happen off-screen in summary text.

Downstream nodes then reference events the player never actively experienced, only read about in passing. If an event matters enough for a downstream node to reference, the player should have played it.

---

## 4. No 爽点 (Gratification Point) Tagging

Highlights have weight and gloss, but no dramatic type information — no `satisfaction_type` (e.g., face_slap, hidden_power, loot_sweep, identity_reveal) and no `hook_type` (e.g., suspense, emotional, crisis). The pipeline knows a moment is "important" but not *why* it's satisfying or *what* it sets up.

Result: payoff moments get narrated past instead of played. The player never feels the hit. we need DRAMA in the show. 

---

## 5. Choices Are Investigation Menus, Not Dilemmas

Nearly every question is a "pursue the clue vs hold back" variant. These are information-gathering decisions — safe/suspicious vs bold/cautious. Neither option has emotional stakes, irreversible consequences, or moral weight.

The five dramatic tension modes (moral conflict, risk asymmetry, character test, NPC expectation, irreversibility) are absent. The player's heart never races because nothing is at stake in the choice itself.

---

## 6. Summary-Compression Hides Player Actions

When multiple events are compressed into one node, they exist only in summary/skeleton text. Downstream nodes reference them as if the reader experienced them, but the reader only skimmed past them in narration. This is the same root pattern as the eavesdropping bug — important scenes become flashbacks the reader never lived through.

---

## Summary Table

| # | Problem | Symptom | Root Cause |
|---|---------|---------|------------|
| 1 | No main line, first fork never converges | Two unrelated stories, zero convergence | No structural constraint on DAG shape |
| 2 | Branches are thematically disconnected | Player sees one theme or the other, never both | No main-trunk requirement; expansion picks edges independently |
| 3 | Bottleneck dumps arcs as narration | Player watches climaxes instead of playing them | No beat cap or location cap in validation |
| 4 | No 爽点/hook typing | Player never feels payoff | Highlight mining drops dramatic type info |
| 5 | Choices are investigation menus | Zero emotional stakes in choices | No tension mode enforcement |
| 6 | Summary hides player actions | Downstream references to unplayed events | Bottleneck compression + no beat-level grounding |

---

## Dev's Note: Per-Node Episode Template

Perhaps every non-DEAD_END node should follow a fixed beat template:

1. **Build-up** — tension rises, stakes become clear
2. **Gratification (爽点)** — payoff moment the player actively triggers
3. **New surprising event** — something unexpected that reframes the situation
4. **User choice** — genuine dilemma forced by the surprise

This would guarantee every node has dramatic structure instead of being a flat sequence of events. But this needs discussion:
- Does this work for every node type (prologue, bottleneck, scene)?
- Is the "surprising event" always natural, or does it feel forced?
- Should DEAD_END nodes also follow a truncated version (build-up → catastrophe)?
- How does this interact with the beat cap — does 4 mandatory beats leave room for the story?
