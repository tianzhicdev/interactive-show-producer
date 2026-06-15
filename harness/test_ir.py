"""Tests for the StoryPlan IR — built around a worked 替嫁王妃 example."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.ir import (
    Beat, Dilemma, DilemmaOption, LedgerEntry, PlanNode, PlayerStat,
    PlayerStateModel, ProtagonistGoal, Sequence, StoryPlan,
    compute_knowledge, dilemma_violations, knowledge_violations,
    ledger_violations, pacing_violations, plan_from_dict, plan_to_dict,
)
from harness.models import VARIES, Effect


def example_plan() -> StoryPlan:
    """替嫁王妃 mini-plan: prologue → t1 (with an excursion x1) → endings.

    x1 is a branch where 颜如玉 learns the accountant's nephew is really her
    husband 霍长鹤 in disguise — on the OTHER path she does not. The knowledge
    matrix must flag any t1 beat where she acts on that fact.
    """
    goals = [
        ProtagonistGoal(id="守护霍家", gloss="保护流放路上的婆家人"),
        ProtagonistGoal(id="查明真相", gloss="查清翼王谋反与构陷"),
        ProtagonistGoal(id="隐藏秘密", gloss="不暴露随身空间"),
    ]
    stats = [
        PlayerStat(id="player.bold", gloss="勇烈", low_effect="行事谨慎结局",
                   high_effect="刚烈结局"),
        PlayerStat(id="player.wary", gloss="隐忍"),
    ]

    n1 = PlanNode(
        id="n1", kind="prologue", sequence="A", arc_slot="hook",
        value="尊严", opening_charge="-", closing_charge="+",
        turning_type="action", tension=3,
        expectation="忍过鞭刑即可平安上路", result="鞭子落向婆母，忍无可忍",
        cast=["颜如玉", "颜松", "霍大夫人"], location="流放官道", time="清晨",
        entry_context="流放官道·清晨", exit_context="流放官道·清晨",
        duration_min=3.0, chapters=(1, 2),
        beats=[
            Beat(id="n1.b0", type="scene_header", text="流放官道"),
            Beat(id="n1.b1", type="action", role="buildup",
                 text="颜松扬鞭抽向队伍，押送兵卒冷眼旁观"),
            Beat(id="n1.b2", type="action", role="payoff",
                 text="颜如玉空手夺鞭，当众折断",
                 facts=["world.yan_song_humiliated"]),
            Beat(id="n1.b3", type="action", role="surprise",
                 text="颜松转而把鞭子甩向霍大夫人——这一鞭躲不开"),
            Beat(id="n1.b4", type="dialogue", role="decision_trigger",
                 speaker="颜松", text="威胁：再拦着，全家都别想活着到岭南"),
        ],
        dilemma=Dilemma(
            question="鞭子已落向婆母——舍身去挡还是记仇蓄力？",
            dilemma_type="irreconcilable_goods",
            trigger_beat="n1.b4",
            options=[
                DilemmaOption(
                    label="舍身去挡", to="t1", cost="暴露身手，被颜松记恨",
                    goal_impacts={"守护霍家": 1, "隐藏秘密": -1},
                    state_delta=[Effect(fact="player.bold", value=True)],
                    resolution=["硬接一鞭", "颜松眼神骤冷"]),
                DilemmaOption(
                    label="隐忍记账", to="x1", cost="婆母受伤，自责难消",
                    goal_impacts={"守护霍家": -1, "查明真相": 1},
                    state_delta=[Effect(fact="player.wary", value=True)],
                    resolution=["按下怒火", "记住每一笔账"]),
            ],
        ),
    )

    # Excursion: only THIS path learns the nephew's true identity
    x1 = PlanNode(
        id="x1", kind="scene", sequence="A",
        value="信任", opening_charge="-", closing_charge="+",
        turning_type="revelation", tension=4,
        expectation="跟踪账房侄子抓住把柄", result="他竟是夫君霍长鹤易容",
        cast=["颜如玉", "霍长鹤"], location="林中空地", time="夜",
        entry_context="流放官道·夜", exit_context="林中空地·夜",
        duration_min=2.5, chapters=(2, 3),
        beats=[
            Beat(id="x1.b0", type="scene_header", text="林中空地"),
            Beat(id="x1.b1", type="action", role="buildup",
                 text="颜如玉夜探，账房侄子察觉反将她逼入树影"),
            Beat(id="x1.b2", type="action", role="surprise",
                 text="缠斗中面具脱落——竟是霍长鹤",
                 facts=["world.nephew_is_husband"],
                 reveals_to=["颜如玉"]),
            Beat(id="x1.b3", type="dialogue", role="decision_trigger",
                 speaker="霍长鹤", text="他按住她的刀：现在你知道了，怎么办？",
                 uses=["world.nephew_is_husband"]),
        ],
        dilemma=Dilemma(
            question="夫君易容随行——结盟同谋还是装作不知？",
            dilemma_type="lesser_of_two_evils",
            trigger_beat="x1.b3",
            options=[
                DilemmaOption(label="结盟同谋", to="t1", cost="秘密多一人知晓",
                              goal_impacts={"查明真相": 1, "隐藏秘密": -1},
                              state_delta=[Effect(fact="player.allied", value=True)],
                              resolution=["低声立约", "并肩回营"]),
                DilemmaOption(label="装作不知", to="t1", cost="错失强援，独自涉险",
                              goal_impacts={"隐藏秘密": 1, "查明真相": -1},
                              state_delta=[Effect(fact="player.lone", value=True)],
                              resolution=["收刀转身", "各自归位"]),
            ],
        ),
    )

    # Convergence bottleneck: BOTH paths arrive; must be path-neutral
    t1 = PlanNode(
        id="t1", kind="bottleneck", sequence="B", arc_slot="lock_in",
        value="生死", opening_charge="+", closing_charge="-",
        turning_type="action", tension=5,
        expectation="熬到驿站便能喘息", result="颜松夜里要对霍家下死手",
        cast=["颜如玉", "颜松"], location="驿站", time="深夜",
        entry_context="驿站·深夜", exit_context="驿站·深夜",
        duration_min=3.0, chapters=(3, 4),
        beats=[
            Beat(id="t1.b0", type="scene_header", text="驿站"),
            Beat(id="t1.b1", type="action", role="recap",
                 text="清点伤情与处境：流放第三日，颜松步步紧逼"),
            Beat(id="t1.b2", type="action", role="surprise",
                 text="颜如玉撞破颜松向井中投毒",
                 facts=["world.poison_plot"]),
            Beat(id="t1.b3", type="dialogue", role="decision_trigger",
                 speaker="颜松", text="毒已入井：你敢声张，先死的是你婆母",
                 uses=["world.poison_plot"]),
        ],
        dilemma=Dilemma(
            question="井水已被投毒——当场揭发还是暗中换水？",
            dilemma_type="lesser_of_two_evils",
            trigger_beat="t1.b3",
            options=[
                DilemmaOption(label="当场揭发", to="e1", cost="撕破脸，再无转圜",
                              goal_impacts={"查明真相": 1, "守护霍家": -1},
                              resolution=["惊动全队", "对峙升级"]),
                DilemmaOption(label="暗中换水", to="e2", cost="罪证沉默，颜松逍遥",
                              goal_impacts={"守护霍家": 1, "查明真相": -1},
                              resolution=["夜半换水", "不动声色"]),
            ],
        ),
    )

    e1 = PlanNode(id="e1", kind="ending", ending="ENDING", sequence="C",
                  tension=4, duration_min=2.5, cast=["颜如玉"],
                  opening_charge="-", closing_charge="+", value="正义",
                  entry_context="驿站·深夜", exit_context="驿站·黎明",
                  beats=[Beat(id="e1.b0", type="scene_header", text="驿站"),
                         Beat(id="e1.b1", type="action", role="aftermath",
                              text="对峙后的黎明，尘埃落定")])
    e2 = PlanNode(id="e2", kind="ending", ending="ENDING", sequence="C",
                  tension=3, duration_min=2.5, cast=["颜如玉"],
                  opening_charge="-", closing_charge="+", value="隐忍",
                  entry_context="驿站·深夜", exit_context="驿站·黎明",
                  beats=[Beat(id="e2.b0", type="scene_header", text="驿站"),
                         Beat(id="e2.b1", type="action", role="aftermath",
                              text="水换罢，长夜无声，账先记下")])

    ledger = [
        LedgerEntry(id="q.main", kind="question",
                    gloss="霍家能否在流放路上活下来并翻案？",
                    planted_at="n1.b1", refs=["t1.b1"], closed_at="",
                    intentionally_open=True),  # answered later in full story
        LedgerEntry(id="irony.husband_identity", kind="irony",
                    gloss="观众知道账房侄子是霍长鹤，颜松不知道",
                    planted_at="x1.b2", closed_at="t1.b1",
                    meta={"revelation": "x1.b2", "recognition": "t1.b1"}),
        LedgerEntry(id="dangling.yan_song_threat", kind="dangling_cause",
                    gloss="颜松的灭门威胁必须兑现或反噬",
                    planted_at="n1.b4", refs=["t1.b3"], closed_at="t1.b3"),
    ]

    return StoryPlan(
        title="替嫁王妃·迷你示例", root="n1",
        sequences=[
            Sequence(id="A", function="hook", span_pct=(0.0, 0.11),
                     question_id="q.main", bottleneck="t1"),
            Sequence(id="B", function="lock_in", span_pct=(0.11, 0.25),
                     bottleneck="t1"),
        ],
        nodes={"n1": n1, "x1": x1, "t1": t1, "e1": e1, "e2": e2},
        ledger=ledger,
        player=PlayerStateModel(goals=goals, stats=stats),
    )


def test_roundtrip():
    plan = example_plan()
    plan2 = plan_from_dict(plan_to_dict(plan))
    assert plan2.nodes["t1"].dilemma.trigger_beat == "t1.b3"
    assert plan2.nodes["x1"].beats[2].reveals_to == ["颜如玉"]
    assert plan2.player.goals[0].id == "守护霍家"


def test_topology_and_convergence():
    plan = example_plan()
    assert plan.predecessors("t1") == ["n1", "x1"]
    assert len(plan.paths()) == 4  # (direct|excursion×2 options) × 2 endings... bounded


def test_knowledge_matrix_varies_at_convergence():
    plan = example_plan()
    entry = compute_knowledge(plan)
    # 颜如玉 learns the husband-identity fact only on the x1 path → VARIES at t1
    assert entry["t1"][("颜如玉", "world.nephew_is_husband")] is VARIES
    # audience always knows it on x1-descendant paths, but t1 is convergent → VARIES too
    assert entry["t1"][("audience", "world.nephew_is_husband")] is VARIES
    # but x1's own established fact is known inside x1's post — check e-entry via t1 OK


def test_knowledge_violation_when_using_path_dependent_fact():
    plan = example_plan()
    # Make t1 (convergence) USE the path-dependent identity fact → violation
    plan.nodes["t1"].beats[2].uses = ["world.nephew_is_husband"]
    problems = knowledge_violations(plan)
    assert any("world.nephew_is_husband" in p and "t1" in p for p in problems)
    # The clean plan has no knowledge violations
    assert not knowledge_violations(example_plan())


def test_pacing_clean_and_nonevent_detection():
    plan = example_plan()
    assert pacing_violations(plan) == []
    plan.nodes["x1"].closing_charge = "-"  # equal to opening → nonevent
    assert any("D16 nonevent: x1" in p for p in pacing_violations(plan))


def test_ledger_closure():
    plan = example_plan()
    assert ledger_violations(plan) == []
    plan.ledger[2].closed_at = ""  # unclose the dangling threat
    assert any("dangling.yan_song_threat" in p for p in ledger_violations(plan))


def test_dilemma_gate():
    plan = example_plan()
    assert dilemma_violations(plan) == []
    # Dominated option: all-positive impacts
    plan.nodes["n1"].dilemma.options[0].goal_impacts = {"守护霍家": 1, "查明真相": 1}
    assert any("dominated" in p for p in dilemma_violations(plan))


def test_trigger_beat_must_be_at_peak():
    plan = example_plan()
    plan.nodes["t1"].dilemma.trigger_beat = "t1.b1"  # early beat, not the peak
    problems = dilemma_violations(plan)
    assert any("tension peak" in p for p in problems)
