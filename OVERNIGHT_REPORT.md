# Overnight Report — 7-Pass Pipeline: Implementation, Test Runs, Findings

*Session: 2026-06-10 23:30 → 2026-06-11 morning. Everything below happened
autonomously after you went to bed; written for your morning read.*

## TL;DR

- The 7-pass pipeline is fully implemented and produced two complete
  interactive scripts from the 替嫁王妃 novel overnight. Final state (v2.1,
  `harness_output/run_20260611_033159` — report.md + web exports there, NOT
  uploaded to prod): **all 3 gates PASS, 9 nodes, 2 convergence nodes, 0 dead
  ends, 0 never-reconverging forks, 14/14 choices carry state, 0 remaining
  semantic violations** — vs the old baseline's 0 convergence / 42% dead ends.
- Every node now carries machine-checked dramatic metadata (charges, tension,
  beat roles incl. decision_trigger, goal-impact dilemma matrices), and the
  drama lint produces a concrete editorial TODO list instead of vibes.
- The validators caught and autonomously fixed the exact bug class that
  motivated this whole effort: an ending presupposing an arson the player
  never played (§4b).
- The P1 outline pass is the architectural win of the night: 6 sequences at
  correct Gulino positions, an 8-entry ledger with a textbook irony bracket,
  and 3 runtime player-stat axes — all from one scored-candidate call.
- Seven distinct bugs were found and fixed by running the pipeline for real —
  every one of them invisible to unit tests (they live in the LLM/cache/
  concurrency interaction layer). Details in §3; durable lessons saved to memory.
- The run took multiple resume cycles because each bug surfaced sequentially —
  that's the checkpoint/resume system doing its job: **no LLM work was ever
  re-paid except where prompts changed** (the disk cache replayed the rest).

## 1. What was built (the table is now real)

| Pass | Implementation | Verified by |
|---|---|---|
| P0 ingest | parallel chunk maps (4 workers), typed 爽点/hook highlights, protagonist_goals, effort=none | 80s vs ~5min sequential |
| P1 outline | k=2 candidates, deterministic score, sequences+ledger+爽点 schedule+player stats → outline.json | real outline below |
| P2 trunk | cornerstone realizes the outline (sequence/arc_slot/scene-contract/goal_impacts), same-target pair chain | clean in 1 round, D13 |
| P3 excursions | sequence obligations in prompts, commit-as-completed, merge auto-register | 2 excursions committed, real reconvergence |
| P4/P6 lint | plan_from_graph → pacing/dilemma/ledger/knowledge validators as drama lint in report.md | fired real findings |
| P5 prose | 3-worker parallel fill | 9-10 nodes in ~13 min |

Dev-velocity layer shipped alongside: `--model fake` (whole pipeline ~0.1s),
`HARNESS_LLM_CACHE` (with poisoning protection), `--until <pass>`,
`HARNESS_READ_TIMEOUT_S`, `HARNESS_STRUCTURE_EFFORT`/`HARNESS_INGEST_EFFORT`.
53 unit tests green.

## 2. The outline P1 produced (real output, zero hand-editing)

Main question: 颜如玉能否找到铁证洗清镇南王的谋反冤屈，同时护全霍家老幼活下来？
(two-horned: truth vs family — the dilemma frame is in the premise itself)

- 6 sequences, functions at correct positions (lock_in→30%, midpoint→65%,
  main_culmination 65-85% where the question IS answered, crisis_finale on new
  tension) — the Gulino rule the old pipeline couldn't express.
- Ledger: 8 entries incl. a textbook irony bracket (霍长鹤's wrong intel about
  颜如玉, revelation A → recognition D, anchored to novel beat h011), a Chekhov
  setup (suspiciously clean confiscation, A→C), dangling causes for both
  villains, the blood-letter motif A→F.
- Player stats: 狠辣/护短/智谋 with low/high effects matching the webapp's
  thresholds model.

## 3. Bugs found and fixed (the night's real value)

1. **Read timeout too small for structure calls** — trunk responses stream
   8-15 min on glm-5p1. → `HARNESS_READ_TIMEOUT_S` env (default 300 kept).
