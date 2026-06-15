# Playwriting Upgrade Plan

Goal: **produce high-quality interactive play scripts automatically** — ~60 min core / ~90 min with forks, a dramatic peak every 3–5 minutes, choices that are real dilemmas, and climaxes that are *played, not narrated*.

This plan folds the two existing design docs (`SKELETON_UNIFICATION.md`, `DRAMA_RESTORATION_PLAN.md`) into a single architecture, grounded in dramatic-craft and interactive-narrative research. It targets the **`harness/`** codebase (the live one — every core file was modified 2026-06-10; `skills/interactive-play-writer/lib/` is a stale Jun-4 parallel that should be retired, see §1).

---

## 0. The unifying diagnosis

The two docs describe **one root cause with six symptoms**. The root cause:

> **A node's representation is denormalized and *dramatically untyped*.** The harness stores *what happens* (`summary` free-text vs `content`/skeleton beats — two sources that drift) but never stores *why it lands as drama* (which value turns, which 爽点 fires, what the tension level is, whether it must be dramatized). With no typed dramatic structure, the validators can only check plot *coherence*, never dramatic *quality* — so the pipeline reliably produces coherent-but-flat scripts.

Every symptom in the two docs is a face of this:

| Doc | Symptom | What's missing |
|---|---|---|
| SKELETON | summary↔content drift, ungrounded back-references (eavesdropping bug) | single grounded source of truth per node |
| DRAMA #1 | no main line, first fork never converges | structural invariant on DAG shape (branch-and-bottleneck) |
| DRAMA #3 | bottleneck nodes dump whole arcs as narration | per-node beat/location cap + "dramatize, don't narrate" gate |
| DRAMA #4 | no 爽点 typing — payoffs get narrated past | typed payoff beats with setup→payoff grounding |
| DRAMA #5 | choices are investigation menus, not dilemmas | typed dilemma model + choice-quality validator |
| DRAMA #6 | summary-compression hides player actions | beat-level grounding (same as SKELETON root cause) |

