"""§1 — Data structures for the interactive-play harness."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

# ---------- Primitives ----------

Value = bool | int | str
FactId = str
NodeId = str
HighlightId = str

class _Varies:
    """Singleton sentinel: paths disagree on a fact's value.

    Survives copy/deepcopy/pickle with identity intact — `is VARIES` checks
    must keep working on graph snapshots (deepcopy of a bare object() would
    silently create an impostor sentinel)."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "VARIES"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        return "VARIES"  # pickle resolves to this module's global


VARIES = _Varies()

# ---------- 1.2 Registry ----------

@dataclass
class FactDecl:
    id: FactId
    kind: str  # "presence"|"possession"|"knowledge"|"event"|"disposition"|"location"|"relation"
    gloss: str  # NL description — for the semantic validator & dedup
    initial: Value  # value at the root
    invariant: bool = False  # if True, may NEVER be flipped

Registry = dict[FactId, FactDecl]

# ---------- 1.1 State ----------

State = dict[FactId, Value]  # fully initialized at root; no absent keys

# ---------- 1.3 Effect ----------

@dataclass
class Effect:
    fact: FactId
    value: Value  # the value the fact takes after this node
    beat: str = ""  # stable beat ID (e.g. "b3") that establishes this fact

# ---------- 1.4 Requirement ----------

@dataclass
class Requirement:
    fact: FactId
    value: Value = True  # the value the fact must already hold

# ---------- 1.5 Choice, Node, Graph ----------

NodeKind = Literal["prologue", "scene", "bottleneck", "ending"]

@dataclass
class Choice:
    label: str  # < 8 Chinese chars
    label_requires: list[Requirement] = field(default_factory=list)
    to: NodeId = ""  # destination node
    resolution: list[str] = field(default_factory=list)  # 2 beats showing choice outcome
    # Per-choice conditional effects, applied AFTER the node's produces when this
    # choice is taken. Two choices may share the same target iff their state_delta
    # differ ("stats over forks": the choice writes state instead of forking).
    state_delta: list[Effect] = field(default_factory=list)
    # Dramatic metadata (StoryPlan IR): what this option irreversibly risks,
    # and its impact on the protagonist's standing goals. A real dilemma has
    # every option negative on SOME goal (dominated options are violations).
    cost: str = ""
    goal_impacts: dict[str, int] = field(default_factory=dict)
    # Dramatized aftermath: 3-6 content elements played at the END of the
    # choosing node after this option is selected (the ━━━ branch section).
    # The skeleton's 2-beat `resolution` is the plan; prose expands it here.
    # Path-specific consequence lives HERE so convergence targets stay neutral.
    aftermath: list[ContentElement] = field(default_factory=list)

    def delta_key(self) -> tuple:
        """Canonical comparison key for state_delta (order-insensitive)."""
        return tuple(sorted((e.fact, str(e.value)) for e in self.state_delta))

EndingType = Literal["NONE", "ENDING", "DEAD_END"]

# ---------- Content element types ----------

# Each content element is a dict with "type" key.
# Types: scene_header, action, dialogue, narration
ContentElement = dict[str, Any]


def make_scene_header(location: str, time: str, characters: list[str]) -> ContentElement:
    return {"type": "scene_header", "location": location, "time": time, "characters": characters}

def make_action(text: str, shot: str = "") -> ContentElement:
    d: ContentElement = {"type": "action", "text": text}
    if shot:
        d["shot"] = shot
    return d

def make_dialogue(speaker: str, line: str, emotion: str = "") -> ContentElement:
    d: ContentElement = {"type": "dialogue", "speaker": speaker, "line": line}
    if emotion:
        d["emotion"] = emotion
    return d

def make_narration(text: str) -> ContentElement:
    return {"type": "narration", "text": text}

def make_namecard(name: str, title: str) -> ContentElement:
    return {"type": "namecard", "name": name, "title": title}


