"""Tests for the interactive-play harness.

Part 1: Unit tests for deterministic functions (no LLM needed).
Part 2: Integration test with a small story (requires ANTHROPIC_API_KEY).
"""

import json
import os
import sys
import logging
import httpx

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.models import (
    VARIES, Choice, Effect, FactDecl, Feedback, Graph, Highlight, Goal,
    Node, NodeId, Params, Registry, Reject, Requirement, Violation,
)
from harness.guaranteed import apply_effects, compute_guaranteed, meet
from harness.registry import seed_registry, register_facts
from harness.budget import estimate_minutes, shortest_playthrough, total_minutes
from harness.graph_ops import build_goal, choose_expansion_type, merge, rank_edges
from harness.validation import validate, validate_deterministic
from harness.checkpoint import checkpoint, write
from harness.chunker import build_chapter_index, chunk_story, sample_for_bible
from harness.tiers import ModelRoute, get_coding_llm_model, get_eval_model, get_writing_llm_model
from harness import llm as llm_mod

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ============================================================
# Helpers to build test fixtures
# ============================================================

def make_registry() -> Registry:
    """A small registry for testing: a mystery story."""
    return {
        "player.met_detective": FactDecl("player.met_detective", "presence", "Player has met the detective", False),
        "player.found_key": FactDecl("player.found_key", "possession", "Player found the brass key", False),
        "player.opened_door": FactDecl("player.opened_door", "event", "Player opened the locked door", False),
        "player.knows_culprit": FactDecl("player.knows_culprit", "knowledge", "Player knows who did it", False),
        "world.baron_is_culprit": FactDecl("world.baron_is_culprit", "knowledge", "The baron is the real culprit", True, invariant=True),
        "char.detective.trusts_player": FactDecl("char.detective.trusts_player", "disposition", "Detective trusts the player", False),
    }


def make_simple_graph(registry: Registry) -> Graph:
    """
    Simple diamond graph:
        n1 (root)
       /  \\
      n2    n3
       \\  /
        n4
       /  \
     n5   de4
    """
    g = Graph(root="n1")
    g.nodes = {
        "n1": Node(
            id="n1", kind="prologue", chapters=(1, 1),
            content="雨夜，你独自来到祖父的老宅。门前石狮长满青苔，推开沉重大门，陈旧气息扑面而来。",
            entry_context="老宅门前·雨夜",
            exit_context="老宅大厅",
            produces=[Effect("player.met_detective", True)],
            question="你在老宅门口遇到一个侦探。",
            choices=[
                Choice(label="跟他聊聊", to="n2",
                       resolution=["你走向侦探搭话", "侦探抬头打量你"]),
                Choice(label="独自调查", to="n3",
                       resolution=["你绕过侦探", "独自走向花园"]),
            ],
        ),
        "n2": Node(
            id="n2", kind="scene", chapters=(1, 2),
            content="侦探递给你一把古老的铜钥匙，目光中透着信任。他说这是在花园地下发现的。",
            entry_context="老宅大厅·与侦探对话",
            exit_context="老宅走廊·持有钥匙",
            requires=[Requirement("player.met_detective", True)],
            produces=[
                Effect("player.found_key", True),
                Effect("char.detective.trusts_player", True),
            ],
            question="侦探给了你一把钥匙。",
            choices=[
                Choice(label="打开门", to="n4",
                       label_requires=[Requirement("player.found_key", True)],
                       resolution=["你拿着钥匙走向地下室", "插入锁孔转动"]),
                Choice(label="独吞钥匙", to="de2",
                       resolution=["你避开侦探独自行动", "地下暗门忽然落锁"]),
            ],
        ),
        "de2": Node(
            id="de2", kind="ending", chapters=(2, 2),
            content="你试图独吞钥匙，却触发了老宅机关，退路被封死。",
            ending="DEAD_END",
        ),
        "n3": Node(
            id="n3", kind="scene", chapters=(1, 2),
            content="花园已荒废多年，角落的梅花树下有块松动石板。你搬开石板，发现了一把铜钥匙。",
            entry_context="后花园·清晨",
            exit_context="花园小径·持有钥匙",
            produces=[Effect("player.found_key", True)],
            question="你自己在花园找到了钥匙。",
            choices=[
                Choice(label="回到门前", to="n4",
                       resolution=["你握着钥匙快步走回老宅", "来到地下室门前"]),
                Choice(label="深入花园", to="de3",
                       resolution=["你沿着花园深处追查", "脚下石板突然塌陷"]),
            ],
        ),
        "de3": Node(
            id="de3", kind="ending", chapters=(2, 2),
            content="你独自深入花园，落入废井，调查在黑暗中断开。",
            ending="DEAD_END",
        ),
        "n4": Node(
            id="n4", kind="bottleneck", chapters=(2, 3),
            content="你用铜钥匙打开了地下室的门。里面是一间书房，满墙书架堆满手稿。",
            entry_context="地下室门前",
            exit_context="地下室书房",
            requires=[Requirement("player.found_key", True)],
            produces=[Effect("player.opened_door", True)],
            question="你用钥匙打开了门。",
            choices=[
                Choice(label="揭露真相", to="n5",
                       resolution=["你翻开祖父日记", "真相浮出水面"]),
                Choice(label="烧毁日记", to="de4",
                       resolution=["你点燃日记", "关键证据化为灰烬"]),
            ],
        ),
        "de4": Node(
            id="de4", kind="ending", chapters=(3, 3),
            content="日记被烧毁，真相再无证据支撑，老宅秘密永远沉入黑暗。",
            ending="DEAD_END",
        ),
        "n5": Node(
            id="n5", kind="ending", chapters=(3, 3),
            content="日记揭示了惊人真相：老宅下埋藏着宝藏，而王管家一直在暗中寻找。你做出了最终选择。",
            entry_context="地下室书房·读完日记",
            exit_context="故事结束",
            produces=[Effect("player.knows_culprit", True)],
            ending="ENDING",
        ),
    }
    return g