**The research says the same thing in craft vocabulary.** The atomic test of a legitimate dramatic unit is the **value-charge turn** (Robert McKee, *Story*): a scene is valid only if a tracked value flips polarity (hope→despair, safe→exposed) via action or revelation; a scene that turns nothing is a "non-event" to be cut. The atomic unit of a *meaningful choice* is the **dilemma** (Dwight Swain's scene/sequel): a forced choice between two options that *each carry a real cost*. And the specific guardrail against DRAMA #3/#6 is **dramatize-don't-narrate**: turning points and climaxes *must* be played out as scenes; compressing them into summary "converts the story's most important value-turn into reported information, killing impact."

So the fix is not six separate patches. It is: **make the node representation single-sourced AND dramatically typed, then add validators that enforce dramatic legitimacy the same way the harness already enforces state coherence.**

---

## 1. Codebase decision (do this first)

There are two implementations of the same product:

- **`harness/`** — Python CLI pipeline, GLM-5.1 via Fireworks, the skeleton-first architecture documented in MEMORY.md. **Live** (modified 2026-06-10). `SKELETON_UNIFICATION.md` targets its files.
- **`skills/interactive-play-writer/lib/`** — Claude-orchestrated state-machine version with its own `data_model.py`, `dfs_expander.py`, `llm_judge.py` (15-question semantic judge), `validate_spine.py`. **Stale** (Jun-4), superseded.

**Recommendation: consolidate on `harness/`. Retire the skills duplicate** — but first **harvest its one genuinely better asset: the `llm_judge.py` 15-question structured semantic judge.** The harness's Phase 4.5 semantic validation (S1–S5) is thinner. Port the judge's question bank into the harness as the backbone of the new drama-quality validator (§7). Everything else in the skills lib is redundant with harness equivalents.

This decision matters because the rest of this plan edits harness files; doing it across two codebases doubles the cost for zero benefit.

---

## 2. Target architecture: the **Dramatic Beat**

Fold `SKELETON_UNIFICATION.md` in as the *substrate*, then add the drama layer on top.

### 2a. Substrate — unified grounded skeleton (from SKELETON_UNIFICATION)

Adopt the unification exactly as that doc specifies, with its recommended resolutions to the open questions:

- Merge `summary` + `content` into a single canonical **`skeleton`** beat list. Prose (Phase 4) becomes pure aesthetic expansion — *no new plot, characters, or facts beyond skeleton beats*.
- Beats carry **stable string IDs** (`b1`, `b2`, …), not array indices, so `produces[].beat` references survive reordering during fix loops (open question #2 → stable IDs).
- Keep `summary` as a *stored* field but add a deterministic consistency check: it may not reference named entities/events absent from skeleton beats (open question #1 → keep stored + validate). This is the check that catches the eavesdropping bug.
- `reader_has_seen` carries beat texts + produces, not just summaries — so the validator can confirm a back-reference is grounded in an ancestor beat (binary check, no guessing).

This kills the SKELETON drift problem and DRAMA #6 at the schema level.

### 2b. Drama layer — typed beat fields

Extend `ContentElement` (`harness/models.py`) so each beat can carry dramatic metadata. Most fields are optional; the validator enforces presence where it matters.

```python
@dataclass
class Beat:                       # extends today's ContentElement
    id: str                       # stable "b1".. (from §2a)
    type: str                     # scene_header|action|dialogue|narration|namecard
    # ... existing text/speaker/line/shot/emotion ...
    facts: list[str] = []         # produces/requires grounding (from SKELETON)

    # --- new drama typing ---
    value_charge: ValueTurn | None = None   # see below; set on the beat that turns the scene
    shuang_type: str | None = None          # 打脸|扮猪吃虎|逆袭|升级|金手指|身份揭露|收获|复仇  (爽点)
    hook_type:  str | None = None           # 悬念|反转|情绪|危机|留白  (钩子), on the exit beat
    setup_ref:  str | None = None           # beat-id or node-id this beat pays off (先抑后扬)
    must_dramatize: bool = False            # payoffs/turning points → rendered in-scene, never narrated
    tension: int | None = None              # 0..100, this beat's intensity (for the curve, §6)

@dataclass
class ValueTurn:
    value: str        # the axis: 安全/暴露, 信任/背叛, 希望/绝望 ...
    charge_in: str    # "+" | "-"
    charge_out: str   # "+" | "-"   (must differ from charge_in)
    via: str          # "action" | "revelation"
```

This is the single most important change. It makes the four things the system currently can't see — *the value that turns, the gratification that fires, the hook that pulls forward, and whether the moment must be played* — first-class and machine-checkable.

### 2c. Node-level dramatic fields

On `Node` (`harness/models.py`):

```python
class Node:
    # ... existing ...
    act: int                      # which act this node belongs to (for the tension baseline, §6)
    tension_target: int           # 0..100, what the director wants this node to hit (§6)
    role: str                     # "setup" | "rising" | "payoff" | "twist" | "climax" | "valley" | "ending"
    covers_shuang: list[str]      # which mined 爽点 highlights this node delivers
```

---

## 3. Mine the drama, not just the highlights (Phase 1)

Today Phase 1 mines `Highlight{id, chapter, weight, gloss}` — weight + gloss, **no dramatic type** (DRAMA #4's root). Upgrade highlight extraction (`harness/llm.py get_highlights`) to a typed mining pass, using the 爽点/钩子 taxonomy from the research:

```python
@dataclass
class Highlight:
    id: str; chapter: int; weight: float; gloss: str
    shuang_type: str | None      # 爽点 type (taxonomy above), if it's a payoff
    hook_type: str | None        # 钩子 type, if it's a suspense/turn
    setup_gloss: str | None      # the 抑 (oppression/contempt) this 扬 pays off — 先抑后扬 pairing
    intensity: int               # 0..100, replaces bare weight; drives peak placement
    plot_mode_fit: list[str]     # 复仇|宫斗|宅斗|权谋|悬疑 — gates which nodes can use it
```

Also detect `genre` + `plot_mode` for the project (大女主/古言, 悬疑, …) into the bible. `plot_mode` *gates which 爽点 types are valid* (复仇 → 打脸/身份揭露 heavy; 悬疑 → 反转/伏笔 heavy), so the generator doesn't staple a face-slap onto a mystery.

The mined `setup_gloss` is what lets the skeleton phase place the suppression beat *before* the payoff node — the "build-up" the per-node template needs (§4).

---

## 4. The per-node dramatic template (Phases 2–3)

DRAMA_RESTORATION's "Dev's Note" proposes a fixed 4-beat template. The research validates it and sharpens it. Make non-terminal nodes follow:

1. **Build-up (蓄势 / 抑)** — stakes rise; if this node delivers a 爽点, the suppression beat lands here (or was planted upstream via `setup_ref`).
2. **Gratification (爽点 / 扬)** — the payoff the player actively triggers. Tagged `shuang_type`, `must_dramatize=true`. **先抑后扬**: magnitude must match the registered setup's severity.
3. **Turn / surprise (反转)** — a revelation or action that flips the scene's `value_charge` and reframes the situation. This *is* McKee's turning point; it's what makes the node a "scene" and not a "non-event."
4. **Dilemma (choice)** — a genuine forced choice produced by the surprise (§5).

Guidance, not a straitjacket:
- **Prologue**: template runs `build-up → small 爽点 (黄金三章 小高潮) → hook → first dilemma`. The opening beat must be a strong hook + conflict (开局即高潮) — forbid slow expository openings.
- **DEAD_END**: truncated `build-up → catastrophe (value flips hard negative) → BE marker`.
- **Convergence/bottleneck nodes**: still follow the template, but their build-up/payoff must be **path-neutral** (only reference `guaranteed` state) — the harness already computes this; the template just has to respect it.

### 4a. Anti-narration caps (fixes DRAMA #3)

Add to deterministic validation (`harness/validation.py`):

- **Beat cap**: a non-bottleneck node may span ≤ N beats and ≤ 2 locations (a single `scene_header` change is fine; 4+ locations in one node = an arc compressed into narration → D-violation, split the node).
- **Dramatize gate**: any beat with `must_dramatize=true` (payoffs, turning points, large value-turns) must be rendered as `action`/`dialogue` with on-screen reaction — **never** as a `narration` beat. A `narration` beat tagged `must_dramatize` is a blocking violation. This is research rule **V6**, and it is the precise fix for "the player reads about the climax instead of playing through it."
- **Off-screen-reference check**: if a downstream node's `requires`/back-reference points at an event, that event must exist as a *dramatized* beat on every path that establishes it — not a narration aside. (Extends SKELETON's grounding check with a "was it *played*?" condition.)

---

## 5. Choices become dilemmas (fixes DRAMA #5)

Today `Choice{label, to, resolution, label_requires}` with a soft S1 "substantiality" check. Replace the menu model with a typed dilemma model + a hard choice-quality lint, drawn directly from Swain (dilemma = two options each with real cost) and inkle/Ingold (stances not degrees, plot-protected, values in tension).

```python
@dataclass
class Choice:
    label: str                    # ≤8 chars, player action
    to: NodeId
    stance: str                   # the value-stance: e.g. 复仇/隐忍, 揭露/掩护 — must differ across options
    cost: str                     # the sacrifice/risk THIS option incurs (non-empty, required)
    values_at_stake: list[str]    # which values this option serves vs sacrifices
    resolution: list[str]
    deferred_payoff: str | None   # node/beat where this choice visibly pays off later (anti-Telltale)
```

**Choice-quality validator** (new S-checks, runs in Phase 3.5/4.5):

| Check | Rule | Source |
|---|---|---|
| C1 | Each option has a **non-empty `cost`** — reject any choice with a strictly dominant (costless/clearly-best) option | Swain dilemma |
| C2 | Options differ in **kind not degree** (distinct `stance`), not "bold vs cautious" variants of the same action | Ingold/inkle |
| C3 | **Values in tension**: the choice trades values, it is not info-solvable (not "pursue clue vs hold back") | Short, dilemma-not-quiz |
| C4 | **Plot-protected**: neither option mutates the scene's load-bearing facts (both lead onward; only stakes/flavor differ) | inkle "multiple middles" |
| C5 | **Deferred-payoff ledger**: every choice that sets a differentiating fact must be *referenced again* downstream; a flag set but never read = a fake choice → blocking | Telltale anti-pattern |
| C6 | One of the 5 tension modes present: moral conflict / risk asymmetry / character test / NPC expectation / irreversibility | DRAMA_RESTORATION #5 |

C1–C3 alone convert "investigation menu" → dilemma. C5 is what makes the branch *felt* even after reconvergence.

---

## 6. The tension-curve director (the "peak every 3–5 min" goal)

This is the missing piece that turns "a coherent DAG" into "a paced experience." The research gives a fully mechanizable recipe (Façade's beat-vs-target-slope drama manager + Reagan's six emotional-arc shapes + Save-the-Cat timed anchors).

Add a **director** module (`harness/director.py`):

1. **Macro arc per project**: pick an arc shape with *multiple reversals* (Reagan's data: audiences prefer Man-in-a-Hole / Cinderella / double-dip over a smooth ramp). Defines `baseline_tension(act, position)`.
2. **Intra-act anchors** (Save-the-Cat, timed as % of runtime): catalyst ~10%, midpoint peak ~50%, all-is-lost ~70%, climax ~85%.
3. **Per-node target**: `tension_target(node) = baseline + intra_anchor + oscillation`, with a **mandatory local peak at every choice node** and a **non-resetting cliffhanger spike at each act boundary** (sawtooth with rising trend — the 短剧 "每集即高潮" shape, throttled to long-form).
4. **Peak-density budget** (deterministic check, the headline goal): estimate runtime per node (existing `budget.py`, 300 chars/min), then **enforce a tagged dramatic peak (爽点 or 反转, `tension ≥ threshold`) every 3–5 minutes along *every root→ending path***. Gaps > 5 min → "insert a beat/peak here" generation trigger. This is the 短剧 per-minute-density rule adapted to your format, and it's the single check that most directly delivers what VISION asks for.
5. **Generate-to-target, then score** (Façade loop, slots into existing Phase 4.5): an LLM rates each rendered node's achieved tension (Dramatis-style: escape-option scarcity / stakes / time-pressure). If achieved deviates from `tension_target` beyond tolerance, regenerate — same escalation machinery the harness already has.
6. **Over-suppression guard**: cap consecutive negative-valence (抑) nodes before a release; long 憋屈 stretches are the #1 abandonment cause in 短剧 data.

---

## 7. Structural invariant: branch-and-bottleneck (fixes DRAMA #1, #2)

The first fork splitting into two never-converging stories is the textbook **Time Cave** anti-pattern (exponential, most content unseen). The field consensus target is **Branch-and-Bottleneck** (Ashwell), which the harness's cornerstone/convergence architecture *already aims at* but does not *enforce*. Make it a blocking invariant in `validation.py`:

- **Mandatory reconvergence**: every branch must reconverge to a bottleneck within ≤ k nodes. A fork whose two sides never share a descendant before an ending = D-violation. (This directly forbids the "two unrelated stories" failure.)
- **Main trunk requirement**: the DAG must have a spine of bottleneck nodes that *all* paths traverse — the pivotal moments every player hits, where only stakes/flavor differ by prior choices. Expansion must attach branches to the trunk, not grow independent edges.
- **Node budget**: `total_nodes ≤ acts × width + endings` (e.g. 8×4 + 5 ≈ 37), vs 256 for a pure binary tree of the same depth. Keeps cost linear and forces reconvergence.
- **Fan-out only at endings**: 3–7 endings selected by stat thresholds (Sorting-Hat endgame); interior choices push consequence into **tracked state**, not new permanent branches (delayed branching — Fabulich/inkle). The harness's player-stats mechanism is exactly the right vehicle; this just mandates its use over branching.

---

## 8. The drama-quality validator (the enforcement layer)

The harness already has the right *shape* — deterministic D-checks (blocking) + semantic S-checks (loop with regen/escalation). Add a drama tier, built on the harvested `llm_judge` question bank (§1). Consolidated gate set:

| # | Rule | Tier | Blocking |
|---|---|---|---|
| **V1** | Each non-bottleneck scene turns ≥1 `value_charge` (`charge_in≠charge_out`); else = non-event → merge/cut | semantic | **yes** |
| **V6** | `must_dramatize` beats are played (action/dialogue), never `narration` | deterministic | **yes** |
| **C1–C5** | Choice-quality lint (§5) | semantic+det | **yes** |
| **P1** | Peak every 3–5 min on every path (§6.4) | deterministic | **yes** |
| **G1** | Beat/location cap per node (§4a) | deterministic | **yes** |
| **B1** | Branch reconverges ≤ k; main trunk exists (§7) | deterministic | **yes** |
| **S1** | 先抑后扬: every payoff references a setup of matching magnitude | semantic | warn→block on 3rd attempt |
| **S2** | Open-loop ledger: every planted hook/伏笔 resolved before its ending (anti-"诈骗") | semantic | warn |
| **S3** | On-the-nose detector: flag dialogue whose literal text == stated objective (no subtext) | semantic | warn |
| **S4** | Tone/genre consistency, 大女主 agency check (heroine drives payoffs, isn't merely rescued) | semantic | warn |

Reuse the existing escalation ladder (regen prose → fix summary/skeleton → fix question/choices) so this is additive, not a rewrite of the loop.

---

## 9. Phased rollout

Each phase is independently shippable and leaves the pipeline runnable.

- **Phase A — Substrate (1 unit).** Implement `SKELETON_UNIFICATION.md` as written (stable beat IDs, unified skeleton, grounded `reader_has_seen`, summary-consistency check). Retire `skills/interactive-play-writer/lib`; harvest `llm_judge` question bank. *Outcome: drift + eavesdropping bug + DRAMA #6 fixed.*
- **Phase B — Typed beats + typed mining (1 unit).** Add `value_charge`/`shuang_type`/`hook_type`/`must_dramatize`/`tension` to beats; typed `Highlight` with `setup_gloss`/`intensity`; genre+plot_mode detection. Update skeleton prompts (`CREATIVE_WRITING_SKELETON.md`) to emit them. *Outcome: the system can now see drama.*
- **Phase C — Dramatize gate + caps (0.5 unit).** V6 + beat/location caps (§4a). *Outcome: DRAMA #3 fixed — climaxes get played. Highest quality-per-effort; do early.*
- **Phase D — Dilemma model + choice lint (1 unit).** New `Choice` schema + C1–C6. *Outcome: DRAMA #5 fixed.*
- **Phase E — Branch-and-bottleneck invariant (1 unit).** B1 + main-trunk requirement + node budget in expansion. *Outcome: DRAMA #1/#2 fixed.*
- **Phase F — Tension director (1.5 units).** `director.py`, per-node targets, peak-density check P1, generate-to-target loop. *Outcome: the 3–5 min-peak goal delivered and measurable.*
- **Phase G — Drama validator consolidation (0.5 unit).** Wire V1/S1–S4 into Phase 4.5 escalation. *Outcome: quality enforced end-to-end.*

**Sequencing logic:** A unblocks everything (single source of truth). C is the cheapest big win. D and E are independent and can parallelize. F depends on B (needs `tension`/`intensity`). G is the capstone.

A lighter first cut, if you want signal fast: **A → C → D**. That alone removes the three failure modes a reader notices first (narrated climaxes, drift, fake choices) without the director's complexity.

---

## 10. Decisions for you

1. **Codebase**: confirm we consolidate on `harness/` and retire the skills duplicate (my strong recommendation; evidence in §1).
2. **Ambition vs. speed**: full A–G, or the lean A→C→D first cut to validate quality gains before building the director?
3. **Author-in-the-loop**: VISION says "continuous pipeline, no manual approval." But drama quality may benefit from a human gate after the skeleton/tension-curve phase (cheap to fix there, expensive after prose). Worth a *single* optional checkpoint?
4. **Evaluation**: to know any of this works we need a quality metric. Propose a held-out **rubric-scored eval** (an LLM-judge panel scoring sample outputs on the V/C/S rules + a human spot-check) run before/after each phase. Build it as Phase A.5?

---

## Appendix: research sources

- **Drama management / tension targeting**: Mateas & Stern, *Façade* (GDC 2003) — beat preconditions/effects + tension-slope selection. Nelson & Mateas, *Anchorhead* (AIIDE 2005) — reusable weighted path-evaluation. Riedl, IPOCL (JAIR 2010) — causal planning. O'Neill & Riedl, *Dramatis* (AAAI 2014) — computable suspense.
- **Emotional arcs**: Reagan et al., "The emotional arcs of stories," *EPJ Data Science* 2016 — six shapes, multi-reversal popularity. Save-the-Cat 15-beat sheet (timed anchors).
- **Branching structure**: Ashwell, "Standard Patterns in Choice-Based Games" (heterogenoustasks, 2015). Fabulich, "By the Numbers" (Choice of Games). Emily Short, "Beyond Branching" — storylets/QBN.
- **Choice & scene craft**: McKee, *Story* / *Dialogue* (value-charge turn, subtext, on-the-nose). Swain, *Techniques of the Selling Writer* (scene/sequel, dilemma). Truby, *Anatomy of Story* (scene-as-ministory). inkle/Ingold (stances-not-degrees, multiple middles).
- **Chinese craft**: 爽点 taxonomy (打脸/扮猪吃虎/逆袭/…) + 先抑后扬; 钩子 7-types + 黄金三章; 短剧 pacing (开局即高潮, 每分钟3–4情绪爆点); 情绪曲线 ECG model; 大女主/古言 + 悬疑 conventions. (Sources: 知乎/CSDN/中国作家网 craft guides — full URL list captured in research notes.)
