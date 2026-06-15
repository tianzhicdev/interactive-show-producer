# Interactive-Play Harness — Implementation Spec

A deterministic Python **harness** (control plane) that drives **soft LLM workers**
and refuses to trust them. The harness owns structure, budget, and validation; the
LLM only generates and judges meaning. Two instruction files —
`CREATIVE_WRITING.md` and `VALIDATION.md` — are loaded at runtime so they can be
iterated without changing this algorithm.

---

## 0. The two kinds of function

| Kind | Trust | Functions |
|---|---|---|
| **Soft (LLM worker)** | distrusted; output always validated | `get_story_bible`, `get_indexes`, `get_highlights`, `get_cornerstone_nodes`, `creative_writing`, `creative_writing_fix`, `validate_semantic` |
| **Hard (pure code)** | authoritative | `seed_registry`, `compute_guaranteed`, `rank_edges`, `shortest_playthrough`, `estimate_minutes`, `choose_expansion_type`, `build_goal`, `register_facts`, `merge`, `validate_deterministic`, `checkpoint`, `write` |

The whole point of the harness: a bare skill skips validation because nothing forces
it to stop. Here, `merge` and `validate_deterministic` are gates the LLM cannot bypass.

---

## 1. Data structures

### 1.1 State — a flat map, fully initialized at the root

State is a single dict, **initialized for every registered fact at the start node**
from the registry's initial values. No fact is ever "absent" — it's always set to
*some* value. This is what keeps the model a simple map and keeps the meet operation
clean.

```python
Value = bool | int | str          # bool for ~everything; int/enum-string when needed
FactId = str                       # layer encoded in the key prefix (see below)
State  = dict[FactId, Value]
```

**Layer is encoded in the key prefix** — this is how the three-layer knowledge split
(world-true / character-knows / player-shown) stays inside one flat map:

| Prefix | Meaning | Typical use |
|---|---|---|
| `player.*` | the **player** has been shown this | confusion detection runs here |
| `char.<name>.*` | a **character** knows this | "how did she know that?" |
| `world.*` | objectively true in the world | twists: true early, revealed late |

Example: `player.has_key`, `player.compartment_discovered`, `char.detective.knows_culprit`,
`world.baron_is_culprit`.

### 1.2 Registry — closed, de-duplicated fact namespace

```python
@dataclass
class FactDecl:
    id: FactId
    kind: str          # "presence"|"possession"|"knowledge"|"event"|"disposition"|"location"|"relation"
    gloss: str         # NL description — for the semantic validator & dedup ONLY
    initial: Value     # value at the root (player.* facts default False = "not yet shown")
    invariant: bool    # if True, may NEVER be flipped by any expansion

Registry = dict[FactId, FactDecl]
```

No node may reference a `FactId` not in the registry. The registry is **seeded** from
the bible and **grows only through `register_facts`** (§3.7).

### 1.3 Effect — what a node does to state

```python
@dataclass
class Effect:
    fact: FactId
    value: Value       # the value the fact takes after this node
```

`reveal(F)` is just `Effect("player.F_...", True)`; `charLearn` writes a `char.*` key;
a world-truth change writes a `world.*` key. One mechanism, layer chosen by key prefix.

### 1.4 Requirement — what a node (or a choice label) presupposes

```python
@dataclass
class Requirement:
    fact: FactId
    value: Value = True   # the value the fact must already hold
```

A requirement is a *back-reference*: it fires only when content treats a fact as
already shared (definite article on a specific thing, "again", "as promised", "the same…").
**First mention asserts and requires nothing.** See `CREATIVE_WRITING.md`.

### 1.5 Choice, Node, Graph

```python
@dataclass
class Choice:
    label: str                 # < 8 Chinese chars, shown to player at decision time
    label_requires: list[Requirement]   # presuppositions of the LABEL, checked at the CHOOSING state
    to: NodeId                 # destination node — this is the edge

EndingType = Literal["NONE", "ENDING", "DEAD_END"]

@dataclass
class Node:
    id: NodeId
    content: str               # prose; written in the FINAL pass, empty during structure loop
    chapters: tuple[int, int]  # [X, Y] source-chapter span this node draws from
    covers: list[HighlightId]  # which raw-novel highlights this node represents
    produces: list[Effect]
    requires: list[Requirement]        # presuppositions of the node BODY
    entry_invariants: list[Requirement]# must hold on EVERY path arriving here (e.g. compartment not yet found)
    ending: EndingType
    question: str | None       # prompt before choices; None iff ending != "NONE"
    choices: list[Choice]      # empty iff ending != "NONE"; else >= 2 (product constraint)
    # computed, not authored:
    guaranteed: State | None = None    # filled by compute_guaranteed

@dataclass
class Graph:
    root: NodeId
    nodes: dict[NodeId, Node]
    # edges are derived: for each node, each choice.to
```

