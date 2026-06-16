# Curated backlog (human-editable)

Each round the proposer surfaces a ranked **plan** of every improvement worth doing —
**any size, any category**. Its primary fuel is the last run's eval deficiencies (P1–P6,
injected automatically) plus the recent-failures feed (so it self-corrects). This file
is for *extra* curated priorities you want it to weigh.

## Categories the loop may propose
- **plot-quality** — raises the `quality_eval.md` PLOT score (the headline objective).
- **bug-fix** — real correctness bugs producing wrong/broken output.
- **speed** — faster/cheaper generation (fewer/parallel LLM calls, caching, less work).
- **refactor** — code health / maintainability, no behavior change.
- **robustness** — error handling, retries, resumability.
- **model** — a better-fitting model for a phase (which phase + which model + why).

Acceptance is category-aware: plot/bug-fix must improve-or-hold the judge mean;
engineering items (speed/refactor/robustness/model) need only NOT regress quality and
keep tests green — their benefit is confirmed at human review of `loop/auto`. The judge,
validators, schemas, and the grading .md files are PROTECTED — you can't cheat by editing
the grading; you can only make the harness genuinely better.

## Priority this run
### Plot quality (the recurring P1–P6 gaps from the ~62.8 baseline)
- **P3 (opening)**: prologue dumps identity/前史 via 旁白 instead of dramatizing it
  through on-screen action + dialogue. (most-cited)
- **P1 (node turns)**: nodes (esp. the prologue's back half) go flat — no value flip /
  no gap — reading as setup/exposition rather than a scene that turns.
- **P5 (game mechanics)**: choices drift into "dominated" (one确定收益 vs one模糊), or
  values not同级 → make both options competing goods with symmetric concreteness.
- **P4 (endings)**: the two endings share emotional polarity → sharpen the swing.
- **P6 (craft)**: 旁白 carries plot/setting; dialogue lacks subtext.

### Engineering (now in scope — propose when genuinely worth it)
- **speed**: the `--mini` bible extraction reads the WHOLE novel before building from
  ch 1–2, making every iteration slow. A scoped extraction (only the chapters used)
  would cut wall-clock with no quality change.
- **robustness**: harness_output accumulates run dirs unboundedly (3.8G+); a cleanup /
  TTL for fake + mini runs keeps the FS healthy across long loops.
- **model**: evaluate whether a cheaper/faster model fits the skeleton phase without
  lowering the judge score (deepseek vs glm vs a smaller model per phase).