@dataclass
class Node:
    id: NodeId
    kind: NodeKind = "scene"
    skeleton: list[ContentElement] = field(default_factory=list)
    content: list[ContentElement] = field(default_factory=list)
    planned_duration_min: float = 2.0
    chapters: tuple[int, int] = (0, 0)
    covers: list[HighlightId] = field(default_factory=list)
    produces: list[Effect] = field(default_factory=list)
    requires: list[Requirement] = field(default_factory=list)
    entry_invariants: list[Requirement] = field(default_factory=list)
    ending: EndingType = "NONE"
    question: str | None = None
    choices: list[Choice] = field(default_factory=list)
    entry_context: str = ""
    exit_context: str = ""
    guaranteed: State | None = None
    _non_expandable_edges: set[NodeId] = field(default_factory=set)

    # Dramatic metadata (StoryPlan IR; nullable for old checkpoints)
    title: str = ""              # chapter-style display title (≠ question)
    sequence: str = ""           # trunk sequence id "A".."H"
    arc_slot: str = ""           # hook|lock_in|midpoint|main_culmination|crisis|...
    tension: int = 0             # 1-5 declared intensity
    value: str = ""              # value at stake (信任/生死/自由)
    opening_charge: str = ""     # "+"|"-"
    closing_charge: str = ""     # "+"|"-" — equal charges = nonevent
    turning_type: str = ""       # action|revelation
    expectation: str = ""        # the Gap: what the protagonist expects
    result: str = ""             # what actually happens (must differ)

    scene_location: str = field(default="", repr=False)
    scene_time: str = field(default="", repr=False)
    scene_characters: list[str] = field(default_factory=list, repr=False)
    prose: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.skeleton, str):
            raw = self.skeleton
            self.skeleton = _parse_prose_to_elements(raw)
            if raw and not any(el.get("type") == "scene_header" for el in self.skeleton):
                self.skeleton.insert(0, make_scene_header(
                    self.scene_location, self.scene_time, list(self.scene_characters)
                ))
        elif self.skeleton and any(isinstance(el, str) for el in self.skeleton):
            normalized: list[ContentElement] = []
            for el in self.skeleton:
                if isinstance(el, dict):
                    normalized.append(el)
                elif isinstance(el, str) and el.strip():
                    normalized.extend(_parse_prose_to_elements(el))
            self.skeleton = normalized

        if isinstance(self.content, str):
            raw = self.content
            self.content = _parse_prose_to_elements(raw)
        elif self.content and any(isinstance(el, str) for el in self.content):
            normalized2: list[ContentElement] = []
            for el in self.content:
                if isinstance(el, dict):
                    normalized2.append(el)
                elif isinstance(el, str) and el.strip():
                    normalized2.extend(_parse_prose_to_elements(el))
            self.content = normalized2

        if self.prose and not self.content and not self.skeleton:
            self._build_content_from_legacy()
        elif not self.content and not self.skeleton and not self.prose:
            pass

        if self.skeleton and not self.content:
            # Deep-copy the element dicts: skeleton is the sole plot source and must
            # not be mutated when prose-fill / metadata edits content (or vice-versa).
            self.content = [dict(el) if isinstance(el, dict) else el for el in self.skeleton]

    def _build_content_from_legacy(self) -> None:
        elements: list[ContentElement] = []
        if self.scene_location or self.scene_time or self.scene_characters:
            elements.append(make_scene_header(
                self.scene_location, self.scene_time, list(self.scene_characters)
            ))
        elements.extend(_parse_prose_to_elements(self.prose))
        self.skeleton = elements
        self.content = list(elements)

    # --- Computed properties from content ---

    def get_first_scene_header(self) -> ContentElement | None:
        for source in (self.content, self.skeleton):
            for el in source:
                if el.get("type") == "scene_header":
                    return el
        return None

    def get_scene_location(self) -> str:
        h = self.get_first_scene_header()
        return h.get("location", "") if h else self.scene_location

    def get_scene_time(self) -> str:
        h = self.get_first_scene_header()
        return h.get("time", "") if h else self.scene_time

    def get_scene_characters(self) -> list[str]:
        h = self.get_first_scene_header()
        return h.get("characters", []) if h else self.scene_characters

    def get_prose(self) -> str:
        if self.content:
            return render_content_to_text(self.content)
        if self.skeleton:
            return render_content_to_text(self.skeleton)
        return self.prose or ""

    def get_skeleton_text(self) -> str:
        if not self.skeleton:
            return ""
        return render_content_to_text(self.skeleton)

    def get_summary(self) -> str:
        """Plot summary, ALWAYS derived from the skeleton (the sole plot source).

        There is no stored `summary` field — skeleton beats are authoritative, so
        this can never drift from the plot the prose is generated against.
        """
        parts = []
        for el in self.skeleton:
            t = el.get("type", "")
            if t in ("scene_header", "namecard"):
                continue
            text = el.get("text", "") or el.get("line", "")
            if text:
                parts.append(text)
        return "。".join(parts)

    def get_beat_by_id(self, beat_id: str) -> ContentElement | None:
        for el in self.skeleton:
            if el.get("id") == beat_id:
                return el
        return None

    def get_content_text_length(self) -> int:
        import re as _re
        text = self.get_prose()
        return len(_re.sub(r"\s+", "", text))

    def get_display_content(self) -> str:
        return self.get_prose()