**Edges are choices.** A non-terminal node always asks a question and offers ≥ 2
genuine choices (the product is game-like, not a steerable movie — so single-exit
nodes are disallowed *by schema*, and "every choice is materially different" becomes a
hard semantic check, not an escape hatch).

### 1.6 Highlight, Goal, params

```python
@dataclass
class Highlight:
    id: HighlightId
    chapter: int
    weight: float          # how important this beat is in the source
    gloss: str

@dataclass
class Goal:                # passed INTO creative_writing; the frozen contract of a pocket
    entryA_state: State    # guaranteed state arriving at A — interior may not demand more than this
    exitB_contract: list[Requirement]  # what downstream-of-B already expects B to supply
    invariants: list[FactId]           # facts that must not flip anywhere in the pocket

@dataclass
class Params:
    target_playthrough_min: float = 55   # any root->ENDING path should be ~this
    total_budget_min: float = 100        # total node-minutes across the whole graph
    words_per_min: float = 300           # for estimate_minutes
    max_fix_attempts: int = 4
    max_llm_calls: int = ...             # global safety budget (authoring compute)
```

> **Two budgets, never conflated.** `target_playthrough_min` (55) bounds each
> root→ending *path*. `total_budget_min` (100) bounds *total* node-minutes.
> Which one is short decides *how* to expand (§3.5).

---

## 2. The core deterministic computation: `compute_guaranteed`

The one algorithm everything rests on. For each node, the **state guaranteed on every
path that reaches it** — computed in one topological pass, no path enumeration.

**Lattice per fact:** a node's incoming state maps each fact to either a concrete
value, or `VARIES` (paths disagree). Meet rule over incoming edges:

```
apply(state, node)      = state with node.produces applied (later writes win)
meet(s1, s2)[f]         = s1[f]            if s1[f] == s2[f]
                        = VARIES           if s1[f] != s2[f]
guaranteed(root)        = registry initial values
guaranteed(N)           = meet over all predecessors P of  apply(guaranteed(P), P)
```

Because state is fully initialized at the root, every fact is always present; the only
question is concrete-value vs `VARIES`. `O(nodes × facts)`, one pass in topological order.

**All deterministic checks reduce to queries against `guaranteed`:**

- `requires(fact=v)` passes ⟺ `guaranteed(N)[fact] == v` (a `VARIES` fact fails — it's
  ill-posed and signals a missing bottleneck).
- `entry_invariant(fact=v)` ⟺ same query, used for "must NOT already be true here"
  (e.g. `player.compartment_discovered == False`, blocking double-reveal).
- `choice.label_requires` is checked against the **choosing state** =
  `apply(guaranteed(A), A)` — i.e. what the player knows *when picking*, before
  entering the destination. This catches a label leaking its destination's content
  (`"打开暗格"` on A when the compartment is only revealed in B).

---

## 3. Helper functions

### 3.1 `get_story_bible(raw_novel, instruction) -> Bible`  *(soft)*
Reads the novel + brief; emits world/characters/setting, the default-license set
(what readers supply for free from genre/era/locale), and the **seed fact list**
(every fact the cornerstone graph will need, with kind/gloss/initial/invariant).

### 3.2 `get_indexes(raw_novel, instruction) -> dict[int, str]`  *(soft+code)*
Chapter-number → raw chapter text. Used to give `creative_writing` the source
material for a pocket's chapter span.

### 3.3 `get_highlights(raw_novel, instruction) -> list[Highlight]`  *(soft)*
The weighted list of major events/beats worth preserving. Computed **once** up front.
A highlight is "placed" when some node lists it in `covers`.

### 3.4 `seed_registry(bible) -> Registry`  *(hard)*
Loads the bible's seed fact list into `FactId -> FactDecl`. Initial values set here
(`player.*` default `False`).

### 3.5 `get_cornerstone_nodes(bible, registry) -> Graph`  *(soft)*
The locked skeleton: spine + bottlenecks + endings as cornerstone nodes, structure
only (no prose). **Itself an LLM output → validated in a loop before the main loop
(§4).**