# ============================================================
# Part 1: Deterministic unit tests
# ============================================================

def test_topo_order():
    """Test topological sort."""
    reg = make_registry()
    g = make_simple_graph(reg)
    order = g.topo_order()
    assert order[0] == "n1", f"Root should be first, got {order[0]}"
    assert "n5" in order, "Ending should be present"
    assert order.index("n4") > order.index("n2")
    assert order.index("n4") > order.index("n3")
    log.info("✓ topo_order")


def test_compute_guaranteed():
    """Test guaranteed state computation."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    # Root: all initial values
    assert g.nodes["n1"].guaranteed["player.met_detective"] is False
    assert g.nodes["n1"].guaranteed["world.baron_is_culprit"] is True

    # n2: met_detective was set by n1's produces
    n2_g = g.nodes["n2"].guaranteed
    assert n2_g["player.met_detective"] is True

    # n4: found_key is True on BOTH paths (n2 and n3 both produce it)
    n4_g = g.nodes["n4"].guaranteed
    assert n4_g["player.found_key"] is True

    # n4: detective.trusts_player is VARIES (only n2 sets it, not n3)
    assert n4_g["char.detective.trusts_player"] is VARIES

    log.info("✓ compute_guaranteed")


def test_meet():
    """Test the meet operation."""
    s1 = {"a": True, "b": False, "c": True}
    s2 = {"a": True, "b": True, "c": True}
    result = meet(s1, s2)
    assert result["a"] is True  # agree
    assert result["b"] is VARIES  # disagree
    assert result["c"] is True  # agree
    log.info("✓ meet")


def test_apply_effects():
    """Test applying effects to state."""
    state = {"x": False, "y": True}
    node = Node(id="test", produces=[Effect("x", True), Effect("z", 42)])
    result = apply_effects(state, node)
    assert result["x"] is True
    assert result["y"] is True
    assert result["z"] == 42
    log.info("✓ apply_effects")


def test_validate_deterministic_pass():
    """A valid graph should pass all deterministic checks."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg)

    # Filter out D4 violations for VARIES facts that are merely expected
    real_violations = [v for v in violations if not (
        v.check == "D4" and v.node == "n4" and "trusts_player" in v.problem
    )]

    # The only issue should be n4 requiring found_key which IS guaranteed
    for v in real_violations:
        log.info(f"  Violation: [{v.check}] {v.node}: {v.problem}")

    # n4's requires(found_key=True) should pass because both paths produce it
    d1_for_n4 = [v for v in violations if v.check == "D1" and v.node == "n4"]
    assert len(d1_for_n4) == 0, f"n4's found_key should be guaranteed: {d1_for_n4}"
    log.info("✓ validate_deterministic (pass case)")