def _parse_prose_to_elements(prose: str) -> list[ContentElement]:
    """Parse a flat prose string into typed content elements."""
    import re as _re
    elements: list[ContentElement] = []
    if not prose or not prose.strip():
        return elements

    for line in prose.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Scene header: 场：xxx 景：xxx
        m_scene = _re.match(r"场：\S+\s+景：(.+)", line)
        if m_scene:
            # This is a scene header inside prose (multi-scene node)
            elements.append({"type": "scene_header", "location": m_scene.group(1).strip(),
                             "time": "", "characters": []})
            continue
        m_time = _re.match(r"时：(\S+)\s+人：(.+)", line)
        if m_time:
            # Patch last scene_header if exists
            if elements and elements[-1].get("type") == "scene_header":
                elements[-1]["time"] = m_time.group(1).strip()
                elements[-1]["characters"] = [c.strip() for c in _re.split(r"[、,，]", m_time.group(2)) if c.strip()]
            continue

        # Narration: 旁白：xxx
        m_narr = _re.match(r"旁白[：:](.+)", line)
        if m_narr:
            elements.append(make_narration(m_narr.group(1).strip()))
            continue

        # Stage/camera direction: ▲xxx or AI xxx
        if line.startswith("▲"):
            body = line[1:].strip()
            shot = ""
            m_shot = _re.match(r"(特写|中景|全景|手持|俯拍|主观|跟拍)[：:]?\s*(.*)", body)
            if m_shot:
                shot = m_shot.group(1)
                body = m_shot.group(2).strip() or body
            elements.append(make_action(body, shot))
            continue
        if _re.match(r"AI\s+", line):
            elements.append(make_action(line, "AI"))
            continue

        # Dialogue: 角色名：（emotion）台词  or  角色名：台词
        m_dial = _re.match(r"([^\s：:▲场时人选\d━┌┐└┘├┤│─]{1,8})[：:](.+)", line)
        if m_dial:
            speaker = m_dial.group(1).strip()
            rest = m_dial.group(2).strip()
            if speaker in ("问题", "BE", "结局"):
                # Not dialogue, it's a control line
                elements.append(make_action(line))
                continue
            # Extract emotion tag: （xxx）
            emotion = ""
            m_emo = _re.match(r"[（(]([^）)]+)[）)](.+)", rest)
            if m_emo:
                emotion = m_emo.group(1).strip()
                rest = m_emo.group(2).strip()
            elements.append(make_dialogue(speaker, rest, emotion))
            continue

        # Default: treat as action/description
        elements.append(make_action(line))

    return elements


def render_content_to_text(content: list[ContentElement]) -> str:
    """Render structured content elements to display text."""
    parts: list[str] = []
    for el in content:
        if isinstance(el, str):
            parts.append(el)
            continue
        if not isinstance(el, dict):
            parts.append(str(el))
            continue
        t = el.get("type", "")
        if t == "scene_header":
            loc = el.get("location", "")
            time = el.get("time", "")
            chars = "、".join(el.get("characters", []))
            if loc or time or chars:
                parts.append(f"场景：{loc}")
                if time or chars:
                    parts.append(f"时：{time}    人：{chars}")
                parts.append("")
        elif t == "action":
            shot = el.get("shot", "")
            text = el.get("text", "")
            if shot:
                parts.append(f"▲{shot}：{text}")
            else:
                parts.append(f"▲{text}")
        elif t == "dialogue":
            speaker = el.get("speaker", "")
            emotion = el.get("emotion", "")
            line = el.get("line", "")
            if emotion:
                parts.append(f"{speaker}：（{emotion}）{line}")
            else:
                parts.append(f"{speaker}：{line}")
        elif t == "narration":
            parts.append(f"旁白：{el.get('text', '')}")
        elif t == "namecard":
            parts.append(f"【人名字幕条】{el.get('name', '')}，{el.get('title', '')}")
        else:
            parts.append(el.get("text", str(el)))
    return "\n".join(parts)


