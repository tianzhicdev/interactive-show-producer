# Choice Quality Plan — Competing Goods over Approach-Avoidance

*2026-06-13. Trigger: lab_cc n1「掰腕立威 vs 吞声蛰伏」reads dominated — no player
picks 吞声蛰伏 — while run_20260613_002903 n1「搜刮地库珍宝 vs 搜寻书房密信」reads
as a real dilemma. This plan makes the harness produce the latter shape by design.*

## 1. Diagnosis (why one works and the other doesn't)

The two scenes are different **choice species** in Mawhorter's choice-poetics terms:

| | lab_cc (bad) | 002903 (good) |
|---|---|---|
| Structure | approach-avoidance: **act vs. don't-act** | competing goods: **gain A vs. gain B** |
| Option 1 | 掰腕立威 — gain 立威 + risk 暴露 | 搜刮地库 — gain 财富 |
| Option 2 | 吞声蛰伏 — **lose** 威慑 (no stated gain) | 搜寻书房 — gain 线索/真相 |
| Player read | option 2 is the "loser" → **dominated** | want both, can take one → **dilemma** |
| Label form | 吞声蛰伏 = negative attitude word | 搜刮/搜寻 = positive action verbs |
| Goal impacts | opt2 only *protects* a long-game goal players can't see | each opt clearly buys one named good, pays the other |

Mawhorter: an **"obvious" choice** has one option that achieves a goal while the
others fail goals — rational players have no reason to pick the loser. A
**"dilemma"** makes *all* options achieve something valuable while conflicting —
that is the shape we want. (Sid Meier's "interesting decision" is the same idea:
no dominant option; the interest is in the **tradeoff** between competing goods.)

Three concrete defects in lab_cc, mapping to the user's three points:

1. **No legible second good.** 吞声蛰伏's only payoff (报恩救恩人 +1 = staying
   hidden serves the long game) is invisible to the player. The question states
   opt1's risk and opt2's loss, but never opt2's *gain* → asymmetric → dominated.
2. **Negative-framed label.** 吞声蛰伏 / 藏锋 / 隐忍 are attitude words that read
   as capitulation. Even when mechanically balanced, they feel like the loser.
3. **Possibly not a choice point at all.** "Be bold or endure" on a single act is
   inherently approach-avoidance. If we can't name a *second positive good*, this
   beat should be authored narration, not a fork.

## 2. Principle

> A choice is between **two competing goods with a legible opportunity cost**, not
> between doing the bold thing and eating shit. Each option names a thing the
> player actively *wants*; picking one *forfeits* the other; the player is shown
> both pulls and both prices **before** choosing. If a beat can't be cast this
> way, it is not a choice — it is a scene.

## 3. The harness already has the rules — they under-enforce

`CHOICE_DESIGN.md` R2 (no pure-loss), R3 (benefit symmetry), R10 (safe option
dignified), R14 (verb-first concrete labels) all point here. They fail because:
- They are **generation hygiene**, checked weakly; the deeper *structural* test
  (competing-goods vs approach-avoidance) isn't expressed or validated.
- The **second good is never required to be named** — opt2 can be "the absence of
  opt1's downside," which is exactly the 吞声蛰伏 trap.
- The player **never sees** the per-option pull+price at decision time (the cost
  field is computed but not reliably surfaced in question / script / webapp).
- Every non-ending node is **forced to have a 2-way choice**, so beats that are
  really single-act tension get a manufactured (dominated) fork.

## 4. Plan

### Phase A — "Two goods" structural rule (generation) [core]
`CREATIVE_WRITING_SKELETON.md` + `CHOICE_DESIGN.md` digest:
- New mandatory pre-write table per choice: **每个选项必须命名一个玩家主动想要的
  收获 (gain)，且两个 gain 不同**; then each option's **price = the other option's
  gain forfeited** (opportunity cost), plus any extra risk.
- Ban "act vs not-act": if option 2 is the negation/absence of option 1 (忍/退/
  不做/保持原样), it is illegal — recast or demote.
- Recast recipe for approach-avoidance beats: ask "什么积极目标被'隐忍'买到了？"
  (情报? 时机? 盟友? 暴露规避?) and make THAT the named good, with a positive verb
  label (e.g. 吞声蛰伏 → 「暗记仇敌探虚实」, the good = intel/positioning).

### Phase B — Positive-label + legible-tradeoff (generation + validation)
- `VALIDATION.md` / D9: extend the bare-opt-out banlist to **negative-attitude
  labels** (吞声/蛰伏/隐忍/认命/作罢/退让…) — a label must lead with an action verb
  toward a *named object/good*.
- **Question must name both goods** (R7 upgraded): 「为A舍B，还是为B舍A？」 form,
  where A and B are both positive nouns the player wants — not "为A冒X险还是失Y".
- Render per-option **pull + price at the decision point** in the script branch
  header and the webapp choice card (benefit + cost both visible). This is what
  lets the player "fully understand pros and cons" before choosing.

### Phase C — Decision-worthiness gate (deterministic, post-P2.5) [new]
Using `goal_impacts` already on each choice:
- **Dominance check**: if one option's impacts are all ≥0 and it weakly dominates
  the other on every shared goal → flag DOMINATED → regenerate (Phase A recast) or
  demote to choiceless.
- **Second-good check**: if an option has **no positive goal_impact at all** (only
  0/negative) → it has no pull → flag → recast or demote.
- These are the operative, measurable metrics (extend the existing dominated-option
  count in the report card).

### Phase D — Allow choiceless nodes [structural, bigger] [DECISION NEEDED]
Today every non-ending node must have exactly 2 choices. Option to relax: a node
may be a pure narrative/payoff beat (no question) when no competing-goods dilemma
exists there. Choices then cluster at genuine junctures (like the vault-vs-study
fork) instead of being manufactured on every beat.
- Pro: kills the root cause of dominated forks; matches "this is not a choice point."
- Con: touches trunk shape (D13 same-target pairs), budget math, expansion, webapp
  player flow. Largest change; do last, gated on A–C landing.
- **Alternative if we keep mandatory forks**: Phase C "demote" instead routes a
  bad fork to a *re-sited* choice (move the decision to the next competing-goods
  beat), never emitting a dominated one.

### Phase E — Choice **placement** (P1 outline) [where good dilemmas live]
The 002903 dilemma was strong because the *source scene* offered two real pursuits
(treasure vs evidence). Teach P1 outline to mark **dilemma sites** — beats in the
source where the protagonist must trade one pursuit for another — and site choices
there, rather than forcing one onto whatever beat lands at the node boundary.

## 5. Sequencing & validation
1. Phase A + B together (prompt + validator), re-run `--first-episode` on all
   three models, eyeball n1 for competing-goods shape and positive labels.
2. Phase C gate, confirm dominated count → 0 on a full run.
3. Decide Phase D (choiceless) vs keep-forks+re-site; implement chosen path.
4. Phase E outline dilemma-siting; full run; compare against 002903 as the bar.

Lab loop (`--first-episode`, ~1–3 calls) makes A/B/C iteration cheap; only D/E
need full runs.

## Sources
- Mawhorter, *Choice Poetics by Example* (Arts 2018) & dissertation — obvious vs
  relaxed vs dilemma choice types; dominated options; framing/goal salience.
- Emily Short, "Choice Poetics (Peter Mawhorter)" — competing-goods vs risk-gamble.
- Sid Meier, "Interesting Decisions" (GDC 2012) — no dominant option; tradeoff is
  the interest.