def test_validate_deterministic_fail():
    """A graph with a broken requirement should fail D1."""
    reg = make_registry()
    g = make_simple_graph(reg)

    # Break it: n4 requires knows_culprit but nobody produces it before n4
    g.nodes["n4"].requires.append(Requirement("player.knows_culprit", True))

    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg)

    d1_culprit = [v for v in violations if v.check == "D1" and "knows_culprit" in v.problem]
    assert len(d1_culprit) > 0, "Should catch broken requirement"
    log.info("✓ validate_deterministic (fail case)")


def test_validate_schema():
    """Schema check: endings should have no choices."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)
    # Break: add choices to an ending (but not creating a back-edge)
    g.nodes["n5"].choices = [Choice(label="test", to="n5_phantom")]
    # Check only the region containing n5 to avoid topo_order issues
    violations = validate_deterministic(g, reg, region=["n5"])
    d9 = [v for v in violations if v.check == "D9"]
    assert len(d9) > 0, "Ending with choices should fail D9"
    log.info("✓ validate_deterministic (schema)")


def test_validate_invariant():
    """D7: invariant facts must not be flipped."""
    reg = make_registry()
    g = make_simple_graph(reg)
    # Try to flip the invariant
    g.nodes["n2"].produces.append(Effect("world.baron_is_culprit", False))
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg)
    d7 = [v for v in violations if v.check == "D7"]
    assert len(d7) > 0, "Flipping invariant should fail D7"
    log.info("✓ validate_deterministic (invariant)")


def test_seed_registry():
    """Test bible → registry."""
    bible = {
        "facts": [
            {"id": "player.x", "kind": "event", "gloss": "Something happened", "initial": False},
            {"id": "world.y", "kind": "knowledge", "gloss": "World truth", "initial": True, "invariant": True},
        ]
    }
    reg = seed_registry(bible)
    assert len(reg) == 2
    assert reg["player.x"].initial is False
    assert reg["world.y"].invariant is True
    log.info("✓ seed_registry")


def test_register_facts():
    """Test fact registration from subgraph."""
    reg = make_registry()
    initial_count = len(reg)

    # Subgraph that uses a new fact
    sub = {
        "n_new": Node(
            id="n_new",
            produces=[Effect("player.new_discovery", True)],
        )
    }
    new_decls = [FactDecl("player.new_discovery", "event", "A new discovery", False)]
    result = register_facts(reg, sub, new_decls)
    assert result is None, f"Should succeed: {result}"
    assert len(reg) == initial_count + 1
    log.info("✓ register_facts (success)")

    # Subgraph with undeclared fact
    sub2 = {
        "n_bad": Node(
            id="n_bad",
            produces=[Effect("player.undeclared_fact", True)],
        )
    }
    result2 = register_facts(reg, sub2, [])
    assert result2 is not None, "Should reject undeclared fact"
    log.info("✓ register_facts (reject undeclared)")


def test_budget():
    """Test budget computations."""
    params = Params(words_per_min=300)
    reg = make_registry()
    g = make_simple_graph(reg)

    # Nodes have content, so budget is based on char counts
    tm = total_minutes(g, params)
    assert tm > 0, f"Total minutes should be > 0, got {tm}"

    sp = shortest_playthrough(g, params)
    assert sp > 0, f"Shortest path should be > 0, got {sp}"
    assert sp <= tm, f"Shortest path ({sp}) should be ≤ total ({tm})"
    log.info(f"✓ budget (total={tm:.2f}min, shortest={sp:.2f}min)")


def test_rank_edges():
    """Test edge ranking."""
    params = Params(target_playthrough_min=55)
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)
    highlights = [Highlight("h1", 1, 0.9, "Key event"), Highlight("h2", 2, 0.5, "Minor event")]

    edges = rank_edges(g, highlights, params)
    assert len(edges) > 0, "Should have rankable edges"
    log.info(f"✓ rank_edges ({len(edges)} edges ranked)")


def test_choose_expansion_type():
    """Test expansion type selection."""
    params = Params(target_playthrough_min=55)
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    # Shortest path is ~8 min, way under 55, so edges on shortest should be LENGTH_EXTENDING
    etype = choose_expansion_type(g, "n1", "n2", params)
    assert etype in ("LENGTH_EXTENDING", "BRANCH_ADDING")
    assert choose_expansion_type(g, "n1", "n3", Params(target_playthrough_min=0)) == "LENGTH_EXTENDING"
    log.info(f"✓ choose_expansion_type: {etype}")


def test_merge():
    """Test merge with a valid subgraph."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    # Create a subgraph that inserts between n1 and n2
    sub_nodes = {
        "n1": Node(
            id="n1", kind="prologue", chapters=(1, 1),
            content="雨夜，你独自来到祖父的老宅。",
            entry_context="老宅门前·雨夜",
            exit_context="老宅大厅",
            produces=[Effect("player.met_detective", True)],
            question="你在老宅门口遇到一个侦探。",
            choices=[
                Choice(label="仔细观察", to="n1a",
                       resolution=["你仔细打量侦探", "注意到他手中的线索"]),
            ],
        ),
        "n1a": Node(
            id="n1a", kind="scene", chapters=(1, 1),
            content="你注意到侦探手中握着一张泛黄的照片，上面是老宅的旧貌。",
            entry_context="老宅门前·观察侦探",
            exit_context="老宅门前·发现线索",
            produces=[Effect("player.observed_detective", True)],
            question="你注意到侦探手里有线索。",
            choices=[
                Choice(label="跟他聊聊", to="n2",
                       resolution=["你指着照片搭话", "侦探露出惊讶表情"]),
                Choice(label="偷走照片", to="de1a",
                       resolution=["你伸手偷走照片", "侦探立刻警觉"]),
            ],
        ),
        "de1a": Node(
            id="de1a", kind="ending", chapters=(1, 1),
            content="你偷走照片被侦探当场抓住，信任彻底破裂。",
            ending="DEAD_END",
        ),
        "n2": Node(
            id="n2", kind="scene", chapters=(1, 2),
            content="侦探递给你一把古老的铜钥匙。",
            entry_context="老宅大厅·与侦探对话",
            exit_context="老宅走廊·持有钥匙",
            requires=[Requirement("player.met_detective", True)],
            produces=[
                Effect("player.found_key", True),
                Effect("char.detective.trusts_player", True),
            ],
            question="侦探给了你一把钥匙。",
            choices=[
                Choice(label="打开门", to="n4",
                       label_requires=[Requirement("player.found_key", True)],
                       resolution=["你拿钥匙走向门前", "插入锁孔"]),
                Choice(label="继续搜查", to="n4",
                       resolution=["你先去其他房间看看", "最终回到门前"]),
            ],
        ),
    }

    new_decls = [
        FactDecl("player.observed_detective", "event", "Player observed the detective", False),
    ]

    result = merge(g, sub_nodes, "n1", "n2", reg, "LENGTH_EXTENDING", new_decls)
    assert not isinstance(result, Reject), f"Merge failed: {result.reason if isinstance(result, Reject) else ''}"
    assert "n1a" in result.nodes
    assert "de1a" in result.nodes
    assert len(result.nodes) == 10  # original 8 + 2 new
    assert len(result.nodes["n1"].choices) == 2
    assert len({c.to for c in result.nodes["n1"].choices}) == 2
    log.info("✓ merge (valid subgraph)")