2. **Output contract too fat** — cornerstone emitted skeleton AND a mirrored
   content array → 66k chars → max_tokens truncation. → structure calls emit
   skeleton only (content mirrored locally for free). Response halved.
3. **`reasoning_effort=none` destroys field discipline** — 20× cheaper but
   produced 2 malformed giant nodes, prose in `+/-` fields, float goal_impacts.
   → ingest=none, structure=low, prose=full; schema enums on charges/
   turning_type; parser whitelists on sequence/arc_slot.
4. **Cache poisoning** — a truncated response was cached, then replayed
   identically through all 10 retries. → invalidate cache entries on schema
   failure.
5. **Cache × fix-loop echo chamber** — Phase 3.5's fix loop relies on sampling
   variation; cached identical judge+fix responses made it loop to a fatal
   crash. → all per-node validate/fix calls are now `cacheable=False`; Phase
   3.5 exhaustion is non-fatal (persists violation, continues).
6. **Validator blindness** — the S1 judge flagged legitimate same-target
   stat-write pairs as "pseudo-choices" because choice payloads omitted
   `state_delta`/`cost`/`goal_impacts`. → all 6 payload builders now include
   them + VALIDATION.md explains the stats-over-forks pattern.
7. **`copy.deepcopy` broke the VARIES sentinel** — graph snapshots created an
   impostor `object()`, silently defeating `is VARIES` checks (latent in ALL
   prior parallel expansion!). → VARIES is a copy/pickle-proof singleton.

Plus smaller ones: registry recovery on resume missed state_delta facts
(every post-resume expansion D5-rejected); fix prompts didn't know child
entry-contexts are frozen (fixes kept breaking D11 and rolling back);
final validation now self-heals prose-length violations instead of dying
at the finish line; merge auto-registers conventional-prefix facts.

## 4. Run results (v2.0 pipeline, 替嫁王妃 10 chapters, completed 03:31)

**All report-card gates PASS.** Old baseline = run_20260609 (the documented
failure case that started this whole effort).

| Metric | Old baseline | v2.0 tonight |
|---|---|---|
| nodes | 43 | 10 (30-min budget vs 100) |
| convergence nodes | **0** | **2** (t3, e1 — branch-and-bottleneck real) |
| dead-end ratio | **42%** (18/43) | **0%** |
| choices carrying state_delta | 0 | 14 of 16 |
| stat-write (same-target) pairs | 0 | 5 |
| similar-question pairs | many (investigation menus) | 0 |
| gates | D13 FAIL, D15 FAIL | **3/3 PASS** |

Playthrough 22.5–32.5 min; duration mean 3.55 min/node.

Spot-check: convergence node t3's prose opens with a genuine path-neutral
recap ("翼王庄园深处…今夜她只有一个目的：找到铁证，为镇南王翻案") — the
Gulino recapitulation device, live.

Drama lint findings on the final graph (all genuine, all actionable):
- **dilemma**: n1's '以狠立威' is a dominated option (non-negative on all four
  goals) — the Mawhorter gate working on real data; two excursion nodes used
  English goal ids ('justice', 'protection') unknown to the bible — the
  metadata-discipline gap, fixed for v2.1 via the expansion contract.
- **pacing**: 6–8.5-minute stretches without a tension≥4 peak on several
  paths — partly missing tension metadata on excursion nodes (v2.1 contract),
  partly real flatness the outline's 爽点 schedule should densify.
- **ledger**: 5 of 8 obligations flagged unclosed — mostly because sequence
  labels on mid-graph nodes were corrupt/absent (the "},{" parsing pollution),
  so closure attribution failed; enum+whitelist fixes target exactly this.

## 4b. Three-way comparison (final, 05:14)

| Metric | baseline run_0609 | v2.0 run_2326 (03:31) | v2.1 run_0332 (05:14) |
|---|---|---|---|
| gates (D13/D14/D15) | FAIL/–/FAIL | 3/3 PASS | 3/3 PASS |
| nodes | 43 | 10 | 9 |
| convergence nodes | 0 | 2 | 2 |
| dead-end ratio | 42% | 0% | 0% |
| forks never reconverging | 21 | 1 (terminal region) | **0** |
| choices with state_delta | 0 | 14/16 | **14/14** |
| stat-write pairs | 0 | 5 | 4 |
| similar-question pairs | many | 0 | 0 |
| sequence-label corruption | n/a | yes ("},{") | **none** (enums+whitelists) |
| playthrough | 7.5–29.5 min | 22.5–32.5 | 20.5–29.0 |

