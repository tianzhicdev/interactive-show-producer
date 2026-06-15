"""StoryPlan IR — the typed intermediate representation for harness v2.

The plan is data; prose is rendering. Every pass of the pipeline reads and
writes THIS structure. Three computations over it are deterministic and free:
  - knowledge propagation (who knows what, per node, meet-over-paths)
  - pacing curve validation (tension/charge over every root→ending path)
  - ledger closure (questions answered, setups paid, ironies recognized)

This module is self-contained (no LLM imports) and JSON round-trippable.
Adopted incrementally per HARNESS_V2_IMPLEMENTATION_PLAN M2; the existing
models.Node maps onto PlanNode (skeleton→beats, choices→dilemma.options).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import VARIES, Effect, NodeId

Charge = Literal["+", "-"]
ArcSlot = Literal[
    "hook", "lock_in", "first_attempt", "midpoint", "complication",
    "main_culmination", "crisis", "climax", "resolution",
]
BeatRole = Literal[
    "buildup", "payoff", "surprise", "decision_trigger",
    "recap", "preparation", "aftermath", "",
]


# ---------- Beats ----------

@dataclass
class Beat:
    """Smallest plot unit. Stable ID survives reordering (produces.beat refs)."""
    id: str                      # "t2.b3"
    type: str                    # scene_header|action|dialogue|narration|namecard
    text: str                    # one-line plot statement (skeleton granularity)
    role: BeatRole = ""          # dramatic function inside the node template
    speaker: str = ""            # [dialogue] who speaks
    facts: list[str] = field(default_factory=list)       # fact ids established HERE
    uses: list[str] = field(default_factory=list)        # fact ids this beat PRESUPPOSES
    reveals_to: list[str] = field(default_factory=list)  # chars who learn facts here
    # (characters present in the scene witness by default; reveals_to extends
    #  to off-scene learning, e.g. a letter)


# ---------- Choice / Dilemma ----------

@dataclass
class DilemmaOption:
    label: str                                   # ≤8 chars, player action
    to: NodeId
    cost: str = ""                               # what is irreversibly risked/lost
    goal_impacts: dict[str, int] = field(default_factory=dict)  # {"复仇": +1, "守护家人": -1}
    state_delta: list[Effect] = field(default_factory=list)
    resolution: list[str] = field(default_factory=list)


@dataclass
class Dilemma:
    question: str                                # ≤30 chars
    dilemma_type: str = ""                       # irreconcilable_goods|lesser_of_two_evils|combined
    trigger_beat: str = ""                       # beat id that FORCES the question (must be in final 2 beats)
    options: list[DilemmaOption] = field(default_factory=list)

    def dominated_options(self) -> list[int]:
        """Option indices that are non-negative across all goals = no dilemma."""
        out = []
        for i, opt in enumerate(self.options):
            if opt.goal_impacts and all(v >= 0 for v in opt.goal_impacts.values()):
                out.append(i)
        return out


# ---------- Node ----------

@dataclass
class PlanNode:
    id: NodeId
    kind: str = "scene"                          # prologue|scene|bottleneck|ending
    sequence: str = ""                           # "A".."H"
    arc_slot: ArcSlot | None = None
    beats: list[Beat] = field(default_factory=list)
    # Scene contract (McKee): a scene must TURN or it is exposition
    value: str = ""                              # value at stake: 信任/生死/自由
    opening_charge: Charge | None = None
    closing_charge: Charge | None = None
    turning_type: str = ""                       # action|revelation
    tension: int = 0                             # 1-5 declared intensity
    expectation: str = ""                        # the Gap: what the protagonist expects
    result: str = ""                             # what actually happens (must differ)
    dilemma: Dilemma | None = None               # None for endings
    ending: str = "NONE"                         # NONE|ENDING|DEAD_END
    duration_min: float = 2.5
    cast: list[str] = field(default_factory=list)  # CLOSED roster; prose may not exceed
    location: str = ""
    time: str = ""
    entry_context: str = ""
    exit_context: str = ""
    chapters: tuple[int, int] = (0, 0)
    covers: list[str] = field(default_factory=list)  # highlight ids paid off here

    def is_nonevent(self) -> bool:
        """McKee D16: equal charges = exposition, not a scene."""
        return (self.opening_charge is not None
                and self.opening_charge == self.closing_charge)


# ---------- Sequence (Gulino trunk unit) ----------

@dataclass
class Sequence:
    id: str                                      # "A".."H"
    function: str                                # hook|lock_in|first_attempt|midpoint|...
    span_pct: tuple[float, float] = (0.0, 0.0)   # target position band
    question_id: str = ""                        # this sequence's ledger question
    bottleneck: NodeId = ""                      # the convergence node ending the sequence


# ---------- Ledger ----------

@dataclass
class LedgerEntry:
    """One trackable narrative obligation. Closure is checked at export."""
    id: str                                      # "q.main", "setup.iron_box", "irony.husband_identity"
    kind: str                                    # question|setup|dangling_cause|irony|motif
    gloss: str
    planted_at: str = ""                         # "node_id" or "node_id.beat_id"
    refs: list[str] = field(default_factory=list)    # deliberations / re-references
    closed_at: str = ""                          # answered / paid_off / recognition beat
    intentionally_open: bool = False             # sequels may leave threads
    meta: dict[str, Any] = field(default_factory=dict)
    # irony: {"revelation": beat_ref, "recognition": beat_ref}
    # question: {"answered": "well"|"badly"}


# ---------- Player-state model ----------

@dataclass
class ProtagonistGoal:
    id: str                                      # "守护家人"
    gloss: str
    weight: int = 1                              # all roughly equal for dilemma math


@dataclass
class PlayerStat:
    id: str                                      # "player.bold"
    gloss: str                                   # 勇烈倾向
    initial: int = 0
    low_threshold: int = -2
    high_threshold: int = 2
    low_effect: str = ""                         # prose/ending flavor at runtime
    high_effect: str = ""


@dataclass
class PlayerStateModel:
    goals: list[ProtagonistGoal] = field(default_factory=list)
    stats: list[PlayerStat] = field(default_factory=list)


# ---------- StoryPlan root ----------

@dataclass
class StoryPlan:
    title: str
    root: NodeId
    sequences: list[Sequence] = field(default_factory=list)
    nodes: dict[NodeId, PlanNode] = field(default_factory=dict)
    ledger: list[LedgerEntry] = field(default_factory=list)
    player: PlayerStateModel = field(default_factory=PlayerStateModel)

    # ----- graph helpers -----

    def successors(self, nid: NodeId) -> list[NodeId]:
        node = self.nodes[nid]
        if not node.dilemma:
            return []
        # Filter dangling targets: a malformed plan with an option pointing at a
        # non-existent node should surface as a violation, not a KeyError in
        # paths()/compute_knowledge().
        return [o.to for o in node.dilemma.options if o.to in self.nodes]

    def predecessors(self, nid: NodeId) -> list[NodeId]:
        return sorted({
            pid for pid, p in self.nodes.items()
            if p.dilemma and any(o.to == nid for o in p.dilemma.options)
        })

    def topo_order(self) -> list[NodeId]:
        indeg = {n: 0 for n in self.nodes}
        for nid in self.nodes:
            for s in self.successors(nid):
                if s in indeg:
                    indeg[s] += 1
        queue = sorted(n for n, d in indeg.items() if d == 0)
        order: list[NodeId] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for s in self.successors(n):
                indeg[s] -= 1
                if indeg[s] == 0:
                    queue.append(s)
            queue.sort()
        if len(order) != len(self.nodes):
            raise ValueError("StoryPlan contains a cycle")
        return order

    def paths(self, limit: int = 200) -> list[list[NodeId]]:
        """All root→terminal paths (bounded; convergent graphs stay small)."""
        out: list[list[NodeId]] = []

        def dfs(nid: NodeId, path: list[NodeId]) -> None:
            if len(out) >= limit:
                return
            path = path + [nid]
            succ = set(self.successors(nid))
            if not succ:
                out.append(path)
                return
            for s in sorted(succ):
                dfs(s, path)

        dfs(self.root, [])
        return out


# ---------- Computation 1: knowledge matrix ----------

def compute_knowledge(plan: StoryPlan) -> dict[NodeId, dict[tuple[str, str], Any]]:
    """Who knows what at ENTRY of each node: (character, fact) -> True | VARIES.

    Same meet-over-paths as guaranteed-state: a character knows a fact at a
    convergence node only if they learned it on EVERY inbound path. "audience"
    is a pseudo-character that witnesses every beat. Characters present in a
    node's cast witness facts established in its beats; reveals_to extends to
    off-scene learners.
    """
    entry: dict[NodeId, dict[tuple[str, str], Any]] = {}
    post: dict[NodeId, dict[tuple[str, str], Any]] = {}

    for nid in plan.topo_order():
        node = plan.nodes[nid]
        preds = plan.predecessors(nid)
        if not preds:
            know: dict[tuple[str, str], Any] = {}
        else:
            states = [post[p] for p in preds if p in post]
            know = dict(states[0])
            for s in states[1:]:
                merged: dict[tuple[str, str], Any] = {}
                for k in set(know) | set(s):
                    a, b = know.get(k, VARIES), s.get(k, VARIES)
                    merged[k] = a if (a is not VARIES and a == b) else VARIES
                know = merged
        entry[nid] = know

        after = dict(know)
        for beat in node.beats:
            for fact in beat.facts:
                learners = set(node.cast) | set(beat.reveals_to) | {"audience"}
                for ch in learners:
                    after[(ch, fact)] = True
        post[nid] = after
    return entry


def knowledge_violations(plan: StoryPlan) -> list[str]:
    """D25: an actor exploits a fact their branch never gave them.

    A beat that `uses` a fact requires the acting character (dialogue speaker,
    else the whole cast is assumed acting) to know it at node ENTRY — knowledge
    established earlier in the SAME node also counts (beats are ordered)."""
    entry = compute_knowledge(plan)
    problems: list[str] = []
    for nid, node in plan.nodes.items():
        know = dict(entry[nid])
        for beat in node.beats:
            actors = [beat.speaker] if beat.speaker else list(node.cast)
            for fact in beat.uses:
                for ch in actors:
                    val = know.get((ch, fact))
                    if val is not True:
                        state = "VARIES (path-dependent)" if val is VARIES else "unknown"
                        problems.append(
                            f"knowledge: {nid}.{beat.id}: '{ch}' uses fact "
                            f"'{fact}' but it is {state} on some inbound path")
            # beats are ordered: facts established here are known downstream
            for fact in beat.facts:
                learners = set(node.cast) | set(beat.reveals_to) | {"audience"}
                for ch in learners:
                    know[(ch, fact)] = True
    return problems


# ---------- Computation 2: pacing curve ----------

def pacing_violations(plan: StoryPlan, peak_gap_min: float = 5.0) -> list[str]:
    """Per-path checks: peak cadence, charge alternation, nonevents."""
    problems: list[str] = []
    for nid, node in plan.nodes.items():
        if node.ending == "NONE" and node.is_nonevent():
            problems.append(f"D16 nonevent: {nid} opening==closing charge "
                            f"({node.opening_charge})")
    for path in plan.paths():
        # Peak-cadence check only applies when tension metadata exists at all
        if not any(plan.nodes[nid].tension > 0 for nid in path):
            continue
        clock = 0.0
        last_peak = 0.0
        # (nid, charge) so the monotony report names the right node — `charges`
        # skips nodes without a closing_charge, so its index ≠ path index.
        charges: list[tuple[NodeId, str]] = []
        for nid in path:
            node = plan.nodes[nid]
            clock += node.duration_min
            if node.tension >= 4:
                last_peak = clock
            if clock - last_peak > peak_gap_min:
                problems.append(
                    f"pacing: path …{nid}: {clock - last_peak:.1f}min since last "
                    f"tension>=4 peak (max {peak_gap_min})")
                last_peak = clock  # report once per gap
            if node.closing_charge:
                charges.append((nid, node.closing_charge))
        for i in range(2, len(charges)):
            if charges[i][1] == charges[i - 1][1] == charges[i - 2][1]:
                problems.append(
                    f"pacing: path …{charges[i][0]}: 3 consecutive '{charges[i][1]}' "
                    f"closing charges (monotony)")
                break
    return problems


# ---------- Computation 3: ledger closure ----------

def ledger_violations(plan: StoryPlan) -> list[str]:
    problems = []
    for e in plan.ledger:
        if e.intentionally_open:
            continue
        if not e.closed_at:
            problems.append(f"ledger: {e.kind} '{e.id}' planted at {e.planted_at} "
                            f"never closed ({e.gloss})")
        if e.kind == "irony":
            if not e.meta.get("revelation") or not e.meta.get("recognition"):
                problems.append(f"ledger: irony '{e.id}' missing "
                                f"revelation/recognition bracket")
        # NOTE: "question answered but never deliberated" is muted until the
        # pipeline actually records deliberation refs — the middle exists in
        # the story; only the bookkeeping is missing (user-confirmed noise).
    return problems


# ---------- Dilemma gate ----------

def dilemma_violations(plan: StoryPlan) -> list[str]:
    problems = []
    goal_ids = {g.id for g in plan.player.goals}
    for nid, node in plan.nodes.items():
        d = node.dilemma
        if d is None or node.ending != "NONE":
            continue
        for i in d.dominated_options():
            problems.append(f"dilemma: {nid} option {i} '{d.options[i].label}' "
                            f"is dominated (non-negative on all goals)")
        impacts = [frozenset(o.goal_impacts.items()) for o in d.options
                   if o.goal_impacts]
        if impacts and len(set(impacts)) < len(impacts):
            problems.append(f"dilemma: {nid} options have identical goal impacts")
        if d.trigger_beat and node.beats:
            tail = [b.id for b in node.beats[-2:]]
            if d.trigger_beat not in tail:
                problems.append(
                    f"dilemma: {nid} trigger_beat '{d.trigger_beat}' is not in "
                    f"the final 2 beats — choice not at the tension peak")
        for o in d.options:
            unknown = set(o.goal_impacts) - goal_ids
            if unknown:
                problems.append(f"dilemma: {nid} references unknown goals {unknown}")
    return problems


# ---------- Bridge: models.Graph → StoryPlan ----------

def plan_from_graph(graph, bible: dict | None = None,
                    outline: dict | None = None) -> StoryPlan:
    """Convert the operational Graph into a StoryPlan so the IR validators
    (pacing/dilemma/ledger/knowledge) can run over it. Lossy where the graph
    lacks IR fields (missing fields simply disable the related checks)."""
    bible = bible or {}
    outline = outline or {}
    nodes: dict[str, PlanNode] = {}

    for nid, n in graph.nodes.items():
        beats: list[Beat] = []
        cast: list[str] = []
        for i, el in enumerate(n.skeleton or []):
            if not isinstance(el, dict):
                continue
            if el.get("type") == "scene_header":
                for c in el.get("characters", []):
                    if c and c not in cast:
                        cast.append(c)
            beats.append(Beat(
                id=el.get("id") or f"{nid}.b{i}",
                type=el.get("type", "action"),
                text=el.get("text", "") or el.get("line", ""),
                role=el.get("role", ""),
                speaker=el.get("speaker", ""),
                facts=list(el.get("facts", []) or []),
                uses=list(el.get("uses", []) or []),
                reveals_to=list(el.get("reveals_to", []) or []),
            ))
        dilemma = None
        if n.question and n.choices:
            # trigger_beat = last beat tagged decision_trigger (if the
            # skeleton carries roles); enables the choice-at-peak check
            trigger = ""
            for b in beats:
                if b.role == "decision_trigger":
                    trigger = b.id
            dilemma = Dilemma(
                question=n.question,
                trigger_beat=trigger,
                options=[DilemmaOption(
                    label=c.label, to=c.to, cost=c.cost,
                    goal_impacts=dict(c.goal_impacts),
                    state_delta=list(c.state_delta),
                    resolution=list(c.resolution),
                ) for c in n.choices],
            )
        nodes[nid] = PlanNode(
            id=nid, kind=n.kind, sequence=n.sequence,
            arc_slot=n.arc_slot or None,
            beats=beats, value=n.value,
            opening_charge=n.opening_charge or None,
            closing_charge=n.closing_charge or None,
            turning_type=n.turning_type, tension=n.tension,
            expectation=n.expectation, result=n.result,
            dilemma=dilemma, ending=n.ending,
            duration_min=n.planned_duration_min, cast=cast,
            entry_context=n.entry_context, exit_context=n.exit_context,
            chapters=n.chapters, covers=list(n.covers),
        )

    present_sequences = {p.sequence for p in nodes.values() if p.sequence}
    # Fact-based attribution (W5): if the ledger entry carries a fact_id,
    # the node producing it is the plant; a later node requiring it closes the
    # reference chain. Falls back to the coarse sequence heuristic.
    producers: dict[str, str] = {}
    consumers: dict[str, str] = {}
    for nid, n in graph.nodes.items():
        for eff in n.produces:
            producers.setdefault(eff.fact, nid)
        for req in n.requires:
            consumers.setdefault(req.fact, nid)
    ledger = []
    for e in outline.get("ledger", []) or []:
        close_seq = e.get("close_sequence", "")
        fact_id = str(e.get("fact_id", "") or "")
        planted_at = (f"node:{producers[fact_id]}"
                      if fact_id and fact_id in producers
                      else f"seq:{e.get('plant_sequence', '')}")
        if fact_id and fact_id in producers and fact_id in consumers:
            closed_at = f"node:{consumers[fact_id]}"
        elif close_seq in present_sequences:
            closed_at = f"seq:{close_seq}"
        else:
            closed_at = ""
        ledger.append(LedgerEntry(
            id=str(e.get("id", "")), kind=str(e.get("kind", "")),
            gloss=str(e.get("gloss", "")),
            planted_at=planted_at,
            closed_at=closed_at,
            meta={"revelation": "planned", "recognition": "planned"}
                 if e.get("kind") == "irony" else {},
        ))

    return StoryPlan(
        title=str(bible.get("title", "") or "(untitled)"),
        root=graph.root,
        sequences=[Sequence(
            id=str(s.get("id", "")), function=str(s.get("function", "")),
            span_pct=tuple(s.get("span_pct", (0.0, 0.0))[:2]) if s.get("span_pct") else (0.0, 0.0),
            question_id=str(s.get("dramatic_question", ""))[:40],
        ) for s in outline.get("sequences", []) or []],
        nodes=nodes,
        ledger=ledger,
        player=PlayerStateModel(
            goals=[ProtagonistGoal(id=str(g.get("id", "")), gloss=str(g.get("gloss", "")))
                   for g in bible.get("protagonist_goals", []) or [] if g.get("id")],
            stats=[PlayerStat(id=str(s.get("id", "")), gloss=str(s.get("gloss", "")),
                              low_effect=str(s.get("low_effect", "")),
                              high_effect=str(s.get("high_effect", "")))
                   for s in outline.get("player_stats", []) or [] if s.get("id")],
        ),
    )


def drama_report(plan: StoryPlan) -> dict:
    """All IR validator outputs in one dict (P6 lint, report-card section)."""
    return {
        "pacing": pacing_violations(plan),
        "dilemma": dilemma_violations(plan),
        "ledger": ledger_violations(plan),
        "knowledge": knowledge_violations(plan),
    }


# ---------- JSON round-trip ----------

def plan_to_dict(plan: StoryPlan) -> dict:
    import dataclasses
    return dataclasses.asdict(plan)


def plan_from_dict(d: dict) -> StoryPlan:
    def _beats(arr):
        return [Beat(**b) for b in arr]

    def _node(nd: dict) -> PlanNode:
        nd = dict(nd)
        nd["beats"] = _beats(nd.get("beats", []))
        nd["chapters"] = tuple(nd.get("chapters", (0, 0)))
        dl = nd.get("dilemma")
        if dl:
            opts = [DilemmaOption(
                label=o["label"], to=o["to"], cost=o.get("cost", ""),
                goal_impacts=o.get("goal_impacts", {}),
                state_delta=[Effect(**e) for e in o.get("state_delta", [])],
                resolution=o.get("resolution", []),
            ) for o in dl.get("options", [])]
            nd["dilemma"] = Dilemma(
                question=dl["question"], dilemma_type=dl.get("dilemma_type", ""),
                trigger_beat=dl.get("trigger_beat", ""), options=opts)
        return PlanNode(**nd)

    return StoryPlan(
        title=d["title"], root=d["root"],
        sequences=[Sequence(**{**s, "span_pct": tuple(s.get("span_pct", (0, 0)))})
                   for s in d.get("sequences", [])],
        nodes={k: _node(v) for k, v in d.get("nodes", {}).items()},
        ledger=[LedgerEntry(**e) for e in d.get("ledger", [])],
        player=PlayerStateModel(
            goals=[ProtagonistGoal(**g) for g in d.get("player", {}).get("goals", [])],
            stats=[PlayerStat(**s) for s in d.get("player", {}).get("stats", [])],
        ),
    )