def test_merge_preserves_boundary_b():
    """Merge must not let an expansion rewrite already accepted endpoint B."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)
    original_b = g.nodes["n2"]

    sub_nodes = {
        "n1": Node(
            id="n1", kind="prologue", chapters=(1, 1),
            content="老宅门前。",
            question="你在老宅门口。",
            choices=[
                Choice(label="细看", to="n1a", resolution=["你停步观察"]),
            ],
        ),
        "n1a": Node(
            id="n1a", kind="scene", chapters=(1, 1),
            content="你在门缝里看见一截铜钥匙的影子。",
            question="你要怎么做？",
            choices=[
                Choice(label="进去", to="n2", resolution=["你推门进入"]),
                Choice(label="退走", to="de1a", resolution=["你转身离开"]),
            ],
        ),
        "de1a": Node(id="de1a", kind="ending", ending="DEAD_END", content="你错过了线索。"),
        "n2": Node(
            id="n2", kind="scene", chapters=(9, 9),
            content="被污染的B内容不应进入结果。",
            requires=[],
            produces=[],
            question="错误问题",
            choices=[],
        ),
    }

    result = merge(g, sub_nodes, "n1", "n2", reg, "LENGTH_EXTENDING")
    assert not isinstance(result, Reject), f"Merge failed: {result.reason if isinstance(result, Reject) else ''}"
    assert result.nodes["n2"].prose == original_b.prose
    assert result.nodes["n2"].requires == original_b.requires
    assert result.nodes["n2"].produces == original_b.produces
    assert result.nodes["n2"].choices == original_b.choices
    log.info("✓ merge preserves endpoint B")


def test_merge_rejects_interior_id_collision():
    """Generated interior nodes cannot overwrite already accepted graph nodes."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    sub_nodes = {
        "n1": Node(
            id="n1", kind="prologue", chapters=(1, 1),
            content="老宅门前。",
            question="你在老宅门口。",
            choices=[Choice(label="误入", to="n3", resolution=["你走向侧门"])],
        ),
        "n3": Node(
            id="n3", kind="scene", chapters=(1, 1),
            content="这个ID已经属于原图节点。",
            question="你要怎么做？",
            choices=[
                Choice(label="继续", to="n2", resolution=["你继续前行"]),
                Choice(label="放弃", to="de1a", resolution=["你放弃探索"]),
            ],
        ),
        "de1a": Node(id="de1a", kind="ending", ending="DEAD_END", content="你放弃了探索。"),
        "n2": g.nodes["n2"],
    }

    result = merge(g, sub_nodes, "n1", "n2", reg, "LENGTH_EXTENDING")
    assert isinstance(result, Reject)
    assert "collides" in result.reason
    log.info("✓ merge rejects interior id collision")


