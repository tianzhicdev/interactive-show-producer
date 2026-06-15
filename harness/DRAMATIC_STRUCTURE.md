# DRAMATIC_STRUCTURE — Canonical Dramaturgy Rules for Skeleton Generation & Validation

Distilled from primary sources (page numbers cite the books, not summaries):
- McKee, *Story* — scene design, dilemma, pacing, exposition (cited as M-p.N)
- Gulino, *Screenwriting: The Sequence Approach* — sequence structure, tools of the trade (G-p.N)
- Snyder, *Save the Cat* beat sheet — percentage anchors (STC)

Consumed by: Phase 2 cornerstone prompt, Phase 3 expansion prompt (structure sections),
Phase 3.5/4.5 validators (checkable rules), pacing.py (curve checks).
Severity legend: **[BLOCK]** deterministic blocking · **[WARN]** deterministic warning ·
**[JUDGE]** LLM-judge per-node · **[PROMPT]** generation instruction only.
Gulino's own caveat (G-p.21): position charts "lend a sense that the technique is more
precise than it is" — all percentage checks are tolerance bands, warnings not hard fails,
EXCEPT the inciting-incident ≤25% rule.

---

## 1. Trunk Template (60-min main path; scale linearly for other budgets)

Merged Gulino 8-sequence (2-4-2 acts, G-p.4) + Save the Cat percentages + McKee act rules.
Trunk = 7 sequences of ~8–10 min for a 60-min piece (Gulino's unit is 8–15 min, G-p.3-5;
observed real range 6–18 — use 6–18 as the [WARN] band). Each sequence ends at a
**bottleneck node** (convergence point + the sequence's dramatic question as the choice).

| Seq | Pos (min / %) | Function | Anchors |
|-----|---------------|----------|---------|
| A | 0–7 (0–11%) | Hook by **curiosity/puzzle first**, then ordinary world + bond beat ("why we care", G-p.14), flaws shown. Ends: **point of attack** — something happens TO the protagonist (STC Catalyst 11%; M-p.189: must "radically upset the balance", onscreen, never backstory M-p.198) | `inciting_incident` node ≤25% of min-path [BLOCK] (M-p.200); if later than ~15%, an opener subplot with its own II is required [WARN] (M-p.223) |
| B | 7–15 (11–25%) | Debate/come-to-terms: attempted easy solutions "lead only to a bigger problem" (G-p.17). Ends: **predicament + lock-in** — main dramatic question posed (STC Break Into Act II 23%) | `main_dramatic_question` string set here [BLOCK]; II must project the obligatory Crisis scene (M-p.198-200) — Crisis node must confront the same antagonism [JUDGE] |
| C | 15–24 (25–40%) | First, **cheapest** attempt (G-p.15: "characters choose the easiest solution first"). Fun-and-games / promise of the premise, positive trajectory (STC). B-story opens ~27% (STC) | `attempt_cost` ordinal starts low [WARN]; 短剧第一卡点 falls here (~15%): place a major 爽点/reveal near seq B/C boundary |
| D | 24–32 (40–53%) | Escalation to **midpoint culmination**: big reversal — stakes raised, threat personal/bigger, story pivots ± (STC Midpoint 50%); often "a glimpse of the actual resolution, or its mirror opposite" (G-p.18) | `first_culmination` node flagged `glimpse_of_ending: true|mirror` [WARN]; 短剧第二卡点 (~40%) — peak-craving reveal goes here |
| E | 32–40 (53–68%) | Bad-guys-close-in: trajectory reversed, complications with "stakes higher still" (G-p.18); subplot zone. Resolution must NOT answer the main question [BLOCK] | Conflict must now run on ≥2 of 3 levels {inner, personal, extra_personal} (M-p.213) [JUDGE] |
| F | 40–48 (68–80%) | **Main culmination**: the main dramatic question is ANSWERED (positively or negatively) at 65–85%, NOT at the end (G-p.13-14: observed 70/77/82%). All-Is-Lost (STC 68%) is the *common* form but Gulino shows it's optional (only 4/12 films, G-p.19) — require resolve-or-reframe, don't require despair. Break into Act III: protagonist learns something (likely from B-story) → bold decision (STC 77%) | `main_culmination` at 65–85% of runtime [WARN]; a **new third-act tension** field is mandatory after it [BLOCK]; penultimate act climax charge MUST contradict ending charge — never set up an up-ending with an up-ending (M-p.225) [BLOCK] |
| G/H | 48–60 (80–100%) | Five-point finale (STC): plan → execute → **High Tower Surprise** (twist that breaks the plan) → dig deep → new plan. Crisis = true dilemma played as a deliberately static onscreen moment (M-p.304,308). Climax: absolute irreversible max-charge value swing (M-p.309). Resolution/coda: close dangling causes, aftermath beat, final image mirrors opening image (STC 99%) | Last act SHORTEST of all (M-p.219) [WARN]; no subplot node between `crisis` and `story_climax` on any path (M-p.306) [BLOCK]; every ending node needs a resolution/aftermath beat after the climactic action — no path ends on the climax line (M-p.312; G-p.20 "catch its breath") [BLOCK] |

Act-level: ≥3 major reversals per root→ending path — two are never enough (M-p.217) [BLOCK];
>5 majors per path, or majors outnumbering moderates → impact dilution (M-p.221) [WARN].
Causal lock test: "Because of the Inciting Incident, the Climax had to happen" must read as a
logical sentence for every path (M-p.288) [JUDGE].

---

## 2. Scene Contract (every skeleton node)

The McKee five-step schema (M-p.257-259) becomes node fields:

```
scene_objective: str        # infinitive, an aspect of the protagonist's spine (M-p.233)
antagonism_desire: str      # in DIRECT conflict with objective, not tangential (M-p.258)
value: str                  # the value at stake, e.g. 信任, 生死, 自由
opening_charge: + | -
closing_charge: + | -       # MUST differ from opening (see nonevent test)
turning_point: action | revelation   # the ONLY two ways a scene turns (M-p.340)
expectation: str            # what the character expects their action to produce
result: str                 # what actually happens — must differ (the Gap, M-p.144-148)
```

- **Nonevent test** [BLOCK]: `opening_charge == closing_charge` → the scene is exposition,
  not a scene. "Cut or rewrite" (M-p.259). This is the single most checkable rule in McKee.
- **Gap test** [JUDGE]: `expectation` ≈ `result` semantically → mere activity, not action
  (M-p.152). Every node must open a gap.
- **Law of conflict** [BLOCK]: empty `antagonism_desire` = nothing moves (M-p.210).
- **Diminishing returns** [WARN]: consecutive nodes on a path with the same `closing_charge`
  sign, UNLESS turn magnitude strictly escalates (the only sanctioned exception, M-p.244-245).
- **Revelation reserve** [WARN]: at least one act-climax per path turns on `revelation`
  referencing a planted setup; flag long runs of `action`-only turns (M-p.340-341).
- **Subtext** [PROMPT]: "no text without a subtext" (M-p.256); dialogue must not state the
  speaker's deepest intent literally; indirection must be motivated in-scene (G-p.33).
- **Reversals** [JUDGE]: any `reversal` beat must cite an external `circumstance_cause` —
  never an out-of-character decision; control circumstances, not characters (G-p.166-167).
- **Coincidence asymmetry** [BLOCK after act I]: chance may hurt the protagonist, never help
  (G-p.15,37). Deterministic on a `chance_benefit` tag.

---

## 3. Choice & Dilemma Contract (every choice node)

McKee's crisis formulation IS the choice-design spec (M-p.248-251, 304):

- **No good-vs-evil / right-vs-wrong choices** — "no choice at all" (M-p.248) [JUDGE].
- **dilemma_type required** [BLOCK]: `irreconcilable_goods | lesser_of_two_evils | combined`.
- **Triangular cost** [BLOCK]: each option carries a non-empty `cost` naming what is
  irreversibly risked/lost — "A price must be paid" (M-p.250-251). Validator: the lost thing
  may not be silently restored downstream [JUDGE over branch].
- **Equal weight** [JUDGE]: options must be desires "of equal weight and value" (M-p.251) —
  with the goal-impact matrix (QUALITY_UPGRADE_PLAN Phase D1), this is arithmetic: reject
  dominated options.
- **No vacillation** [WARN]: a binary state toggling A→B→A across consecutive nodes without
  escalation is "tediously repetitious and has no ending" (M-p.249).
- **Crisis node** (final bottleneck): dilemma at maximum pressure, dramatized as a static
  deliberation moment with beats — never summarized or off-screen (M-p.308) [BLOCK: content
  length floor + position after all complications].
- **Choice prompt as telegraph** (G-p.9): each option label must imply a concrete future —
  this is why the 问题 line exists; an option that implies nothing is a blind choice [JUDGE].

---

## 4. Pacing & Rhythm

- **Risk monotonicity** [BLOCK]: per path, `risk_level`/action magnitude never decreases;
  the final action is the path maximum — points of no return, no retreat to lesser actions
  (M-p.208-209). Desire is measured by risk accepted (M-p.149-150).
- **No repetition at equal magnitude** [JUDGE]: pairwise similarity scan over node summaries
  within a path; near-duplicate action types at equal magnitude = treading water (M-p.209).
- **Tension alternation** [WARN]: cycles of tension and relief; curve must dip after act
  climaxes and each act-climax peak must top the previous (M-p.289-291). ≥3 consecutive
  sequences at identical intensity = monotony (G-p.5-6).
- **Scene length variance** [WARN]: uniform `planned_duration_min` distribution kills pace
  (M-p.291); accelerate (shorter nodes) approaching an act climax, then "earn the pause" —
  the climax node itself may be the longest (M-p.293).
- **爽点 cadence** (短剧 + L4D loop): a tension≥4 peak every ≤5 estimated minutes; every
  压抑 (suppression) beat pays off within ≤2 nodes / ≤5 min; biggest reveals near the
  ~15% and ~40% marks (the 卡点 positions). [WARN via pacing.py]
- **Comic/dramatic relief** [PROMPT]: tonal monotony tires even when every node "works"
  (G-p.36); vary tone tags across consecutive nodes.

---

## 5. Continuity Tools & Ledgers (Gulino's Tools of the Trade → DAG state)

These are the mechanisms that make a branching graph feel authored. All are **ledgers**:
plant entries during skeleton generation, validate closure deterministically.

### 5.1 Dangling-cause ledger [BLOCK at export]
`{type: intent|warning|threat|hope|fear|prediction, planted_at, paid_off_at}` (G-p.10).
Branch semantics: each branch inherits the ledger and must close its copies. By the final
sequence every entry is `paid_off` or explicitly `intentionally_open` (G-p.20). Sequence G
must consume ≥1 long-dangling cause as its twist fuel (G-p.20).

### 5.2 Setup/payoff + motif ledger [WARN]
Payoffs must reference setups strictly earlier **on every inbound path** (M-p.238-239);
orphan payoffs = blocking. Payoffs become new setups, chaining to the end (M-p.241).
Motifs need ≥2 occurrences in ≥2 contexts; plant motifs in a *revision pass after endings
exist* — "the screenplay is written backwards" (G-p.46-47).

### 5.3 Telegraph → twist contract [BLOCK]
Every node tagged `twist` must reference an earlier telegraph it subverts — "such twists
only work if the audience is made to anticipate something" (G-p.9, false telegraphing).
**Retardation** [WARN]: ≥2 nodes / ≥2 min between a telegraph and its delivery for major
reveals (G-p.27-28).

### 5.4 Dramatic irony brackets [BLOCK]
Every irony entry requires both a `revelation_scene` (audience learns; character doesn't)
and a `recognition_scene` (character catches up) (G-p.11-12). Unclosed irony at an ending
= violation.

### 5.5 Knowledge matrix [BLOCK] — *extends path-neutrality to characters*
Per node, per fact: who knows it — audience / each named character (G-p.11-12 "hierarchies
of knowledge"). The branching killer check: no scene may have a character act on knowledge
their branch never gave them. This generalizes the existing fact-intersection (VARIES)
machinery from world-state to epistemic state.

### 5.6 Recapitulation at convergence [PROMPT + WARN]
Characters "recount briefly where the story has been... trying to figure out what to do
next" (G-p.31-32). **Every convergence node opens with a recap beat** (situation + stakes +
plan, rendered in-world). This is simultaneously Gulino's orientation duty (G-p.34) and the
natural path-neutral opening for convergence nodes — it restates only guaranteed facts.

### 5.7 Preparation & aftermath [WARN]
Before each culmination node: a `preparation` beat with `expected_outcome` and
`payoff_mode: direct|contrast` — contrast-payoff before disaster is the high-impact pattern
(G-p.27,163). After high-intensity climaxes and in the final sequence: an `aftermath` beat —
a lingering image, audience catches its breath (G-p.166-168, p.20).

### 5.8 Question lifecycle [BLOCK]
Every `dramatic_question` (main, per-sequence, per-irony) maps to three references:
`posed_at`, `deliberated_at[]`, `answered_at` (G-p.12-13). Orphaned questions = violation.
Sequence questions must differ from the main question verbatim (except seq C, G-p.30);
the main tension is **immutable across branches** — branches may flip the protagonist's
objective, never the audience-level question (G-p.163: "tension is in the audience, not
the characters").

---

## 6. Exposition Rules (McKee ch.15)

- **No scene exists solely to inform** [BLOCK]: exposition only inside scenes that
  independently pass the nonevent test (M-p.334).
- **Ammunition** [JUDGE]: characters use what they know as weapons; never "as-you-know"
  mutual-knowledge recaps (M-p.335,340). Smuggle backstory inside conflict or as the answer
  to an established puzzle (G-p.25).
- **Secrets last** [WARN]: backstory facts ranked by importance; critical facts are secrets
  revealed at the latest possible moment, never in act I (M-p.336-337).
- **Desire-to-know gate** [BLOCK]: a flashback/reveal node must be preceded on every path by
  a node that raises the corresponding question (`question_raised_by` link) (M-p.337,342).
  This is the book-form of the eavesdropping-bug fix: a back-reference is only legal if the
  audience was made to want it AND an ancestor beat planted it.
- **Anti-patterns** [JUDGE]: stranger-confession scenes, servant-dusting exposition
  dialogues, plot-carrying voice-over (strip test: story still told without it? M-p.343-345).

---

## 7. Validator Spec Summary (continues QUALITY_UPGRADE_PLAN numbering)

Deterministic (validation.py / pacing.py):
- D16 nonevent: opening_charge == closing_charge → blocking
- D17 risk monotonicity per path → blocking
- D18 inciting incident ≤25% min-path → blocking; >15% without opener subplot → warn
- D19 ≥3 major reversals per path; >5 → warn
- D20 penultimate-climax charge ≠ ending charge per path → blocking
- D21 no subplot node between crisis and climax → blocking
- D22 ending nodes end with resolution/aftermath beat, not the climax line → blocking
- D23 ledger closure at export (dangling causes, irony brackets, question lifecycle) → blocking
- D24 twist-references-telegraph; retardation distance ≥2 nodes → block / warn
- D25 knowledge matrix: no character uses knowledge their branch never gave them → blocking
- D26 main culmination at 65–85% + new third-act tension present → warn / blocking
- D27 coincidence benefits protagonist after act I → blocking
- D28 scene-length variance floor; same-charge adjacency without escalation → warn
- D29 sequence length 6–18 min; ≥3 consecutive equal-intensity sequences → warn

LLM-judge (short inputs, one property per call — never holistic "is it good"):
gap test, equal-weight options, dominated options (with matrix: arithmetic), direct-conflict
desires, ammunition/as-you-know scan, technique-realized check, circumstance-caused reversals,
climax ablation ("does this scene feed its path's climax?" M-p.310 — cut orphans).

Prompt-only: subtext/indirection, mood-vs-emotion, ripeness of II, tonal variety,
curtains/act-end punctuation, "inevitable and unexpected" climax (M-p.311).
