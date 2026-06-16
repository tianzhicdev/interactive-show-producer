# Curated backlog (human-editable)

**The loop optimizes the PLOT score in `loop/quality_eval.md`.** Its primary fuel is
the **last run's eval deficiencies** (P1–P6), which are injected automatically each
iteration. This file is for *extra* curated priorities — but ONLY list things that
will actually **raise the plot score**.

Do NOT list code-quality / refactor items here (JSON-parsing robustness, naming,
perf, dead code). They don't change the plot eval, so the loop would apply them,
see no score change, and stall. Such items belong in normal dev, not this loop.

## Priority this run: the recurring plot deficiencies
From the 57.8 baseline, the biggest, most repeated gaps (fix the harness PROMPTS /
generation logic in `harness/` — never the schema, validators, or eval):
- **P3 (opening)**: prologue dumps identity/前史 via 旁白 instead of dramatizing it
  through on-screen action + dialogue. (most-cited)
- **P1 (node turns)**: nodes (esp. the prologue's back half) go flat — no value
  flip / no gap — reading as setup/exposition rather than a scene that turns.
- **P5 (game mechanics)**: choices drift into "dominated" (one确定收益 vs one模糊),
  or values not同级 → make both options competing goods with symmetric concreteness.
- **P4 (endings)**: the two endings share emotional polarity → sharpen the swing so
  they're genuinely distinct payoffs.
- **P6 (craft)**: 旁白 carries plot/setting; dialogue lacks subtext.

Pick the ONE change per iteration most likely to lift the mean without regressing
any genre. The generation guidance is editable — improve the prose/skeleton
**instructions** in `harness/CREATIVE_WRITING_PROSE.md` / `CREATIVE_WRITING_SKELETON.md`,
or the **prompt builders** in `harness/llm.py` / `harness/metadata_fill.py`. (The
judge, validators, schemas, CHOICE_DESIGN/DRAMATIC_STRUCTURE/VALIDATION are PROTECTED
— you cannot cheat by editing the grading; you can only make the output better.)