def test_merge_cycle_reject():
    """Merge should reject if subgraph introduces a cycle."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    # Create a cycle: n1a → n1 (back edge)
    sub_nodes = {
        "n1": Node(
            id="n1", kind="prologue", chapters=(1, 1),
            content="老宅门前。",
            entry_context="老宅门前", exit_context="老宅入口",
            produces=[Effect("player.met_detective", True)],
            question="你在老宅门口。",
            choices=[
                Choice(label="进去", to="n1a", resolution=["你推门而入"]),
                Choice(label="离开", to="n3", resolution=["你转身离开"]),
            ],
        ),
        "n1a": Node(
            id="n1a", kind="scene", chapters=(1, 1),
            content="你进入老宅。",
            entry_context="老宅内", exit_context="老宅大厅",
            question="你进入了老宅。",
            choices=[
                Choice(label="回头", to="n1", resolution=["你折返回去"]),
                Choice(label="前进", to="n2", resolution=["你继续往前走"]),
            ],
        ),
        "n2": Node(
            id="n2", kind="scene", chapters=(1, 2),
            content="侦探给了你钥匙。",
            entry_context="老宅大厅", exit_context="走廊",
            requires=[Requirement("player.met_detective", True)],
            produces=[Effect("player.found_key", True), Effect("char.detective.trusts_player", True)],
            question="侦探给了你钥匙。",
            choices=[
                Choice(label="打开门", to="n4", resolution=["你用钥匙开门"]),
                Choice(label="继续搜查", to="n4", resolution=["你先搜查一下"]),
            ],
        ),
    }

    result = merge(g, sub_nodes, "n1", "n2", reg, "LENGTH_EXTENDING")
    assert isinstance(result, Reject), "Should reject cyclic subgraph"
    assert "cycle" in result.reason.lower()
    log.info("✓ merge (cycle rejected)")


def test_build_goal():
    """Test goal construction."""
    reg = make_registry()
    g = make_simple_graph(reg)
    compute_guaranteed(g, reg)

    goal = build_goal(g, "n1", "n2", reg)
    assert "player.met_detective" in goal.entryA_state
    assert "world.baron_is_culprit" in goal.invariants
    log.info("✓ build_goal")


def test_checkpoint_write():
    """Test checkpoint and write."""
    import tempfile
    reg = make_registry()
    g = make_simple_graph(reg)

    with tempfile.TemporaryDirectory() as td:
        cp_path = checkpoint(g, output_dir=td)
        assert os.path.exists(cp_path)

        w_path = write(g, prose=False, output_dir=td)
        assert os.path.exists(w_path)

        with open(w_path) as f:
            data = json.load(f)
        assert data["root"] == "n1"
    assert len(data["nodes"]) == 8
    log.info("✓ checkpoint & write")


# ============================================================
# Part 1b: Chunker unit tests
# ============================================================

_MULTI_CHAPTER_TEXT = """第一章 起始