@dataclass
class Graph:
    root: NodeId
    nodes: dict[NodeId, Node] = field(default_factory=dict)

    def predecessors(self, node_id: NodeId) -> list[NodeId]:
        """Return all node IDs that have a choice pointing to node_id."""
        preds = []
        for nid, node in self.nodes.items():
            for c in node.choices:
                if c.to == node_id:
                    preds.append(nid)
                    break
        return preds

    def successors(self, node_id: NodeId) -> list[NodeId]:
        """Return destination node IDs from this node's choices."""
        return [c.to for c in self.nodes[node_id].choices]

    def all_edges(self) -> list[tuple[NodeId, Choice]]:
        """Return (from_node_id, choice) for every edge."""
        edges = []
        for nid, node in self.nodes.items():
            for c in node.choices:
                edges.append((nid, c))
        return edges

    def topo_order(self) -> list[NodeId]:
        """Topological sort via Kahn's algorithm. Raises if cyclic."""
        in_degree: dict[NodeId, int] = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for c in node.choices:
                if c.to in in_degree:
                    in_degree[c.to] += 1
        queue = [nid for nid, d in in_degree.items() if d == 0]
        order = []
        while queue:
            queue.sort()  # deterministic
            n = queue.pop(0)
            order.append(n)
            for c in self.nodes[n].choices:
                if c.to in in_degree:
                    in_degree[c.to] -= 1
                    if in_degree[c.to] == 0:
                        queue.append(c.to)
        if len(order) != len(self.nodes):
            raise ValueError("Graph contains a cycle")
        return order

# ---------- 1.6 Highlight, Goal, Params ----------

@dataclass
class Highlight:
    id: HighlightId
    chapter: int
    weight: float
    gloss: str
    satisfaction_type: str = ""  # 打脸|身份揭露|逆袭|反杀|护短|夺宝|隐藏实力
    hook_type: str = ""          # 悬念|危机|情感|反转

@dataclass
class Goal:
    entryA_state: State
    exitB_contract: list[Requirement]
    invariants: list[FactId]
    varying_state: list[FactId] = field(default_factory=list)  # DO NOT REFERENCE in content

@dataclass
class Params:
    target_playthrough_min: float = 55.0
    total_budget_min: float = 100.0
    words_per_min: float = 300.0
    max_fix_attempts: int = 10  # legacy cap for compatibility
    edge_structural_fix_attempts: int = 10
    edge_semantic_fix_attempts: int = 10
    cornerstone_fix_attempts: int = 10
    final_fix_attempts: int = 10
    max_llm_calls: int = 0  # 0 = unlimited
    min_ending_count: int = 1  # minimum ENDING nodes (not DEAD_END)
    editor_notes: str = ""  # free-text guidance injected into cornerstone prompt
    skip_upload: bool = False  # skip the final webapp DB upload (test runs)
    # Dead-end budget: expansion offers DEAD_END as a candidate target while
    # the graph has fewer dead ends than this. -1 → defaults to min_ending_count.
    target_dead_end_count: int = -1
    # Live review: re-upload intermediary state to the webapp at phase
    # milestones under one stable project id (status="running" until done).
    live_upload: bool = False

    def dead_end_target(self) -> int:
        return self.min_ending_count if self.target_dead_end_count < 0 \
            else self.target_dead_end_count
    stop_after: str = ""  # ""|"phase1"|"cornerstone"|"expansion" — early-exit gate for fast iteration
    # First-episode lab: after the trunk stabilizes, run P2.5/3.5/P4/4.5 on the
    # ROOT node only, write first_episode.md, and stop. With HARNESS_LLM_CACHE=1
    # this is a ~5-min lap for iterating on question/choice prompts.
    first_episode: bool = False
    # Mini-story lab: generate a tiny complete unit (1 choice → 2 endings, 3
    # nodes) directly from the opening chapters, with the per-node quality passes.
    mini_story: bool = False
    _llm_calls_used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def llm_calls_left(self) -> bool:
        if self.max_llm_calls <= 0:
            return True  # unlimited
        with self._lock:
            return self._llm_calls_used < self.max_llm_calls

    def use_llm_call(self) -> None:
        with self._lock:
            self._llm_calls_used += 1

    def llm_calls_used(self) -> int:
        with self._lock:
            return self._llm_calls_used

# ---------- Errors ----------

class HarnessError(Exception):
    pass

@dataclass
class Reject:
    reason: str

@dataclass
class Violation:
    node: NodeId
    check: str  # D1-D10 or S1-S5
    severity: str = "high"
    problem: str = ""
    suggested_fix: str = ""

@dataclass
class Feedback:
    violations: list[Violation] = field(default_factory=list)

    def empty(self) -> bool:
        return len(self.violations) == 0