v2.1 additionally ran with: frozen-seam fix prompts (3.5: 10 violations → 6
fixed, 0 fatal), non-fatal 3.5 exhaustion, delta-visible judges (no stat-pair
false positives), self-heal at final validation (rebuilt n1's gutted prose).

**Final state (after P2.5 metadata resume, completed 07:44): all gates PASS,
9 nodes, 2 endings, 4.5 finished with 0 remaining violations.** Metadata
verified persisted in graph_final.json — e.g. t2: charges −→+, tension 4,
beat roles [buildup, buildup, decision_trigger, payoff], both choices carrying
proper dilemma-shaped goal_impacts (each option negative on some goal).

Two flagship moments from the final cycles, showing the system catching the
exact bug classes it was built for:
- **e2 unplayed-arson catch (S2)**: prose had 霍长鹤 open with "庄园的火，是
  你放的" — but no path ever *played* her setting the fire. The validator
  fought it through regen cycles until the presupposition was scrubbed;
  final pass: 0 remaining. This is the eavesdropping-bug class, caught and
  fixed autonomously.
- **n1 prose collapse root-caused**: repeated 92-166-char prose came from a
  GLM+strict-JSON trap — the model writes 代号"X" with unescaped ASCII
  quotes, breaks its own JSON, bails early. Fixed twice over: length floor
  enforced inside fill_prose's retry loop (with explicit length feedback),
  and a 「」-only quoting rule in the prose instructions.

Drama lint on the final graph (full metadata, all warning-level — these are
now the editorial TODO list, which is exactly the point):
- charge monotony on 2 paths (the P2.5 backfill biases −→+ everywhere — its
  prompt needs an alternation hint);
- n1's two options have identical goal impacts; evening_rest has one
  dominated option — the Mawhorter gate naming specific weak choices;
- several excursion choices use off-vocabulary goal ids (protect_family,
  escape…) — goal vocabulary needs to be passed into 4.5 fix calls too;
- 4 ledger obligations unattributed because excursion nodes lack sequence
  labels (attribution heuristic needs node→sequence inheritance from B).

## 5. Improvements implemented for the next iteration

- Beat `role` field (buildup/payoff/surprise/**decision_trigger**/recap/...)
  in schema + skeleton instructions; `ir.plan_from_graph` maps the last
  decision_trigger beat to `Dilemma.trigger_beat`, activating the
  choice-at-tension-peak check mechanically.
- Recap-opening requirement for convergence-node prose (Gulino's
  recapitulation device) in the fill_prose convergence warning.
- Expansion prompt now demands the full scene contract + choice metadata
  (was cornerstone-only — excursion nodes came back metadata-less).
- Merge-time auto-declaration of player./char./world. facts.

## 6. Open items (ranked)

1. **Metadata reliability**: even at effort=low, enum/contract compliance from
   glm-5p1 is imperfect; consider a tiny deterministic post-pass that asks a
   cheap model to fill ONLY missing scene-contract fields per node.
2. Technique slots + realized-critic (ACL'25 result) — designed, not wired.
3. Outline tie-break: both candidates scored identical 87.8; add a cheap
   judge or diversity bonus.
4. trigger_beat end-to-end verification on a fresh run (emitted → mapped →
   checked).
5. M1 module split (harness.py/llm.py are now even bigger).
6. Stat-conditioned prose variants at convergence nodes (webapp runtime).

## 7. Costs & timing observations

- glm-5p1 completion rates: outline candidates 8-14k tokens (2-4 min);
  trunk ~10k tokens at effort=low ≈ 9 min; prose ~2-4k tokens ≈ 40-90s/node.
- Parallel P0: 4 chunks in 18-80s total. Parallel prose: 9 nodes ≈ 13 min.
- Fireworks was degraded all evening (repeated 300s+ stalls on single calls);
  the read-timeout env + retry ladder absorbed it.