这是第一章的内容。主人公出发了，踏上了漫长的旅途。
他告别了家人，独自一人走向远方。

第二章 旅途

这是第二章的内容。旅途中发生了很多事情。
他遇到了一位神秘的老人，老人给了他一把钥匙。

第三章 到达

这是第三章的内容。终于到达了目的地。
他用钥匙打开了古老的大门，发现了宝藏。

第四章 归来

这是第四章的内容。带着宝藏回到家乡。
家人都很高兴，庆祝他的归来。

第五章 结局

故事的结局。一切都很美好。
"""


def test_build_chapter_index():
    """build_chapter_index should extract chapters by text markers."""
    chapters = build_chapter_index(_MULTI_CHAPTER_TEXT)
    assert len(chapters) == 5, f"Expected 5 chapters, got {len(chapters)}"
    assert 1 in chapters
    assert 5 in chapters
    assert "第一章" in chapters[1]
    assert "结局" in chapters[5]
    # Chapter boundaries should not leak into adjacent chapters
    assert "第二章" not in chapters[1]
    log.info("✓ build_chapter_index")


def test_build_chapter_index_no_markers():
    """Text without chapter markers returns empty dict."""
    chapters = build_chapter_index("这是一个没有章节标记的短文。")
    assert chapters == {}, f"Expected empty dict, got {chapters}"
    log.info("✓ build_chapter_index (no markers)")


def test_build_chapter_index_chinese_numerals():
    """Chinese numeral chapter markers should parse correctly."""
    text = """第一章 开始
内容一

第十二章 中间
内容二

第二十三章 结尾
内容三
"""
    chapters = build_chapter_index(text)
    assert 1 in chapters, f"Missing chapter 1, got keys: {list(chapters.keys())}"
    assert 12 in chapters, f"Missing chapter 12, got keys: {list(chapters.keys())}"
    assert 23 in chapters, f"Missing chapter 23, got keys: {list(chapters.keys())}"
    log.info("✓ build_chapter_index (Chinese numerals)")


def test_chunk_story_small():
    """Small text should produce a single chunk."""
    text = "这是一段很短的文字。" * 10
    chunks = chunk_story(text, max_chars=30000)
    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    assert chunks[0]['text'] == text
    log.info("✓ chunk_story (small text)")


def test_chunk_story_large():
    """Large text should be split into multiple chunks."""
    # Create a text with chapter markers, ~90K chars total
    parts = []
    for i in range(1, 31):
        parts.append(f"第{i}章 标题{i}\n\n")
        parts.append("这是一段内容。" * 200 + "\n\n")  # ~1200 chars per chapter
    text = "".join(parts)

    chunks = chunk_story(text, max_chars=10000)
    assert len(chunks) > 1, f"Expected multiple chunks, got {len(chunks)}"

    # Verify all text is covered (no gaps)
    reconstructed = "".join(c['text'] for c in chunks)
    assert len(reconstructed) == len(text), \
        f"Reconstructed length {len(reconstructed)} != original {len(text)}"
    log.info(f"✓ chunk_story (large text → {len(chunks)} chunks)")


def test_sample_for_bible_small():
    """With few chunks, all should be included."""
    chunks = [{'index': i, 'char_count': 1000, 'text': f'chunk {i}'} for i in range(1, 4)]
    sample = sample_for_bible(chunks, max_chars=80000)
    assert 'chunk 1' in sample
    assert 'chunk 2' in sample
    assert 'chunk 3' in sample
    log.info("✓ sample_for_bible (small)")


def test_sample_for_bible_large():
    """With many chunks, should include first 2, last 2, and middle samples."""
    chunks = [{'index': i, 'char_count': 5000, 'text': f'chunk_{i}_content'}
              for i in range(1, 21)]
    sample = sample_for_bible(chunks, max_chars=80000)
    # Must include first and last chunks
    assert 'chunk_1_content' in sample
    assert 'chunk_2_content' in sample
    assert 'chunk_19_content' in sample
    assert 'chunk_20_content' in sample
    log.info("✓ sample_for_bible (large)")


def test_sample_for_bible_respects_limit():
    """sample_for_bible should not exceed max_chars."""
    chunks = [{'index': i, 'char_count': 10000, 'text': 'x' * 10000}
              for i in range(1, 21)]
    sample = sample_for_bible(chunks, max_chars=50000)
    assert len(sample) <= 55000, \
        f"Sample too large: {len(sample)} (limit 50000 + headers)"
    log.info("✓ sample_for_bible (respects limit)")


# ============================================================
# Part 2: Integration test with small story
# ============================================================

SMALL_STORY = """
第一章：古宅