### 3.6 `estimate_minutes(node) -> float` / `shortest_playthrough(graph) -> float`  *(hard)*
`estimate_minutes = wordcount(node.content_or_beat) / words_per_min` (word-count proxy
is fine — only needs to be monotone). `shortest_playthrough` = min node-minute sum over
all **root → ENDING** paths (DEAD_END paths excluded; they're allowed to be short).

### 3.7 `register_facts(registry, subgraph) -> OK | Reject(reason)`  *(hard)*
Gate run inside `merge`. For every `FactId` the subgraph mentions
(`produces`/`requires`/`entry_invariants`/`label_requires`): if already registered, OK;
if new, register it from the subgraph's declared decl; if it looks like a **rename of an
existing fact** (gloss collision) or can't be cleanly declared → **reject** back to the
fix loop. This keeps the namespace closed and de-duplicated so `requires ⊆ guaranteed`
is a real check, not string-matching with unknown holes.

### 3.8 `rank_edges(graph, highlights, params) -> list[Choice-edge]`  *(hard)*
Recomputed every iteration (insertion changes which path is shortest). Weight =

- **length deficit:** `+w_len` if the edge lies on a current shortest root→ending path
  **and** `shortest_playthrough < target_playthrough_min`;
- **unplaced-highlight density:** `+ Σ weight(h)` for highlights `h` whose `chapter`
  falls in `[startChap(A), endChap(B)]` and that are **not yet covered** by any node;

plus a deterministic tie-break (e.g. node-id order) so "the highest one" is stable.

### 3.9 `choose_expansion_type(graph, edge, params) -> "LENGTH_EXTENDING" | "BRANCH_ADDING"`  *(hard)*
- If `shortest_playthrough < target_playthrough_min` **and** edge is on a shortest path
  → `LENGTH_EXTENDING` allowed (the direct A→B is **replaced**; all crossing paths get longer).
- Else → `BRANCH_ADDING` only (**keep** A→B as one option; add parallel A→…→B routes —
  adds branching + total-minutes without lengthening the shortest path).

### 3.10 `build_goal(graph, A, B, registry) -> Goal`  *(hard)*
Freezes the **outer seams of the editable region {A, interior, B}**:
`entryA_state = guaranteed(A)` (interior may not demand more than upstream supplies),
`exitB_contract` = the requirements every node downstream of B places on B's output,
and the list of `invariant` facts that may not flip in the pocket. Passed into
`creative_writing` as a hard constraint.

### 3.11 `creative_writing(A, B, bible, chapter_span, chapters_index, unplaced_highlights, goal, etype) -> Subgraph`  *(soft)*
Generates the interior subgraph (and updated A/B) per `CREATIVE_WRITING.md`. Emits
**structure first** (beats, `produces`, `requires`, choices, `covers`, chapter refs);
prose is written in the final pass (§4) — except prose, when written, must stay faithful
to its own declared facts (checked by `validate_semantic`).

### 3.12 `creative_writing_fix(..., subgraph, feedback) -> Subgraph`  *(soft)*
Same contract, plus the previous subgraph and the validator's feedback; returns a revision.

### 3.13 `merge(graph, subgraph, A, B, registry) -> Graph | Reject(reason)`  *(hard — the most dangerous function)*
Not plumbing — a **validating** operation:
1. `register_facts` (§3.7); reject on failure.
2. Splice interior between A and B; **re-point A's choices** to the new entry node(s)
   (and re-point B's incoming as needed). For `LENGTH_EXTENDING`, drop direct A→B; for
   `BRANCH_ADDING`, keep it.
3. **Reject if not a DAG** (any back-edge from the subgraph).
4. Recompute `guaranteed` forward over the region dominated by A. **Escalate to a full
   recompute** if any interior `requires` is not satisfiable within the pocket (i.e. needs
   an establishing beat *upstream of A*) — that ripple is not pocket-bounded.
5. **Seam check:** `entryA_state` unchanged as demand floor; `exitB_contract` still
   satisfied by B's output.
6. **Reconvergence check** at every internal join and at B: branches merging must not
   leave a required fact `VARIES`.

Returns the candidate graph or a reject reason (fed to the fix loop).

### 3.14 `validate(graph, region) -> Feedback`  *(hard orchestration; semantic part soft)*
Runs `validate_deterministic` **first** (authoritative). Only if it passes, runs
`validate_semantic` (advisory). Returns combined feedback; empty ⇒ accept.

#### `validate_deterministic(graph, region) -> list[Violation]`  *(hard)*
- **D1** node `requires ⊆ guaranteed` (by value).
- **D2** every `choice.label_requires` holds at the **choosing state** `apply(guaranteed(A),A)`.
- **D3** every `entry_invariant` holds.
- **D4** no required fact is `VARIES`.
- **D5** registry closure — no unregistered `FactId` anywhere.
- **D6** graph is acyclic.
- **D7** no `invariant` fact is ever flipped by any `produces`.
- **D8** reconvergence — joins don't silently drop state to `VARIES` where required.
- **D9** schema — every non-ending node has a `question` + ≥ 2 choices; endings have neither.
- **D10** reachability — every node reachable from root; every non-DEAD_END path reaches an ENDING.

#### `validate_semantic(graph, region) -> list[Violation]`  *(soft — uses `VALIDATION.md`)*
Choice materiality, cold-introduction grace, prose-faithful-to-declared-facts, label
legibility, voice. Advisory; never overrides a deterministic pass/fail.

### 3.15 `checkpoint(graph)` / `write(graph, prose: bool)`  *(hard)*
`checkpoint` = per-iteration crash-recovery dump (cache LLM outputs keyed by input so a
resume doesn't diverge). `write(prose=True)` = final emit after the loop.

---

## 4. Main algorithm

```python
def build(raw_novel, instruction, params: Params) -> Graph:
    bible      = get_story_bible(raw_novel, instruction)
    chapters   = get_indexes(raw_novel, instruction)
    highlights = get_highlights(raw_novel, instruction)
    registry   = seed_registry(bible)

    graph = get_cornerstone_nodes(bible, registry)
    graph = stabilize(graph, registry, region=ALL, params)   # cornerstone validation loop
    compute_guaranteed(graph)

    # --- expansion loop: bounded by TOTAL node-minutes (100) ---
    while total_minutes(graph) < params.total_budget_min and llm_calls_left(params):
        edges = rank_edges(graph, highlights, params)        # recomputed each pass
        progressed = False
        for edge in edges:                                   # highest weight first
            etype = choose_expansion_type(graph, edge, params)
            if expand_edge(graph, edge, etype, bible, chapters,
                           highlights, registry, params):
                checkpoint(graph)
                progressed = True
                break
        if not progressed:                                   # nothing expandable -> done
            break

    write_prose_per_pocket(graph, bible)                     # structure was locked; now prose
    graph = stabilize(graph, registry, region=ALL, params)   # final faithfulness pass
    write(graph, prose=True)
    return graph


def expand_edge(graph, edge, etype, bible, chapters, highlights, registry, params) -> bool:
    A, B = edge.from_node, edge.to
    span = (graph.nodes[A].chapters[0], graph.nodes[B].chapters[1])
    goal = build_goal(graph, A, B, registry)
    unplaced = [h for h in highlights if in_span(h, span) and not covered(graph, h)]

    subgraph = creative_writing(A, B, bible, span, chapters, unplaced, goal, etype)
    for _ in range(params.max_fix_attempts):
        if not llm_calls_left(params):
            return False
        candidate = merge(graph, subgraph, A, B, registry)
        if is_reject(candidate):
            feedback = candidate.reason
        else:
            feedback = validate(candidate, region=pocket(A, B))
            if feedback.empty():
                graph.adopt(candidate)                       # commit
                return True
        subgraph = creative_writing_fix(A, B, bible, span, chapters,
                                        unplaced, goal, etype, subgraph, feedback)

    mark_non_expandable(edge)        # give up on THIS edge; never starve the run
    return False


def stabilize(graph, registry, region, params) -> Graph:
    """Validate-and-fix loop for an LLM-produced graph (cornerstone or final prose)."""
    for _ in range(params.max_fix_attempts):
        compute_guaranteed(graph)
        fb = validate(graph, region)
        if fb.empty():
            return graph
        graph = creative_writing_fix_whole(graph, registry, fb)
    raise HarnessError("could not stabilize", region)
```

**Termination:** success when `total_minutes ≥ total_budget_min` **or** no edge is
expandable; safety stop on `max_llm_calls`. Per-edge giving-up (`mark_non_expandable`)
ensures one stubborn pocket can't consume the whole budget.

---

## 5. Open / accepted limitations (v1)

- **Greedy, no global backtracking** beyond per-edge abandon. Acceptable for v1.
- `estimate_minutes` is a word-count proxy — fine, must only be monotone.
- The deterministic layer certifies **not-confusing** (load-bearing facts established on
  every path). Whether a cold surprise reads as *graceful* is left to `validate_semantic`.
  Don't try to make the state model judge feeling.
