# Morning Report 2 — Choice-Design Research, Implementation, and the v2.4→v2.5 Comparison

*Overnight session 2026-06-11 23:00 → 06-12 morning. Your instruction: research
choice/question design, write it up, implement, rerun.*

## TL;DR

- Research done and distilled into **`harness/CHOICE_DESIGN.md`**: 14 checkable
  rules + a 12-archetype option menu, from CoG doctrine, Mawhorter/Dunyazad
  formal choice poetics, Failbetter/inkle GDC material, agency studies, and
  Chinese 互动剧 design analyses. Your two complaints map to *named formal
  defects*: 「冷眼退避」= unpurchased opt-out (R2/R6) with asymmetric support
  (R3); the 精铁密信 question = stakes-tier mismatch (R1/R8) + certainty
  asymmetry (R4 — the documented *Papers, Please* tilt mechanism).
- Implemented: archetype-menu generation order (gain+price BEFORE label),
  deterministic checks (bare opt-out labels, 还是-contrast required in stems,
  parallel label form), and an S1 judge rubric with a **three-persona vote
  test** (every option must be somebody's first pick).
- **v2.5 choice quality, measured**: dominated options **8 → 3**; every
  question carries explicit double-sided stakes; retreat options all purchased;
  the finale is a 3-way fan testing different competencies.

## v2.4 → v2.5, same nodes, before and after

**Before (v2.4)** — costs absent, all-gain impacts, stems hide stakes:
- t2: 「内忧外患，以力服人还是以智破局？」 → 拆穿挑拨破局 {守护霍家:+1} /
  整顿霍家立威 {守护霍家:+1, 护婆母幼弟:+1} — *both options only gain; nothing
  to agonize over; both flagged dominated.*
- n1: 冷言震慑立威 {守护霍家:+1} — dominated, no price anywhere.

**After (v2.5)** — R7 stems, purchased retreats, same-tier collisions:
- n1: 「为立威冒暴露之险，还是忍屈辱保暗中布局？」
- exp_n1: 戴面具潜庄园 (cost: 婆母幼弟无人守护、被发现则死罪;
  报恩+1/护家−1) vs 留队守婆母 (cost: **永远失去查明翼王阴谋的机会**;
  报恩−1/护家+1) — symmetric stakes, both sides a real loss.
- exp_n2_1: 拼杀逼退探敌踪 (受伤暴露风险) vs 隐入暗影速脱身 (错失探知身份
  良机) — the "retreat" buys safety and pays in intel: R2 satisfied.
- t4 finale: 三选项 拔刀硬战突围 / 以证为饵引敌 / 舍身断后保全 — three
  different competencies, no opt-out (the CoG ternary rule).

Residual: 3 dominated options remain (e.g. exp_n2's 搜刮私库报复 at +1/+1/+1 —
its sibling is all-negative, so the *impacts annotation* of that pair needs
work more than the writing); some impacts were empty pre-P2.5 and get filled
by the metadata pass.

## What was implemented (beyond the rulebook)

1. `CHOICE_DESIGN.md` rules embedded in ALL skeleton-generation prompts — as a
   ~400-token **digest** (see lesson below); full text powers the S1 judge
   rubric in VALIDATION.md (persona vote, benefit audit, tier check,
   certainty audit).
2. Deterministic D9 slices: bare opt-out labels (退避/旁观/沉默… without an
   object/benefit), questions without 还是/或 contrast, label length gap >3.
3. Batch-4 verification from v2.4's full run: **trigger_beat on 15/15 choice
   nodes** (choice-at-peak machinery fully live), goal-vocab violations
   **zero** (was the #1 residual), aftermath/target duplicate-scene check
   active, dead-end budget honored, post-prose path floor live.

## Hard lessons (written to memory)

- **Prompt-size ceiling for structured output**: embedding the full 1.5k-token
  rulebook in the cornerstone prompt collapsed glm-5p1's trunk JSON **twice in
  a row** (12-18k reasoning tokens, then a degenerate 1-node tail). The
  ~400-token digest fixed it on the first try. Rule: generation prompts get
  digests; judges and humans get the full text.
- **Collapse guard**: a trunk below `2 + min_endings` nodes now triggers
  cache-invalidation + regeneration (up to 3×) instead of letting stabilize
  flail on a stump.
- **Auto-stub**: responses that omit the immutable A/B endpoint stubs get them
  reinserted deterministically instead of burning an LLM repair call.

## Run state & links

- **v2.4 (pre-upgrade baseline, complete)**: 19 nodes, 4/4 gates, 0 remaining
  violations — https://hudongju.net/project/c57cef6d-719b-4fc4-b60e-606a8f43e217
- **v2.5 (choice-design upgrade)**: structure complete (18 nodes, all trunk
  pairs broken, dead-end budget met); at time of writing the final pair-break
  call is riding out a Fireworks 504 storm, with the validation chain
  (P2.5 → 3.5 → prose → 4.5 → lint) running. Live view (updates as it
  builds): https://hudongju.net/project/97da2594-a247-4141-a4f9-fe128477d9fa

## Next-batch candidates

1. The 3 residual dominated options → P2.5 impacts re-annotation rule ("if one
   option is all-positive, re-examine: what does it cost?").
2. 4.5 wall-clock (2h on 19 nodes) → parallel judges (the known top
   optimization).
3. The D-refactor pass from BATCH4_PLAN (module split etc.) — still queued,
   still gated on a banked good run.