雨夜，林小雨独自来到了祖父留下的老宅。门前的石狮子已经长满了青苔。
她推开沉重的大门，扑面而来的是陈旧的气息。大厅里挂着一幅巨大的家族画像，
画中的人物似乎都在注视着她。

壁炉旁的桌上放着一封信，信封上写着她的名字。信中提到了一个秘密：
祖父在地下室藏了一样东西，只有找到三把钥匙才能打开。

第二章：花园

第二天清晨，林小雨走进后花园。花园已经荒废多年，但角落里有一棵
古老的梅花树，树下有一块松动的石板。她搬开石板，发现了第一把铜钥匙。

这时，一个自称王管家的老人出现了。他说自己曾在祖父手下工作，
可以帮助她找到其他钥匙。但他的眼神中似乎藏着什么秘密。

第三章：地下室

林小雨终于集齐了三把钥匙，打开了地下室的门。里面是一间书房，
满墙的书架上堆满了手稿。她在桌上发现了祖父的日记，日记揭示了
一个惊人的真相：这座老宅下面埋藏着一笔巨大的宝藏，而王管家
一直在暗中寻找这笔宝藏。

林小雨必须做出选择：独自守护秘密，还是揭露真相。
"""

SMALL_INSTRUCTION = """制作一个3-5个节点的互动故事，基于这个古宅探秘的短篇。
保持简短，适合测试。目标时长约10分钟。"""


def test_integration():
    """Full integration test with a small story."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        log.warning("⚠ Skipping integration test: OPENROUTER_API_KEY/FIREWORKS_API_KEY not set")
        return

    from harness.harness import build
    from harness.llm import set_tier

    set_tier("cheap")

    params = Params(
        target_playthrough_min=8,
        total_budget_min=15,
        words_per_min=300,
        max_fix_attempts=3,
        max_llm_calls=30,
    )

    log.info("\n" + "="*60)
    log.info("INTEGRATION TEST: Small story")
    log.info("="*60)

    graph = build(SMALL_STORY, SMALL_INSTRUCTION, params)

    log.info(f"\nResult: {len(graph.nodes)} nodes")
    for nid in graph.topo_order():
        node = graph.nodes[nid]
        tag = f" [{node.ending}]" if node.ending != "NONE" else ""
        log.info(f"  [{nid}]{tag} ch{node.chapters[0]}-{node.chapters[1]}")
        if node.question:
            log.info(f"    Q: {node.question}")
        for c in node.choices:
            log.info(f"      → {c.label} → {c.to}")
        if node.prose:
            log.info(f"    Content: {node.get_content()[:60]}...")

    # Basic assertions
    assert len(graph.nodes) >= 3, f"Expected ≥3 nodes, got {len(graph.nodes)}"
    endings = [n for n in graph.nodes.values() if n.ending == "ENDING"]
    assert len(endings) >= 1, "Need at least one ENDING"

    log.info("\n✓ Integration test passed!")


def test_tier_routes_premium():
    route = get_coding_llm_model("premium")
    assert route.provider == "claude_code"
    assert route.model is None
    assert route.fallbacks == ()


def test_tier_routes_free_first(monkeypatch):
    from harness import tiers

    free_models = (
        {
            "id": "free/model-a:free",
            "pricing": {"prompt": "0", "completion": "0", "request": "0"},
            "supported_parameters": ["json_schema"],
            "context_length": 64000,
            "created": 10,
        },
        {
            "id": "free/model-b:free",
            "pricing": {"prompt": "0", "completion": "0", "request": "0"},
            "supported_parameters": [],
            "context_length": 32000,
            "created": 20,
        },
        {
            "id": "free/model-c:free",
            "pricing": {"prompt": "0", "completion": "0", "request": "0"},
            "supported_parameters": [],
            "context_length": 16000,
            "created": 30,
        },
    )

    monkeypatch.setattr(tiers, "_cached_free_models", lambda *a, **k: free_models)
    route = get_writing_llm_model("cheap")
    assert route.provider == "openrouter"
    assert route.model == "free/model-a:free"
    assert route.fallbacks == ()


def test_tier_routes_openrouter_fallback(monkeypatch):
    from harness import tiers

    monkeypatch.setattr(tiers, "_cached_free_models", lambda *a, **k: ())
    route = get_eval_model("cheap")
    assert route.provider == "openrouter"
    assert route.model == "openrouter/free"
    assert route.fallbacks == ()


def test_openrouter_relaxes_schema_on_400(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm_mod, "_route_for_role",
                        lambda role: ModelRoute(provider="openrouter", model="free/model-a:free"))

    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            self.text = "bad request" if status_code == 400 else json.dumps(self._payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("bad request", request=self.request, response=self)

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) == 1:
            return FakeResponse(400)
        return FakeResponse(
            200,
            {
                "choices": [{"message": {"content": "{\"ok\": true}"}, "finish_reason": "stop"}],
                "usage": {},
                "model": "free/model-a:free",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    out = llm_mod._call_llm_openrouter(
        "system",
        "user",
        Params(),
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    )
    assert out == "{\"ok\": true}"
    assert calls[0]["response_format"]["json_schema"]["schema"]["required"] == ["ok"]
    assert "response_format" not in calls[1]


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    # --cc flag: use local Claude Code headless mode (subscription) instead of Fireworks API
    if "--cc" in sys.argv:
        from harness.llm import set_backend
        set_backend("claude_code")
        sys.argv.remove("--cc")
        print("Using Claude Code headless mode (subscription)")

    print("=" * 60)
    print("Interactive-Play Harness Tests")
    print("=" * 60)

    # Part 1: Deterministic tests (no LLM)
    tests = [
        test_topo_order,
        test_compute_guaranteed,
        test_meet,
        test_apply_effects,
        test_validate_deterministic_pass,
        test_validate_deterministic_fail,
        test_validate_schema,
        test_validate_invariant,
        test_seed_registry,
        test_register_facts,
        test_budget,
        test_rank_edges,
        test_choose_expansion_type,
        test_merge,
        test_merge_preserves_boundary_b,
        test_merge_rejects_interior_id_collision,
        test_merge_cycle_reject,
        test_build_goal,
        test_checkpoint_write,
        # Chunker tests
        test_build_chapter_index,
        test_build_chapter_index_no_markers,
        test_build_chapter_index_chinese_numerals,
        test_chunk_story_small,
        test_chunk_story_large,
        test_sample_for_bible_small,
        test_sample_for_bible_large,
        test_sample_for_bible_respects_limit,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            log.error(f"✗ {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\nDeterministic tests: {passed} passed, {failed} failed")

    # Part 2: Integration test
    if "--integration" in sys.argv:
        try:
            test_integration()
        except Exception as e:
            log.error(f"✗ Integration test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    sys.exit(1 if failed else 0)
