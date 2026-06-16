"""Soft LLM worker wrappers — distrusted; output always validated by harness."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .validation import NodeMemory

from .models import (
    Choice, Effect, FactDecl, Feedback, Graph, HarnessError, Highlight, Goal,
    Node, NodeId, Params, Registry, Requirement, State, VARIES, Violation,
)

log = logging.getLogger(__name__)

LLM_RETRY_ATTEMPTS = 10
JSON_RETRY_ATTEMPTS = 10

# Load instruction files at module level
_HARNESS_DIR = Path(__file__).parent
_CREATIVE_WRITING_MD = (_HARNESS_DIR / "CREATIVE_WRITING.md").read_text()
_CHOICE_DESIGN_MD = (_HARNESS_DIR / "CHOICE_DESIGN.md").read_text()
# Generation prompts get a DIGEST — the full rulebook (tables included) bloats
# the cornerstone prompt enough to collapse glm-5p1's JSON emission (observed:
# 2x 1-node trunks). Full text remains for S-judge rubrics & humans.
_CHOICE_DESIGN_DIGEST = """## 选择设计规则（摘要，违者拒绝）
**核心：选择=两个竞争性收益之间的取舍（competing goods），不是"做大胆的事 vs 忍气吞声"。**
玩家两样都想要，却只能拿一样；选 A 就放弃 B，选 B 就放弃 A。这才是两难。
反例（被支配，必拒）：「掰腕立威」(得立威+冒险) vs「吞声蛰伏」(只是失去威慑、无收获)——
没人选第二项。正例：「搜刮地库」(得财富，舍线索) vs「搜寻书房」(得线索，舍财富)。

生成顺序（强制）：
1. 先找本场两个**都积极、玩家都想要**的收获 A 和 B（财富/真相/情报/立威/盟友/时机/保命…），
   且 A≠B、属同一赌注层级（生死>使命>阵营>关系>脸面）。
2. 选项1=争取A（代价=失去B），选项2=争取B（代价=失去A）。可再加各自的额外风险。
3. question 同时点名 A 和 B：「为A舍B，还是为B舍A？」——两边都是玩家想要的正向目标。
4. 最后写 ≤8字 label：动词开头，争取某物（争/夺/取/搜/护/换…），不写否定/忍让。

硬规则：
- **每个选项必须命名一个玩家主动想要的正向收获**；选项不得是另一项的"否定/不做/忍住"
  （吞声/蛰伏/隐忍/认命/退让/作罢/按兵不动 作 label = 违规）。
- 若某选项只能写出"避免了选项1的坏处"而没有自己的正向收获 → 这不是选择点 → 重铸：
  问"忍/退买到了什么积极目标？"(情报?时机?盟友?避免暴露?)，把那个收获写成正向 label。
- 两边收获具体度对称；一边确定另一边模糊 = 倾斜，违规。
- 两选项的 goal_impacts 必须各自有正项、方向相反（各得一目标、各舍一目标）。
- question 必含对比（…还是…）且两边都是正向目标名词，不是"冒X险 vs 失Y"。
- 危险选项写得更鲜活；选错也要推进剧情（fail forward）。
- 两 label 语法平行、长度差≤3字、动作互斥、禁态度词。"""
_CREATIVE_WRITING_SKELETON_MD = (
    (_HARNESS_DIR / "CREATIVE_WRITING_SKELETON.md").read_text()
    + "\n\n" + _CHOICE_DESIGN_DIGEST
)
_CREATIVE_WRITING_PROSE_MD = (_HARNESS_DIR / "CREATIVE_WRITING_PROSE.md").read_text()
_VALIDATION_MD = (_HARNESS_DIR / "VALIDATION.md").read_text()

# ---------- LLM backend selection ----------

_LLM_BACKEND = "fireworks"  # "fireworks" | "claude_code"
_LLM_MODEL: str | None = None

_MODEL_ALIASES = {
    "fireworks": ("fireworks", "accounts/fireworks/models/glm-5p1"),
    "glm": ("fireworks", "accounts/fireworks/models/glm-5p1"),
    "glm-5p1": ("fireworks", "accounts/fireworks/models/glm-5p1"),
    "deepseek": ("fireworks", "accounts/fireworks/models/deepseek-v4-pro"),
    "deepseek-v4-pro": ("fireworks", "accounts/fireworks/models/deepseek-v4-pro"),
    "fable": ("anthropic", "claude-fable-5"),
    "fable-5": ("anthropic", "claude-fable-5"),
    "cc": ("claude_code", None),
    "claude": ("claude_code", None),
    "claude_code": ("claude_code", None),
}

_VALUE_SCHEMA = {"type": ["boolean", "integer", "number", "string"]}
_FACT_DECL_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string"},
        "gloss": {"type": "string"},
        "initial": _VALUE_SCHEMA,
        "invariant": {"type": "boolean"},
    },
    "required": ["id", "kind", "gloss", "initial", "invariant"],
}
_REQ_SCHEMA = {
    "type": "object",
    "properties": {
        "fact": {"type": "string", "description": "事实ID，必须在registry中已声明"},
        "value": {**_VALUE_SCHEMA, "description": "期望的事实值"},
    },
    "required": ["fact"],
}
_EFFECT_SCHEMA = {
    "type": "object",
    "properties": {
        "fact": {"type": "string", "description": "事实ID"},
        "value": {"description": "事实值", "oneOf": [{"type": "boolean"}, {"type": "integer"}, {"type": "string"}]},
        "beat": {"type": "string", "description": "建立此事实的节拍ID（如b3）"},
    },
    "required": ["fact", "value"],
}
_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "≤8中文字，玩家视角的动作描述，不泄露目标内容"},
        "to": {"type": "string", "description": "目标节点ID"},
        "label_requires": {"type": "array", "items": _REQ_SCHEMA, "description": "显示此选项前玩家必须满足的条件"},
        "resolution": {"type": "array", "items": {"type": "string"}, "description": "恰好2个短句，展示选择后的结果走向"},
        "state_delta": {"type": "array", "items": _EFFECT_SCHEMA,
                        "description": "选此项后追加的状态变化。两个选择可指向同一目标节点，"
                                       "但此时各自的state_delta必须不同（选择写状态而非分叉）"},
        "cost": {"type": "string", "description": "此选项不可逆地付出/冒险的代价（一句话）"},
        "goal_impacts": {"type": "object",
                         "description": "对主角各目标的影响，如 {\"守护家人\": 1, \"查明真相\": -1}。"
                                        "真两难=每个选项都对某个目标为负；全非负=伪选择"},
    },
    "required": ["label", "to", "resolution"],
}
_CONTENT_ELEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["scene_header", "action", "dialogue", "narration", "namecard"],
                 "description": "元素类型"},
        "id": {"type": "string", "description": "稳定节拍ID（b1, b2, ...），用于produces.beat引用"},
        "location": {"type": "string", "description": "[scene_header] 场景地点名"},
        "time": {"type": "string", "description": "[scene_header] 时段（如：深夜、黄昏、午后）"},
        "characters": {"type": "array", "items": {"type": "string"},
                       "description": "[scene_header] 出场角色列表"},
        "shot": {"type": "string", "description": "[action] 镜头语言：特写/中景/全景/手持/俯拍/主观/AI"},
        "text": {"type": "string", "description": "[action/narration] 动作描述或旁白文本"},
        "speaker": {"type": "string", "description": "[dialogue] 说话角色名"},
        "emotion": {"type": "string", "description": "[dialogue] 角色动作/表情标注"},
        "line": {"type": "string", "description": "[dialogue] 台词内容"},
        "name": {"type": "string", "description": "[namecard] 角色名"},
        "title": {"type": "string", "description": "[namecard] 一句话身份介绍"},
        "facts": {"type": "array", "items": {"type": "string"},
                  "description": "本节拍建立的事实ID列表（提示prose生成器）"},
        "role": {"type": "string",
                 "description": "节拍的戏剧职能：buildup|payoff|surprise|decision_trigger|recap|preparation|aftermath。"
                                "非结局节点的最后一个节拍必须是 decision_trigger（逼出 question 的突发/反转/最后通牒）"},
    },
    "required": ["type"],
}
_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "节点唯一标识符"},
        "kind": {"type": "string", "description": "节点类型：prologue|scene|bottleneck|ending"},
        "skeleton": {"type": "array", "items": _CONTENT_ELEMENT_SCHEMA, "minItems": 3,
                     "description": "骨架节拍列表（单一来源）。必须以scene_header开头。每个节拍携带id（b1,b2,...）和可选的facts标签。非DEAD_END≥5个节拍，DEAD_END/ENDING≥3个（下限由确定性校验器按节点类型强制；schema 仅设 3 的底线，避免合法的短结局被 strict 模式拒绝）。"},
        "content": {"type": "array", "items": _CONTENT_ELEMENT_SCHEMA, "minItems": 3,
                     "description": "剧本内容元素列表（Phase 4扩展后的prose）。必须以scene_header开头。"},
        "planned_duration_min": {"type": "number", "description": "最终 prose/shooting 预计时长，单位分钟。非DEAD_END必须2-5，DEAD_END可1-1.5"},
        "chapters": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "description": "覆盖的原作章节范围 [起始章, 结束章]"},
        "covers": {"type": "array", "items": {"type": "string"}, "description": "本节点覆盖的高光点ID列表"},
        "produces": {"type": "array", "items": _EFFECT_SCHEMA, "description": "本节点建立的事实。beat字段指向建立该事实的节拍ID。"},
        "requires": {"type": "array", "items": _REQ_SCHEMA, "description": "进入前玩家必须已持有的事实。首次出现的元素无需requires"},
        "entry_invariants": {"type": "array", "items": _REQ_SCHEMA, "description": "进入时必须成立的不变量约束"},
        "ending": {"type": "string", "description": "NONE=普通节点 | ENDING=正式结局 | DEAD_END=死胡同"},
        "question": {"type": ["string", "null"], "description": "≤30中文字，向玩家提出的选择问题。结局节点为null"},
        "choices": {"type": "array", "items": _CHOICE_SCHEMA, "description": "非结局节点必须恰好2个选择。两个选择可指向同一目标（此时state_delta必须不同），否则目标必须不同。结局节点为空数组"},
        "entry_context": {"type": "string", "description": "进入此节点时的场景状态（地点、时间、氛围）"},
        "exit_context": {"type": "string", "description": "离开此节点时的场景状态，为后续节点提供衔接"},
        "sequence": {"type": "string", "description": "所属段落 A-H（trunk 节点必填）"},
        "arc_slot": {"type": "string",
                     "description": "hook|lock_in|first_attempt|midpoint|complication|main_culmination|crisis|climax|resolution"},
        "tension": {"type": "integer", "description": "张力强度 1-5（4-5 为爽点/危机峰值）"},
        "value": {"type": "string", "description": "本场押上的价值：信任/生死/自由/尊严…"},
        "opening_charge": {"type": "string", "enum": ["+", "-"],
                           "description": "开场价值极性，只能是 + 或 -"},
        "closing_charge": {"type": "string", "enum": ["+", "-"],
                           "description": "收场价值极性，只能是 + 或 -。必须与开场不同（场必须翻转）"},
        "turning_type": {"type": "string", "enum": ["action", "revelation"],
                         "description": "本场翻转方式"},
        "expectation": {"type": "string", "description": "主角对结果的预期（Gap 的一半）"},
        "result": {"type": "string", "description": "实际发生的事——必须偏离预期"},
    },
    "required": [
        "id", "kind", "skeleton", "planned_duration_min",
        "chapters", "covers", "produces",
        "requires", "entry_invariants", "ending", "question", "choices",
        "entry_context", "exit_context",
    ],
}
_SKELETON_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        **_NODE_SCHEMA["properties"],
    },
    "required": [
        "id", "kind", "skeleton", "planned_duration_min",
        "chapters", "covers", "produces",
        "requires", "entry_invariants", "ending", "question", "choices",
        "entry_context", "exit_context",
    ],
}
_SKELETON_NODES_MAP = {
    "type": "object",
    "additionalProperties": _SKELETON_NODE_SCHEMA,
}
_SKELETON_SUBGRAPH_SCHEMA = {
    "type": "object",
    "properties": {"nodes": _SKELETON_NODES_MAP, "new_facts": {"type": "array", "items": _FACT_DECL_SCHEMA}},
    "required": ["nodes", "new_facts"],
}
_SKELETON_CORNERSTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "root": {"type": "string"},
        "new_facts": {"type": "array", "items": _FACT_DECL_SCHEMA},
        "nodes": _SKELETON_NODES_MAP,
    },
    "required": ["root", "nodes", "new_facts"],
}

# Prose fill schema: single node's content array
_PROSE_FILL_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "array", "items": _CONTENT_ELEMENT_SCHEMA, "minItems": 3},
        "aftermaths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "对应的选择 label（原样）"},
                    "elements": {"type": "array", "items": _CONTENT_ELEMENT_SCHEMA,
                                 "description": "3-6 个剧本元素：选择后的即时后果，戏剧化呈现（动作/对白/旁白），不是概述"},
                },
                "required": ["label", "elements"],
            },
            "description": "每个选择一个支线段落，玩家选择后在本节点末尾播放（结局节点为空数组）",
        },
    },
    "required": ["content"],
}

_NEW_FACTS = {"type": "array", "items": _FACT_DECL_SCHEMA}
_NODES_MAP = {
    "type": "object",
    "additionalProperties": _NODE_SCHEMA,
}

_PROTAGONIST_GOALS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "gloss": {"type": "string"}},
        "required": ["id", "gloss"],
    },
}
_STORY_BIBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "protagonist_goals": _PROTAGONIST_GOALS_SCHEMA,
        "world": {"type": "string"},
        "characters": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "role", "description"],
            },
        },
        "setting": {"type": "string"},
        "opening_scene": {"type": "string",
                          "description": "原著最开头那一场的字面描述：WHERE/WHEN、在场人物、正在发生的引子事件，以及这一场里会自然浮现的背景信息（身份、世界观、危机）。这是故事真正的起点，不是后续高潮危机。"},
        "default_license": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "minItems": 5, "items": _FACT_DECL_SCHEMA},
    },
    "required": ["world", "characters", "setting", "default_license", "facts"],
}
_STORY_BIBLE_CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "world": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "role", "description"],
            },
        },
        "setting": {"type": "string"},
        "opening_scene": {"type": "string",
                          "description": "仅当本 chunk 是原著开头时填写：最开头那一场的字面描述（WHERE/WHEN、在场人物、引子事件、会自然浮现的背景）。非开头 chunk 留空字符串。"},
        "default_license": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "items": _FACT_DECL_SCHEMA},
        "protagonist_goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "gloss": {"type": "string"}},
                "required": ["id", "gloss"],
            },
            "description": "主角的2-3个长期目标（如 复仇/守护家人/隐藏身份），用于选择两难判定",
        },
    },
    "required": ["world", "characters", "setting", "default_license", "facts"],
}
_HIGHLIGHTS_SCHEMA = {
    "type": "array",
    "minItems": 5,
    "maxItems": 16,
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "chapter": {"type": "integer"},
            "weight": {"type": "number"},
            "gloss": {"type": "string"},
            "satisfaction_type": {"type": "string",
                                  "description": "爽点类型：打脸|身份揭露|逆袭|反杀|护短|夺宝|隐藏实力（若是爽点）"},
            "hook_type": {"type": "string",
                          "description": "钩子类型：悬念|危机|情感|反转（若是钩子）"},
        },
        "required": ["id", "chapter", "weight", "gloss"],
    },
}
_HIGHLIGHTS_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": _HIGHLIGHTS_SCHEMA,
    },
    "required": ["highlights"],
}
_OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "main_dramatic_question": {"type": "string",
                                   "description": "全片主问题，一句话（观众层面的悬念）"},
        "sequences": {
            "type": "array", "minItems": 4, "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "A-H"},
                    "function": {"type": "string",
                                 "description": "hook|lock_in|first_attempt|midpoint|complication|main_culmination|crisis_finale"},
                    "span_pct": {"type": "array", "items": {"type": "number"},
                                 "description": "[起,止] 占全片比例，如 [0.0, 0.11]"},
                    "dramatic_question": {"type": "string",
                                          "description": "本段局部张力问题（与主问题不同）"},
                    "bottleneck_gloss": {"type": "string",
                                         "description": "本段结尾汇合点的剧情（一句话）"},
                    "satisfaction_beats": {"type": "array", "items": {"type": "string"},
                                           "description": "安排在本段的爽点/钩子 highlight id 列表"},
                    "chapters": {"type": "array", "items": {"type": "integer"},
                                 "description": "本段覆盖的原作章节 [起,止]"},
                },
                "required": ["id", "function", "dramatic_question", "bottleneck_gloss"],
            },
        },
        "ledger": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string",
                             "description": "question|setup|dangling_cause|irony|motif"},
                    "gloss": {"type": "string"},
                    "plant_sequence": {"type": "string", "description": "在哪段埋下 A-H"},
                    "close_sequence": {"type": "string", "description": "在哪段兑现 A-H"},
                    "fact_id": {"type": "string",
                                "description": "代表此义务的事实ID（world.*），埋下节点 produces 它，引用节点 requires 它"},
                },
                "required": ["id", "kind", "gloss", "plant_sequence", "close_sequence", "fact_id"],
            },
        },
        "player_stats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "player.xxx"},
                    "gloss": {"type": "string"},
                    "low_effect": {"type": "string"},
                    "high_effect": {"type": "string"},
                },
                "required": ["id", "gloss"],
            },
            "description": "玩家累积状态轴（选择的 state_delta 写入这些轴）",
        },
    },
    "required": ["main_dramatic_question", "sequences", "ledger", "player_stats"],
}
_CORNERSTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "root": {"type": "string"},
        "new_facts": _NEW_FACTS,
        "nodes": _NODES_MAP,
    },
    "required": ["root", "nodes", "new_facts"],
}
_SUBGRAPH_SCHEMA = {
    "type": "object",
    "properties": {"nodes": _NODES_MAP, "new_facts": _NEW_FACTS},
    "required": ["nodes", "new_facts"],
}
_PROSE_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "content": {"type": "array", "items": _CONTENT_ELEMENT_SCHEMA, "minItems": 3},
                },
                "required": ["content"],
            },
        }
    },
    "required": ["nodes"],
}
_VIOLATIONS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "node": {"type": "string"},
            "check": {"type": "string"},
            "severity": {"type": "string"},
            "problem": {"type": "string"},
            "suggested_fix": {"type": "string"},
        },
        "required": ["node", "check", "problem"],
    },
}
_VIOLATIONS_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "violations": _VIOLATIONS_SCHEMA,
    },
    "required": ["violations"],
}
_SUMMARY_VIOLATION_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "fixed_summary": {"type": "string"},
    },
    "required": ["fixed_summary"],
}
_SKELETON_NODE_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "node": _SKELETON_NODE_SCHEMA,
        "upstream_fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "produces_to_add": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"fact": {"type": "string"}, "value": {}}, "required": ["fact", "value"]},
                    },
                    "produces_to_remove": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "summary_patch": {"type": "string"},
                },
                "required": ["node_id"],
            },
        },
    },
    "required": ["node"],
}
_S4_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
    },
    "required": ["question", "labels"],
}

_COMPETING_GOODS_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "choices": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "gain": {"type": "string"},
                    "cost": {"type": "string"},
                    "goal_impacts": {"type": "object"},
                },
                "required": ["label", "gain", "cost", "goal_impacts"],
            },
        },
    },
    "required": ["question", "choices"],
}


def set_backend(backend: str, model: str | None = None) -> None:
    """Switch LLM backend: 'fireworks' (API) or 'claude_code' (local subscription)."""
    global _LLM_BACKEND, _LLM_MODEL
    if backend not in ("fireworks", "anthropic", "claude_code", "fake"):
        raise ValueError(f"Unknown backend: {backend!r}. "
                         f"Use 'fireworks', 'anthropic', 'claude_code' or 'fake'.")
    if backend == "claude_code":
        _preflight_claude_code()
    _LLM_BACKEND = backend
    _LLM_MODEL = model
    if model:
        log.info("LLM backend set to: %s (%s)", backend, model)
    else:
        log.info(f"LLM backend set to: {backend}")


def set_model_profile(profile: str) -> None:
    """Switch LLM backend/model using a CLI-friendly profile alias."""
    normalized = (profile or "fireworks").strip().lower()
    if normalized == "fake":
        backend, model = "fake", "fake"
    elif normalized in _MODEL_ALIASES:
        backend, model = _MODEL_ALIASES[normalized]
    elif normalized.startswith("accounts/"):
        backend, model = "fireworks", profile
    else:
        raise ValueError(
            f"Unknown model profile: {profile!r}. "
            f"Use one of {sorted(_MODEL_ALIASES)} or a Fireworks model id."
        )
    set_backend(backend, model)


def _preflight_claude_code() -> None:
    """Fail fast on Claude Code auth/quota problems before long schema calls."""
    import subprocess

    timeout_s = int(os.environ.get("CLAUDE_CODE_PREFLIGHT_TIMEOUT_S", "30"))
    cmd = [
        "claude", "-p", "--max-turns", "1",
        "--output-format", "text", "--tools", "",
    ]
    try:
        result = subprocess.run(
            cmd, input="Reply with OK only.",
            capture_output=True, text=True, timeout=timeout_s,
            env=_claude_code_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Claude Code preflight timed out after {timeout_s}s"
        ) from e

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    if result.returncode != 0:
        if "hit your limit" in output.lower():
            raise RuntimeError(f"Claude Code quota exhausted: {output}")
        raise RuntimeError(f"Claude Code preflight failed: {output or result.returncode}")


def _cache_dir() -> str | None:
    """LLM response cache dir. Enabled via HARNESS_LLM_CACHE=1 (default path
    .llm_cache/) or HARNESS_LLM_CACHE=/custom/path. Off when unset."""
    val = os.environ.get("HARNESS_LLM_CACHE", "")
    if not val:
        return None
    return ".llm_cache" if val == "1" else val


def _cache_path_for(system: str, user: str, json_schema: dict | None,
                    reasoning_effort: str | None) -> str | None:
    cache_d = _cache_dir()
    if not cache_d:
        return None
    import hashlib
    key_src = json.dumps(
        [_LLM_BACKEND, _LLM_MODEL, system, user, json_schema, reasoning_effort],
        ensure_ascii=False, sort_keys=True,
    )
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()
    os.makedirs(cache_d, exist_ok=True)
    return os.path.join(cache_d, f"{key}.json")


def invalidate_cached_response(system: str, user: str, json_schema: dict | None,
                               reasoning_effort: str | None) -> None:
    """Drop a cached response that failed parse/schema validation — otherwise
    every retry replays the same bad answer from disk."""
    path = _cache_path_for(system, user, json_schema, reasoning_effort)
    if path and os.path.exists(path):
        os.remove(path)
        log.info("LLM cache invalidated (validation failure)")


def _call_llm(system: str, user: str, params: Params, json_schema: dict | None = None,
              reasoning_effort: str | None = None, cacheable: bool = True) -> str:
    """Dispatch LLM call to the configured backend (with optional disk cache).

    cacheable=False for fix/validate loop calls: those loops rely on sampling
    variation to escape repeated failures; serving identical cached responses
    turns them into infinite echo loops."""
    if _LLM_BACKEND == "fake":
        from .fake_llm import fake_response
        return fake_response(system, user, json_schema)

    cache_path = (_cache_path_for(system, user, json_schema, reasoning_effort)
                  if cacheable else None)
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        log.info("LLM cache hit (%s...)", os.path.basename(cache_path)[:12])
        return cached["response"]

    if _LLM_BACKEND == "claude_code":
        result = _call_llm_claude_code(system, user, params, json_schema=json_schema)
    elif _LLM_BACKEND == "anthropic":
        result = _call_llm_anthropic(system, user, params, json_schema=json_schema,
                                     reasoning_effort=reasoning_effort)
    else:
        result = _call_llm_fireworks(system, user, params, json_schema=json_schema,
                                     reasoning_effort=reasoning_effort)

    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump({"response": result}, fh, ensure_ascii=False)
    return result


# ---------- Backend: Fireworks API ----------

def _call_llm_fireworks(
    system: str, user: str, params: Params, json_schema: dict | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Call the LLM via Fireworks API (OpenAI-compatible)."""
    import httpx

    params.use_llm_call()

    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY not set")

    model = _LLM_MODEL or os.environ.get(
        "FIREWORKS_MODEL",
        "accounts/fireworks/models/glm-5p1",
    )

    for attempt in range(LLM_RETRY_ATTEMPTS):
        try:
            payload = {
                "model": model,
                "max_tokens": int(os.environ.get("HARNESS_MAX_TOKENS", "32000")),
                "temperature": 0.2 if json_schema is not None else 1.0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if reasoning_effort:
                # Verified on glm-5p1: "none" → direct answer (~20x fewer
                # completion tokens); "low" → bounded thinking in
                # reasoning_content. Structure calls default to low.
                payload["reasoning_effort"] = reasoning_effort
            if json_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "HarnessOutput",
                        "schema": json_schema,
                        "strict": True,
                    },
                }

            response = httpx.post(
                "https://api.fireworks.ai/inference/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=float(os.environ.get("HARNESS_READ_TIMEOUT_S", "300")),
                    write=30.0, pool=30.0,
                ),
            )
            response.raise_for_status()
            data = response.json()

            # Check for truncation
            finish_reason = data["choices"][0].get("finish_reason", "")
            if finish_reason == "length":
                log.warning("LLM response truncated (hit max_tokens). Output may be incomplete.")

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            log.info(
                "LLM response: %d chars, finish=%s, tokens=%s/%s",
                len(content) if content else 0,
                finish_reason,
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
            )
            if not content or not content.strip():
                log.warning("LLM returned empty content, retrying...")
                if attempt < LLM_RETRY_ATTEMPTS - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
            return content
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else 0
            if status not in (429, 500, 502, 503, 504) or attempt == LLM_RETRY_ATTEMPTS - 1:
                raise
            log.warning(
                "Fireworks transient HTTP %s (attempt %d/%d), retrying",
                status, attempt + 1, LLM_RETRY_ATTEMPTS,
            )
            import time
            time.sleep(min(30, 2 ** attempt))
        except (
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as e:
            if attempt == LLM_RETRY_ATTEMPTS - 1:
                raise
            log.warning(
                "Fireworks transient network error %s (attempt %d/%d), retrying",
                type(e).__name__, attempt + 1, LLM_RETRY_ATTEMPTS,
            )
            import time
            # Connect-class errors usually mean the local network/DNS is down:
            # waiting longer is free and rides out short outages (~10 min total).
            if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
                time.sleep(60)
            else:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"LLM call failed after {LLM_RETRY_ATTEMPTS} attempts")


# ---------- Backend: Anthropic API ----------

# Running token totals for cost visibility (fable is expensive — every call logs
# the cumulative spend so a runaway loop is visible immediately).
_ANTHROPIC_TOKENS = {"in": 0, "out": 0}


def _call_llm_anthropic(
    system: str, user: str, params: Params, json_schema: dict | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Call the Anthropic Messages API (claude-fable-5 etc.).

    Forced tool_choice is not supported on claude-fable-5, so json_schema is
    enforced by instruction: the schema is appended to the system prompt and
    the JSON is parsed from the response text (the downstream parsers already
    extract JSON from the end and retry on mismatch). Thinking is adaptive on
    this model and cannot be disabled; reasoning_effort is ignored.
    """
    import httpx

    params.use_llm_call()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = _LLM_MODEL or "claude-fable-5"
    # Output cap independent of HARNESS_MAX_TOKENS (48k is a glm knob; fable
    # output is billed per token — 16k covers the largest prose node).
    max_tokens = int(os.environ.get("HARNESS_ANTHROPIC_MAX_TOKENS", "16000"))

    if json_schema is not None:
        system = (
            f"{system}\n\n"
            "输出要求：只输出一个符合下列 JSON Schema 的 JSON 对象，"
            "不要输出任何其他文字、Markdown 代码块或解释。\n"
            f"JSON Schema:\n{json.dumps(json_schema, ensure_ascii=False)}"
        )
    # temperature is deprecated on claude-fable-5 (adaptive thinking models) —
    # sending it at all is a 400.
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    for attempt in range(LLM_RETRY_ATTEMPTS):
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=float(os.environ.get("HARNESS_READ_TIMEOUT_S", "300")),
                    write=30.0, pool=30.0,
                ),
            )
            response.raise_for_status()
            data = response.json()

            usage = data.get("usage", {})
            _ANTHROPIC_TOKENS["in"] += usage.get("input_tokens", 0)
            _ANTHROPIC_TOKENS["out"] += usage.get("output_tokens", 0)

            content = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            )
            stop = data.get("stop_reason", "")
            if stop == "max_tokens":
                log.warning("Anthropic response truncated (hit max_tokens).")
            log.info(
                "Anthropic response: %d chars, stop=%s, tokens=%s/%s "
                "(session total %d in / %d out)",
                len(content), stop,
                usage.get("input_tokens", "?"), usage.get("output_tokens", "?"),
                _ANTHROPIC_TOKENS["in"], _ANTHROPIC_TOKENS["out"],
            )
            if not content or not content.strip():
                log.warning("Anthropic returned empty content, retrying...")
                if attempt < LLM_RETRY_ATTEMPTS - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
            return content
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else 0
            if status not in (429, 500, 502, 503, 529) or attempt == LLM_RETRY_ATTEMPTS - 1:
                raise
            log.warning("Anthropic transient HTTP %s (attempt %d/%d), retrying",
                        status, attempt + 1, LLM_RETRY_ATTEMPTS)
            import time
            time.sleep(min(60, 5 * (attempt + 1)))
        except (
            httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError,
            httpx.NetworkError, httpx.RemoteProtocolError,
        ) as e:
            if attempt == LLM_RETRY_ATTEMPTS - 1:
                raise
            log.warning("Anthropic transient network error %s (attempt %d/%d), retrying",
                        type(e).__name__, attempt + 1, LLM_RETRY_ATTEMPTS)
            import time
            if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
                time.sleep(60)
            else:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Anthropic call failed after {LLM_RETRY_ATTEMPTS} attempts")


# ---------- Backend: Claude Code headless ----------

def _call_llm_claude_code(
    system: str, user: str, params: Params, json_schema: dict | None = None
) -> str:
    """Call LLM via local Claude Code headless mode (uses Claude subscription).

    Uses `claude -p` with --system-prompt and --bare for fast, tool-free generation.
    """
    import subprocess

    params.use_llm_call()

    model = os.environ.get("CC_MODEL", "")

    # Structured output is emitted as a StructuredOutput tool call. If the CLI's
    # schema validator rejects the first tool input, Claude Code needs another
    # assistant turn to repair it before returning a successful result.
    max_turns = os.environ.get("CLAUDE_CODE_STRUCTURED_MAX_TURNS", "4") if json_schema is not None else "1"
    # --strict-mcp-config with no --mcp-config disables ALL external MCP servers:
    # these utility calls need no project tools, and spinning the full MCP stack
    # up in parallel headless sessions is slow and a frequent source of exit-1.
    cmd = ["claude", "-p", "--max-turns", max_turns, "--strict-mcp-config"]
    if json_schema is not None:
        cmd.extend([
            "--output-format", "json",
            "--json-schema", json.dumps(
                _claude_code_compatible_schema(json_schema),
                ensure_ascii=False,
            ),
        ])
    else:
        cmd.extend([
            "--output-format", "text",
            "--tools", "",
        ])
    if model:
        cmd.extend(["--model", model])

    # Combine system + user into a single stdin prompt to avoid ARG_MAX limits.
    # The system prompt can be very large (includes CREATIVE_WRITING.md + context).
    combined = f"<instructions>\n{system}\n</instructions>\n\n{user}" if system else user

    import time
    timeout_s = int(os.environ.get("CLAUDE_CODE_TIMEOUT_S", "1200"))
    # Back-compat: CLAUDE_CODE_TIMEOUT_RETRIES still honored; CLAUDE_CODE_RETRIES preferred.
    max_retries = int(os.environ.get(
        "CLAUDE_CODE_RETRIES",
        os.environ.get("CLAUDE_CODE_TIMEOUT_RETRIES", "10")))
    max_retries = max(1, min(max_retries, LLM_RETRY_ATTEMPTS))

    last_err = "(no attempts)"
    for attempt in range(max_retries):
        # ALL transient failures retry with backoff: timeout, non-zero exit
        # (flaky subprocess / momentary API error), and empty output. Only a
        # quota-exhaustion message fails fast — retrying that is pointless.
        try:
            result = subprocess.run(
                cmd, input=combined,  # pipe everything via stdin
                capture_output=True, text=True, timeout=timeout_s,
                env=_claude_code_env(),
            )
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout_s}s"
        else:
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and json_schema is not None:
                    return _extract_claude_structured_output(output)
                if output:
                    return output
                last_err = "empty output"
            else:
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()
                # stderr first — it carries the real error, not the JSON init stream.
                combined_error = "\n".join(p for p in (stderr, stdout) if p)
                if "hit your limit" in combined_error.lower():
                    raise RuntimeError(f"Claude Code quota exhausted: {combined_error[:500]}")
                if stdout and json_schema is not None:
                    try:
                        return _extract_claude_structured_output(stdout)
                    except Exception:
                        pass
                err_head = stderr[-1500:] if stderr else ""
                out_tail = stdout[-2500:] if stdout else ""
                detail = "\n".join(p for p in (err_head, out_tail) if p)
                last_err = f"exit {result.returncode}: {detail or '(no output)'}"

        if attempt < max_retries - 1:
            log.warning("Claude Code %s (attempt %d/%d), retrying...",
                        last_err, attempt + 1, max_retries)
            time.sleep(min(30, 2 ** attempt))

    raise RuntimeError(
        f"Claude Code failed after {max_retries} attempts; last error: {last_err}")


def _claude_code_env() -> dict[str, str]:
    """Environment for Claude Code subscription-backed harness calls.

    Claude Code can authenticate with either Claude account auth or API-key
    auth. The harness `--cc` mode is intended to use Claude Code account auth,
    so do not let a repo/user shell `ANTHROPIC_API_KEY` silently switch the
    subprocess to API-key billing. Set HARNESS_CLAUDE_CODE_ALLOW_API_KEY=1 to
    opt back into inherited API-key auth explicitly.
    """
    env = os.environ.copy()
    if os.environ.get("HARNESS_CLAUDE_CODE_ALLOW_API_KEY") != "1":
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def _claude_code_compatible_schema(schema: Any) -> Any:
    """Return a Claude Code CLI-compatible JSON Schema copy.

    Claude Code's schema parser runs in strict mode and rejects union-type
    declarations (`{"type": ["string", "null"]}`). The harness still validates
    the returned JSON against the original schema after parsing; this copy only
    relaxes the schema passed to the CLI enough for structured output to run.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, list):
                # Preserve nullability hints in descriptions where useful, but
                # omit the strict type so values like bool/int/string are all
                # accepted by the CLI-side schema.
                continue
            out[key] = _claude_code_compatible_schema(value)
        return out
    if isinstance(schema, list):
        return [_claude_code_compatible_schema(item) for item in schema]
    return schema


def _extract_claude_structured_output(output: str) -> str:
    """Extract --json-schema output from Claude Code's JSON event wrapper."""
    data = json.loads(output)
    events = data if isinstance(data, list) else [data]

    for event in reversed(events):
        if isinstance(event, dict) and "structured_output" in event:
            return json.dumps(event["structured_output"], ensure_ascii=False)

    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        for item in message.get("content", []):
            if (
                isinstance(item, dict)
                and item.get("name") == "StructuredOutput"
                and "input" in item
            ):
                return json.dumps(item.get("input", {}), ensure_ascii=False)

    def find_structured(value: Any) -> Any:
        if isinstance(value, dict):
            if value.get("name") == "StructuredOutput" and "input" in value:
                return value["input"]
            if "structured_output" in value:
                return value["structured_output"]
            for child in value.values():
                found = find_structured(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find_structured(child)
                if found is not None:
                    return found
        return None

    found = find_structured(data)
    if found is not None:
        return json.dumps(found, ensure_ascii=False)

    raise RuntimeError(
        "Claude Code JSON result did not include structured output; "
        f"tail={output[-1000:]}"
    )


def _extract_json_by_braces(text: str, prefer_object: bool = False) -> Any:
    """Extract JSON by finding balanced braces/brackets.

    Strategy: try from the END first (actual JSON is usually after reasoning text),
    then fall back to searching from the start.
    """
    # Try finding the last top-level JSON object/array by scanning from end
    result = _try_extract_from_end(text, '{', '}')
    if result is not None:
        return result
    if not prefer_object:
        result = _try_extract_from_end(text, '[', ']')
        if result is not None:
            return result

    # Fallback: try from the start (handles case where response IS the JSON)
    result = _try_extract_from_start(text, prefer_object)
    if result is not None:
        return result

    raise json.JSONDecodeError("No valid JSON found in response", text[:200], 0)


def _try_extract_from_end(text: str, open_ch: str, close_ch: str) -> Any | None:
    """Find the outermost balanced JSON starting from the last close_ch."""
    # Find the last close_ch
    end_idx = text.rfind(close_ch)
    if end_idx < 0:
        return None

    # Walk backwards to find the matching open_ch
    depth = 0
    in_string = False
    i = end_idx
    while i >= 0:
        ch = text[i]
        # Check for escaped quote (look back for odd number of backslashes)
        if ch == '"':
            num_backslashes = 0
            j = i - 1
            while j >= 0 and text[j] == '\\':
                num_backslashes += 1
                j -= 1
            if num_backslashes % 2 == 0:
                in_string = not in_string
        elif not in_string:
            if ch == close_ch:
                depth += 1
            elif ch == open_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[i:end_idx + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
        i -= 1
    return None


def _try_extract_from_start(text: str, prefer_object: bool) -> Any | None:
    """Find the first balanced JSON from the start of text."""
    start_idx = -1
    if prefer_object:
        start_idx = text.find('{')
        if start_idx < 0:
            start_idx = text.find('[')
    else:
        for i, ch in enumerate(text):
            if ch in ('{', '['):
                start_idx = i
                break

    if start_idx < 0:
        return None

    open_ch = text[start_idx]
    close_ch = '}' if open_ch == '{' else ']'
    depth = 0
    in_string = False
    escape = False
    for i in range(start_idx, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start_idx:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _parse_json_from_response(text: str, prefer_object: bool = False) -> Any:
    """Extract JSON from LLM response, handling leading text, code blocks, and trailing text."""
    text = text.strip()
    if not text:
        raise json.JSONDecodeError("Empty response", "", 0)

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1
        if lines[-1].strip() == "```":
            end = -1
        text = "\n".join(lines[start:end]).strip()

    # Try normal parse first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find and extract JSON from anywhere in the response (handles leading text)
    return _extract_json_by_braces(text, prefer_object=prefer_object)


def _ingest_effort() -> str | None:
    """Reasoning effort for INGEST calls (bible/highlights extraction).

    Extraction needs no chain-of-thought; "none" verified ~20x cheaper on
    glm-5p1. HARNESS_INGEST_EFFORT: none (default) | low | off."""
    val = os.environ.get("HARNESS_INGEST_EFFORT", "none").strip().lower()
    return None if val in ("", "off") else val


def _structure_effort() -> str | None:
    """Reasoning effort for STRUCTURE calls (skeleton/expansion/graph-fix).

    Structure correctness is enforced by deterministic validators, so paying
    16k+ hidden reasoning tokens per call is waste. HARNESS_STRUCTURE_EFFORT:
    low (default) | none | off (= send nothing, full reasoning)."""
    val = os.environ.get("HARNESS_STRUCTURE_EFFORT", "low").strip().lower()
    return None if val in ("", "off") else val


def _call_json(
    system: str, user: str, params: Params, *, context: str,
    top_level: str = "object", schema: dict | None = None,
    structured: bool = True,
    reasoning_effort: str | None = None,
    cacheable: bool = True,
) -> Any:
    """Call the LLM for schema-validated JSON with bounded retries."""
    if structured and schema is None:
        raise ValueError(
            f"LLM JSON call '{context}' is missing a predefined schema"
        )
    schema = schema if structured else None
    prefer_obj = top_level == "object"
    last_response = ""
    for attempt in range(JSON_RETRY_ATTEMPTS):
        attempt_context = context if attempt == 0 else f"{context}_retry_{attempt + 1}"
        response = _call_llm(system, user, params, json_schema=schema,
                             reasoning_effort=reasoning_effort,
                             cacheable=cacheable)
        last_response = response
        _save_debug_response(attempt_context, response)
        data = _try_parse_json(response, prefer_obj, top_level, context)
        if data is not None:
            _normalize_json_value_fields(data)
            errors = _validate_json_schema(data, schema) if schema is not None else []
            if not errors:
                if attempt:
                    log.info(
                        "JSON/schema validation for %s succeeded on attempt %d/%d",
                        context, attempt + 1, JSON_RETRY_ATTEMPTS,
                    )
                return data
            log.warning(
                "Schema validation failed for %s attempt %d/%d: %s",
                context, attempt + 1, JSON_RETRY_ATTEMPTS, "; ".join(errors[:5]),
            )
        if attempt < JSON_RETRY_ATTEMPTS - 1:
            # A bad response must not be replayed from cache on the retry
            invalidate_cached_response(system, user, schema, reasoning_effort)
            log.warning(
                "JSON parse/schema validation failed for %s; retrying %d/%d",
                context, attempt + 2, JSON_RETRY_ATTEMPTS,
            )
    raise json.JSONDecodeError(
        f"JSON parse/schema validation failed for {context} after {JSON_RETRY_ATTEMPTS} attempts",
        last_response[:500],
        0,
    )


def _try_parse_json(
    response: str, prefer_obj: bool, top_level: str, context: str,
) -> Any | None:
    """Try to parse JSON from response. Returns None on failure."""
    try:
        data = _parse_json_from_response(response, prefer_object=prefer_obj)
        if top_level in ("object", "array") and not (
            (top_level == "object" and isinstance(data, dict)) or
            (top_level == "array" and isinstance(data, list))
        ):
            # If we got a list but expected object, try unwrapping single-element list
            if top_level == "object" and isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                return data[0]
            # If we got a dict but expected array, try common patterns
            if top_level == "array" and isinstance(data, dict):
                # Pattern 1: single violation object → wrap in list
                if "node" in data or "check" in data or "problem" in data:
                    return [data]
                # Pattern 2: dict wraps a list value
                for v in data.values():
                    if isinstance(v, list):
                        return v
            raise json.JSONDecodeError(
                f"Expected top-level {top_level}, got {type(data).__name__}",
                response,
                0,
            )
        return data
    except json.JSONDecodeError as e:
        log.warning("JSON parse attempt for %s: %s", context, e)
    return None


def _normalize_json_value_fields(data: Any) -> None:
    """Coerce common model over-structured scalar fact values in-place.

    Boundary schemas permit booleans, numbers, and strings for fact values.
    Claude sometimes returns a one-item list or small object for `initial` /
    `value` even when the semantic value is scalar. Keep validation strict for
    shape, but normalize these known scalar fields before schema checking.
    """
    if isinstance(data, dict):
        for key, value in list(data.items()):
            if key in {"initial", "value"} and isinstance(value, (list, dict)):
                data[key] = json.dumps(value, ensure_ascii=False)
            else:
                _normalize_json_value_fields(value)
    elif isinstance(data, list):
        for item in data:
            _normalize_json_value_fields(item)


def _validate_json_schema(data: Any, schema: dict | None, path: str = "$") -> list[str]:
    """Small JSON Schema subset validator for LLM boundary contracts."""
    if schema is None:
        return []
    errors: list[str] = []

    expected = schema.get("type")
    if expected is not None and not _schema_type_matches(data, expected):
        errors.append(f"{path}: expected {expected}, got {type(data).__name__}")
        return errors

    enum = schema.get("enum")
    if enum is not None and data not in enum:
        errors.append(f"{path}: value {data!r} not in enum {enum!r}")

    if isinstance(data, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required key {key!r}")
        for key, value in data.items():
            if key in props:
                errors.extend(_validate_json_schema(value, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected key {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(_validate_json_schema(
                    value, schema["additionalProperties"], f"{path}.{key}"
                ))

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items, got {len(data)}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: expected at most {schema['maxItems']} items, got {len(data)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(data):
                errors.extend(_validate_json_schema(item, item_schema, f"{path}[{i}]"))

    return errors


def _schema_type_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_schema_type_matches(value, e) for e in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if expected == "null":
        return value is None
    return True


def _save_debug_response(context: str, response: str) -> None:
    """Save raw LLM response to debug file for post-mortem analysis."""
    try:
        from .checkpoint import get_run_dir
        run_dir = get_run_dir()
        debug_dir = os.path.join(run_dir, "debug")
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        safe_ctx = context.replace("->", "_to_").replace(" ", "_")
        path = os.path.join(debug_dir, f"raw_{safe_ctx}.txt")
        # Append if file exists (multiple attempts for same context)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\nResponse ({len(response)} chars):\n")
            # Save first 2000 chars + last 3000 chars to capture both reasoning and JSON
            if len(response) > 8000:
                f.write(response[:2000])
                f.write(f"\n... ({len(response) - 5000} chars skipped) ...\n")
                f.write(response[-3000:])
            else:
                f.write(response)
            f.write("\n")
    except Exception:
        pass  # Debug save should never block execution


# ---------- §3.1 get_story_bible ----------

def get_story_bible(raw_novel: str, instruction: str, params: Params) -> dict:
    """§3.1 — Extract story bible from novel."""
    system = """You are a story analyst. Given a novel/story text and production instructions,
extract a structured story bible as JSON with these keys:

- "world": string describing the world/setting
- "characters": list of {name, role, description} where:
    - name: 角色名
    - role: 一句话身份（如"底层农家少年"、"深宫嫡女"）
    - description: 250-350字角色背景简介，第三人称档案卡风格。内容：出身、性格、处境、与其他角色的关系。不剧透结局。
- "setting": string describing time/place
- "opening_scene": the story's literal FIRST scene — WHERE/WHEN it opens, who is
  present, the inciting beat that starts the story, and which background facts
  (identity, world, looming crisis) surface naturally inside that scene. This is the
  TRUE START the root node must stage; do NOT describe a later crisis/climax here.
- "default_license": list of strings (things readers supply from genre/era/locale knowledge)
- "facts": list of {id, kind, gloss, initial, invariant} — every fact the interactive graph needs.
  Use prefixes: player.* (shown to player), char.<name>.* (character knows), world.* (objectively true).
  kind: "presence"|"possession"|"knowledge"|"event"|"disposition"|"location"|"relation"
  initial: the value at the story start (player.* default false, world.* as appropriate)
  invariant: true if this fact should NEVER change
- "protagonist_goals": 2-3 standing goals of the protagonist, list of {id, gloss}
  (e.g. {"id": "守护家人", "gloss": "..."}). The reference frame for choice dilemmas.

Return ONLY valid JSON, no markdown."""

    user = f"""## Production Instructions
{instruction}

## Story Text
{raw_novel}"""

    last_error = ""
    for attempt in range(JSON_RETRY_ATTEMPTS):
        data = _call_json(
            system, user, params,
            context="story bible" if attempt == 0 else f"story bible retry {attempt + 1}",
            schema=_STORY_BIBLE_SCHEMA,
            reasoning_effort=_ingest_effort(),
        )
        try:
            return _normalize_story_bible(data)
        except ValueError as e:
            last_error = str(e)
            log.warning("Story bible normalization failed: %s", last_error)
    raise ValueError(
        f"Story bible malformed after {JSON_RETRY_ATTEMPTS} normalization attempts: {last_error}"
    )


def get_story_bible_chunk(
    chunk_text: str,
    instruction: str,
    params: Params,
    *,
    chunk_label: str,
) -> dict:
    """Extract compact bible material from one Phase 1 chunk."""
    system = """You extract compact story-bible material from ONE source chunk.
Return ONLY a JSON object with:
- world: compact notes about the world visible in this chunk
- characters: characters actually present or important in this chunk
- setting: compact WHERE/WHEN notes visible in this chunk
- opening_scene: ONLY if this chunk contains the story's very first scene, describe
  it literally — WHERE/WHEN it opens, who is present, the inciting beat that kicks
  off the story, and which background facts (identity, world, looming crisis) surface
  naturally inside that scene. This is the TRUE START, not a later crisis. If this
  chunk is NOT the opening, return "" (empty string).
- default_license: genre/era assumptions readers can supply
- facts: durable facts needed by an interactive graph, using stable IDs
- protagonist_goals: 2-3 STANDING goals of the protagonist visible in this chunk
  (e.g. {"id": "守护家人", "gloss": "..."}). These become the reference frame for
  choice dilemmas — every choice option will be scored against them.

Rules:
- Do not summarize the whole novel unless this chunk provides that evidence.
- Prefer existing-looking fact ID prefixes: player.*, char.<name>.*, world.*.
- Facts must be useful for state checks, requirements, or choices.
- Keep output compact; do not pad counts."""

    user = f"""## Production Instructions
{instruction}

## Chunk
{chunk_label}

## Source Text
{chunk_text}"""

    data = _call_json(
        system, user, params,
        context=f"story bible chunk {chunk_label}",
        schema=_STORY_BIBLE_CHUNK_SCHEMA,
        reasoning_effort=_ingest_effort(),
    )
    return _normalize_story_bible_chunk(data)


def merge_story_bible_chunks(chunk_bibles: list[dict]) -> dict:
    """Deterministically merge compact chunk bibles into final bible shape."""
    character_by_name: dict[str, dict] = {}
    facts_by_id: dict[str, dict] = {}
    default_license: list[str] = []
    seen_license: set[str] = set()
    worlds: list[str] = []
    settings: list[str] = []
    # Opening scene anchors the root node; take it from the FIRST chunk that
    # carries one (chunk order is preserved → chunk 1 is the source opening).
    opening_scene = ""

    for bible in chunk_bibles:
        world = str(bible.get("world", "")).strip()
        setting = str(bible.get("setting", "")).strip()
        if not opening_scene:
            opening_scene = str(bible.get("opening_scene", "")).strip()
        if world and world not in worlds:
            worlds.append(world)
        if setting and setting not in settings:
            settings.append(setting)
        for item in bible.get("default_license", []) or []:
            text = str(item).strip()
            if text and text not in seen_license:
                default_license.append(text)
                seen_license.add(text)
        for char in bible.get("characters", []) or []:
            if not isinstance(char, dict):
                continue
            name = str(char.get("name", "")).strip()
            if not name:
                continue
            existing = character_by_name.get(name)
            if existing is None:
                character_by_name[name] = {
                    "name": name,
                    "role": str(char.get("role", "")).strip(),
                    "description": str(char.get("description", "")).strip(),
                }
            else:
                role = str(char.get("role", "")).strip()
                desc = str(char.get("description", "")).strip()
                if role and role not in existing["role"]:
                    existing["role"] = _join_compact(existing["role"], role, 80)
                if desc and desc not in existing["description"]:
                    existing["description"] = _join_compact(existing["description"], desc, 420)
        for fact in bible.get("facts", []) or []:
            if not isinstance(fact, dict):
                continue
            fid = str(fact.get("id", "")).strip()
            if not fid:
                continue
            if fid not in facts_by_id:
                facts_by_id[fid] = {
                    "id": fid,
                    "kind": str(fact.get("kind", "event")).strip() or "event",
                    "gloss": str(fact.get("gloss", "")).strip(),
                    "initial": fact.get("initial", False),
                    "invariant": bool(fact.get("invariant", False)),
                }

    goals_by_id: dict[str, dict] = {}
    for bible in chunk_bibles:
        for goal in bible.get("protagonist_goals", []) or []:
            if isinstance(goal, dict) and goal.get("id"):
                gid = str(goal["id"]).strip()
                if gid and gid not in goals_by_id:
                    goals_by_id[gid] = {"id": gid, "gloss": str(goal.get("gloss", "")).strip()}

    merged = {
        "world": _join_compact("", " / ".join(worlds), 1200),
        "characters": list(character_by_name.values()),
        "setting": _join_compact("", " / ".join(settings), 800),
        "opening_scene": opening_scene,
        "default_license": default_license,
        "facts": list(facts_by_id.values()),
        "protagonist_goals": list(goals_by_id.values())[:4],
    }
    return _normalize_story_bible(merged)


def _normalize_story_bible_chunk(data: dict) -> dict:
    """Normalize a single chunk bible without requiring global minimum counts."""
    if not isinstance(data, dict):
        raise ValueError(f"story bible chunk must be object, got {type(data).__name__}")
    normalized = dict(data)
    for key in ("characters", "facts", "default_license"):
        normalized[key] = _maybe_parse_json_string(normalized.get(key, []))
    if not isinstance(normalized.get("characters"), list):
        normalized["characters"] = []
    if not isinstance(normalized.get("facts"), list):
        normalized["facts"] = []
    if not isinstance(normalized.get("default_license"), list):
        normalized["default_license"] = []
    normalized["world"] = str(normalized.get("world", ""))
    normalized["setting"] = str(normalized.get("setting", ""))
    normalized["opening_scene"] = str(normalized.get("opening_scene", "") or "")
    return normalized


def _join_compact(existing: str, addition: str, limit: int) -> str:
    parts = [p for p in (existing.strip(), addition.strip()) if p]
    text = "；".join(parts)
    return text[:limit]


def _maybe_parse_json_string(value: Any) -> Any:
    """Parse fields that Claude sometimes returns as JSON-encoded strings."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return _parse_json_from_response(text)
        except Exception:
            return value


def _normalize_story_bible(data: dict) -> dict:
    """Normalize and validate story bible shape before checkpoint/export."""
    if not isinstance(data, dict):
        raise ValueError(f"story bible must be object, got {type(data).__name__}")
    if isinstance(data.get("bible"), dict):
        data = data["bible"]

    normalized = dict(data)
    for key in ("characters", "facts", "default_license"):
        normalized[key] = _maybe_parse_json_string(normalized.get(key, []))

    if isinstance(normalized.get("characters"), dict):
        chars_obj = normalized["characters"]
        for key in ("characters", "items", "list"):
            if isinstance(chars_obj.get(key), list):
                normalized["characters"] = chars_obj[key]
                break
    if isinstance(normalized.get("facts"), dict):
        facts_obj = normalized["facts"]
        for key in ("facts", "items", "list"):
            if isinstance(facts_obj.get(key), list):
                normalized["facts"] = facts_obj[key]
                break

    characters = [
        {
            "name": str(c.get("name", "")).strip(),
            "role": str(c.get("role", "")).strip(),
            "description": str(c.get("description", "")).strip(),
        }
        for c in (normalized.get("characters") or [])
        if isinstance(c, dict) and str(c.get("name", "")).strip()
    ]
    facts = [
        f for f in (normalized.get("facts") or [])
        if isinstance(f, dict) and f.get("id")
    ]
    default_license = normalized.get("default_license")
    if isinstance(default_license, str):
        default_license = [default_license]
    elif not isinstance(default_license, list):
        default_license = []

    if len(characters) < 3:
        raise ValueError(f"story bible has {len(characters)} valid characters; need at least 3")
    if len(facts) < 5:
        raise ValueError(f"story bible has {len(facts)} valid facts; need at least 5")

    normalized["world"] = str(normalized.get("world", ""))
    normalized["setting"] = str(normalized.get("setting", ""))
    normalized["opening_scene"] = str(normalized.get("opening_scene", ""))
    normalized["characters"] = characters
    normalized["facts"] = facts
    normalized["default_license"] = default_license
    return normalized


# ---------- §3.3 get_highlights ----------

def get_highlights(raw_novel: str, instruction: str, params: Params) -> list[Highlight]:
    """§3.3 — Extract weighted highlights from the novel."""
    system = """Identify the major events/beats worth preserving in an interactive adaptation.
Return a JSON object: {"highlights": [{"id": "h1", "chapter": 1, "weight": 0.9, "gloss": "description", "satisfaction_type": "打脸", "hook_type": ""}, ...]}
Return 8-16 highlights, not more.
weight: 0.0-1.0, how important this beat is to the story.
TYPE every beat: satisfaction_type (爽点: 打脸|身份揭露|逆袭|反杀|护短|夺宝|隐藏实力, else "")
and hook_type (钩子: 悬念|危机|情感|反转, else "").
Return ONLY valid JSON."""

    user = f"""## Instructions
{instruction}

## Story
{raw_novel}"""

    data = _call_json(
        system, user, params,
        context="highlights", schema=_HIGHLIGHTS_OBJECT_SCHEMA,
        reasoning_effort=_ingest_effort(),
    )
    highlights = data.get("highlights", [])
    return [Highlight(id=h["id"], chapter=h["chapter"], weight=h["weight"], gloss=h["gloss"],
                      satisfaction_type=str(h.get("satisfaction_type", "") or ""),
                      hook_type=str(h.get("hook_type", "") or ""))
            for h in highlights]


def get_highlights_chunk(
    chunk_text: str,
    instruction: str,
    params: Params,
    *,
    chunk_label: str,
    chapter_start: int,
    chapter_end: int,
) -> list[Highlight]:
    """Extract weighted highlights from one Phase 1 chunk."""
    system = """Identify the strongest adaptation beats in ONE source chunk.
Return a JSON object: {"highlights": [{"id": "h1", "chapter": 1, "weight": 0.9, "gloss": "description", "satisfaction_type": "打脸", "hook_type": ""}, ...]}
Return 5-12 highlights. Use chapter numbers inside the provided chapter range.
weight: 0.0-1.0, how important this beat is to the full interactive adaptation.
TYPE every beat (this drives drama placement downstream):
- satisfaction_type if it is a 爽点 payoff: 打脸|身份揭露|逆袭|反杀|护短|夺宝|隐藏实力 (else "")
- hook_type if it creates forward pull: 悬念|危机|情感|反转 (else "")
Return ONLY valid JSON."""

    user = f"""## Instructions
{instruction}

## Chunk
{chunk_label}
Chapter range: {chapter_start}-{chapter_end}

## Story
{chunk_text}"""

    data = _call_json(
        system, user, params,
        context=f"highlights chunk {chunk_label}",
        schema=_HIGHLIGHTS_OBJECT_SCHEMA,
        reasoning_effort=_ingest_effort(),
    )
    highlights = data.get("highlights", [])
    return [
        Highlight(
            id=str(h["id"]),
            chapter=int(h["chapter"]),
            weight=float(h["weight"]),
            gloss=str(h["gloss"]),
            satisfaction_type=str(h.get("satisfaction_type", "") or ""),
            hook_type=str(h.get("hook_type", "") or ""),
        )
        for h in highlights
    ]


# ---------- P1: outline plan ----------

def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if '一' <= ch <= '鿿')
    return cjk / max(1, len("".join(text.split())))


def _score_outline(data: dict, highlights: list[Highlight]) -> float:
    """Deterministic outline quality score for k-candidate selection."""
    score = 0.0
    # Language rule: all output values must be Chinese — heavily penalize
    # anglicized candidates (they propagate into every downstream artifact).
    lang_sample = (str(data.get("main_dramatic_question", "")) + "".join(
        str(s.get("dramatic_question", "")) + str(s.get("bottleneck_gloss", ""))
        for s in data.get("sequences", [])
    ))
    if _cjk_ratio(lang_sample) < 0.5:
        score -= 100.0
    seqs = data.get("sequences", [])
    if 4 <= len(seqs) <= 8:
        score += 10
    # Distinct sequence questions, all different from the main question
    main_q = data.get("main_dramatic_question", "")
    qs = [s.get("dramatic_question", "") for s in seqs]
    score += 2 * len({q for q in qs if q and q != main_q})
    # 爽点 coverage: how much top-weight highlight mass got scheduled
    assigned = {hid for s in seqs for hid in (s.get("satisfaction_beats") or [])}
    top = sorted(highlights, key=lambda h: -h.weight)[:12]
    score += 4 * sum(h.weight for h in top if h.id in assigned)
    # Ledger richness (capped) + bracket sanity
    ledger = data.get("ledger", [])
    score += min(len(ledger), 8)
    seq_ids = {s.get("id") for s in seqs}
    score += sum(1 for e in ledger
                 if e.get("plant_sequence") in seq_ids
                 and e.get("close_sequence") in seq_ids)
    # Player stats: 2-4 axes is right
    n_stats = len(data.get("player_stats", []))
    if 2 <= n_stats <= 4:
        score += 5
    return score


def generate_outline(
    bible: dict, highlights: list[Highlight], params: Params,
    chapter_bounds: tuple[int, int], k: int = 2,
) -> dict:
    """P1 — sequence outline + ledger plants + 爽点 schedule + player stats.

    Generates k candidates in parallel, picks the best by deterministic score.
    Everything downstream realizes THIS artifact; it is the highest-leverage
    LLM call in the pipeline, hence full reasoning + candidate selection.
    """
    from concurrent.futures import ThreadPoolExecutor

    min_ch, max_ch = chapter_bounds
    hl_desc = json.dumps(
        [{"id": h.id, "chapter": h.chapter, "weight": h.weight,
          "satisfaction_type": h.satisfaction_type, "hook_type": h.hook_type,
          "gloss": h.gloss}
         for h in highlights],
        ensure_ascii=False, indent=1,
    )
    goals_desc = json.dumps(bible.get("protagonist_goals", []), ensure_ascii=False)

    system = f"""You are the story architect. Design the SEQUENCE OUTLINE for a
{params.target_playthrough_min:.0f}-minute interactive film adapted from the source below.
This outline is the single source of truth for everything generated afterwards.
所有输出的文字值（问题、gloss、标题、low/high_effect 等）必须是中文；JSON 键保持英文。

## Output (JSON only)
- main_dramatic_question: the audience-level question that unifies the whole film
- sequences: 5-7 sequences (Gulino units, ~8-15 min each). Each has:
  - id "A".."H", function in order: hook → lock_in → first_attempt → midpoint →
    complication → main_culmination → crisis_finale (merge/omit to fit count)
  - span_pct [start, end] — lock_in ends ~0.25, midpoint ~0.5, main_culmination 0.65-0.85
  - dramatic_question: the LOCAL question this sequence runs on (≠ main question;
    posed at its start, answered at its bottleneck, the answer raising the next question)
  - bottleneck_gloss: the convergence scene ending the sequence (one line)
  - satisfaction_beats: highlight ids scheduled INTO this sequence. Place the two
    biggest reveals near the 15% and 40% marks. Every 爽点 must pay off ≤5 min after
    its 压抑 setup.
  - chapters: [start,end] within {min_ch}-{max_ch}
- ledger: 4-8 narrative obligations to plant and pay off:
  kinds: question (dramatic questions incl. the main one), setup (Chekhov items),
  dangling_cause (threats/promises), irony (audience-knows-character-doesn't:
  these need a revelation AND a later recognition), motif. Each entry says WHERE
  planted (plant_sequence) and WHERE closed (close_sequence).
- player_stats: 2-4 axes the player's choices accumulate into (player.* ids),
  with low_effect/high_effect describing how endings/scenes read differently.

## Craft rules
- The main question is IMMUTABLE across branches; only stakes and flavor differ.
- main_culmination ANSWERS the main question (well or badly) and a NEW final-act
  tension takes over — do not save the answer for the very end.
- Schedule 爽点 by type: {{"打脸","身份揭露","逆袭","反杀","护短"}} are payoffs the
  player must TRIGGER, not watch.

## Protagonist goals (dilemma reference frame)
{goals_desc}

## Typed highlights (schedule these)
{hl_desc}"""

    user = f"""## Bible (compact)
{json.dumps(_compact_bible(bible), ensure_ascii=False, indent=1)}

Design the outline. Return ONLY JSON."""

    def _one(i: int) -> dict | None:
        try:
            return _call_json(
                system, user + f"\n(candidate {i + 1})", params,
                context=f"outline candidate {i + 1}", schema=_OUTLINE_SCHEMA,
            )
        except Exception:
            log.exception("Outline candidate %d failed", i + 1)
            return None

    if k <= 1:
        candidates = [_one(0)]
    else:
        with ThreadPoolExecutor(max_workers=k) as pool:
            candidates = list(pool.map(_one, range(k)))
    scored = [(c, _score_outline(c, highlights)) for c in candidates if c]
    if not scored:
        raise HarnessError("All outline candidates failed")
    scored.sort(key=lambda x: -x[1])
    for i, (c, s) in enumerate(scored):
        log.info("  Outline candidate scores: #%d = %.1f (%d sequences, %d ledger)",
                 i + 1, s, len(c.get("sequences", [])), len(c.get("ledger", [])))
    best = scored[0][0]
    return best


# ---------- §3.5 get_cornerstone_nodes ----------

def _compact_registry(registry: Registry) -> str:
    """Compact registry format: one line per fact to reduce token count."""
    lines = []
    for fid, d in registry.items():
        inv = ",inv" if d.invariant else ""
        lines.append(f"  {fid}: {d.kind}, init={d.initial}{inv} — {d.gloss}")
    return "\n".join(lines)


def _compact_bible(bible: dict) -> dict:
    """Keep generation prompts focused without dropping story grounding."""
    facts = bible.get("facts", [])
    return {
        "world": str(bible.get("world", "")),
        "setting": str(bible.get("setting", "")),
        "characters": [
            {
                "name": c.get("name", ""),
                "role": c.get("role", ""),
                "description": str(c.get("description", "")),
            }
            for c in bible.get("characters", [])
            if isinstance(c, dict)
        ],
        "fact_ids": [
            f.get("id", "")
            for f in facts
            if isinstance(f, dict) and f.get("id")
        ],
    }


def generate_mini_story(
    bible: dict, registry: Registry, params: Params,
    chapters_index: dict[int, str] | None = None,
    chapter_bounds: tuple[int, int] | None = None,
) -> tuple[Graph, list[FactDecl]]:
    """Minimal complete interactive unit: 1 root choice node → 2 different ENDINGs.

    Reuses the cornerstone node format + CHOICE_DESIGN digest (so prompt tuning
    transfers to full runs), grounded directly in the opening chapters' text.
    Returns (graph, new_fact_declarations). One LLM call.
    """
    facts_desc = _compact_registry(registry)
    min_ch, max_ch = chapter_bounds or (1, 2)
    goal_ids = [g.get("id") for g in bible.get("protagonist_goals", []) if g.get("id")]

    # Ground in the actual opening chapter text (truncated to fit).
    src = ""
    if chapters_index:
        parts = [chapters_index.get(c, "") for c in range(min_ch, max_ch + 1)]
        src = "\n\n".join(p for p in parts if p)[:7000]

    opening_scene = (bible.get("opening_scene", "") or "").strip()
    opening_block = (
        f"\n## 必须演出的开场（root 从这里开始，WHERE/WHEN/引子事件）\n{opening_scene}\n"
        if opening_scene else ""
    )

    system = f"""你为一部互动剧设计一个**最小完整单元**：恰好 3 个节点。
- 1 个开场选择节点（kind="prologue", ending="NONE"）：**演出原著字面意义上的第一场戏**（故事真正的起点），升温到张力顶点，抛出一个两难。
- 2 个结局节点（ending="ENDING"）：分别是开场那个选择两个选项的不同结局。
开场节点的 2 个选项各通向一个**不同**的结局（真正的分叉，竞争性收益）：选项A→e1，选项B→e2。

**开场锚定（强制）**：root 必须停在原著字面开头那一场。圣经的 setting/goals 描述的是后续才到达的高潮/危机——**不要**让它们把 root 拉到那个危机。背景（身份、世界观、危机）要靠开场这一场的现场动作与对白自然带出，不能跳到后段再用旁白补叙。

## 选择质量
{_CHOICE_DESIGN_DIGEST}

## 规则
- root：kind="prologue"，question ≤30字，恰好 2 个选项分别指向 e1 和 e2，每个选项 state_delta 写一个不同的 player.* 事实（在 new_facts 声明），resolution 两个短句。
- 结局：ending="ENDING"，question=null，choices=[]，最后一个 skeleton 节拍是 {{"type":"narration","text":"结局：结局名"}}。
- skeleton：5-8 个节拍，第一个必须是 scene_header。**skeleton 节拍是剧情的唯一载体**，必须自带全部细节（出场人物、按序事件、对白要点、关键物件、转折）——没有单独的 summary 字段。entry_context/exit_context 必填。planned_duration_min 在 2.0-3.0。
- 主角目标（竞争性收益用）：{json.dumps(goal_ids, ensure_ascii=False)}；两个选项偏向不同目标。
- 只用注册表里的 fact ID 或在 new_facts 声明新 ID。DAG，无环。
- 文本字段内禁止英文双引号，用「」。

## 注册表
{facts_desc}

只返回 JSON：{{"root":"n1","new_facts":[...],"nodes":{{"n1":{{...}},"e1":{{...}},"e2":{{...}}}}}}
节点字段同骨架格式：id,kind,planned_duration_min,chapters,covers,skeleton,entry_context,exit_context,produces,requires,entry_invariants,ending,question,choices。"""

    user = f"""## 原著开场（第 {min_ch}-{max_ch} 章）
{src}
{opening_block}
## 故事圣经
{json.dumps(_compact_bible(bible), ensure_ascii=False, indent=1)}

产出恰好 3 个节点：1 个开场选择节点 + 2 个不同结局，遵守上面的规则。chapters 值不得超出 {min_ch}-{max_ch}。root 必须演出上面「必须演出的开场」那一场。"""

    log.info("  Mini-story: generating 3-node skeleton...")
    data = _call_json(system, user, params, context="mini_story",
                      schema=_SKELETON_CORNERSTONE_SCHEMA,
                      reasoning_effort=_structure_effort())
    new_decls = _parse_new_facts(data.get("new_facts", []))
    graph = _parse_graph(data)
    log.info("  Mini-story skeleton: %d nodes, %d new facts", len(graph.nodes), len(new_decls))
    return graph, new_decls


def get_cornerstone_nodes(
    bible: dict, registry: Registry, params: Params,
    chapter_bounds: tuple[int, int] | None = None,
    outline: dict | None = None,
) -> tuple[Graph, list[FactDecl]]:
    """P2 — Generate the trunk skeleton graph realizing the P1 outline.

    Returns (graph, new_fact_declarations).
    Polished prose is filled separately in Phase 4 via fill_prose().
    """
    facts_desc = _compact_registry(registry)
    if chapter_bounds:
        min_ch, max_ch = chapter_bounds
    else:
        min_ch, max_ch = 1, 10

    outline_section = ""
    if outline:
        outline_section = f"""

## THE OUTLINE (P1 — realize it, do not redesign it)
Main dramatic question: {outline.get('main_dramatic_question', '')}
Sequences (one trunk bottleneck per sequence, in order; set node.sequence and
node.arc_slot accordingly; cover each sequence's chapters; its bottleneck_gloss
is that bottleneck node's plot; pay off its satisfaction_beats inside the sequence):
{json.dumps(outline.get('sequences', []), ensure_ascii=False, indent=1)}

Ledger obligations (plant/close in the named sequences — put the plant/close
events into the corresponding nodes' skeleton beats and summaries).
LEDGER FACTS: the node that PLAYS a plant must `produces` its fact_id (with a
beat anchor); any later node that REFERENCES the obligation must declare its
fact_id in `requires`. Declare these fact_ids in new_facts. This makes
plant-before-reference machine-checkable (D1):
{json.dumps(outline.get('ledger', []), ensure_ascii=False, indent=1)}

Player stat axes (each choice's state_delta writes one of these; declare them
in new_facts if not in the registry):
{json.dumps(outline.get('player_stats', []), ensure_ascii=False, indent=1)}

OUTPUT BUDGET — keep the trunk LEAN (the response must fit; a truncated trunk
is worthless):
- Each node: "sequence" (A-H letter) is REQUIRED; skeleton ≤6 beats (the beats are the sole plot record — no separate summary field).
- Do NOT emit: value/opening_charge/closing_charge/turning_type/tension/
  expectation/result/arc_slot/cost/goal_impacts — a dedicated metadata pass
  fills these afterwards. Emit ONLY structure, plot, choices (with state_delta),
  produces/requires, contexts.
- The protagonist goals for later dilemma checks are {json.dumps([g.get('id') for g in bible.get('protagonist_goals', [])], ensure_ascii=False)}; design each
  choice pair so the two options favor DIFFERENT goals (the metadata pass will
  score them)."""

    system_a = f"""Design the TRUNK of an interactive story graph. Return STRUCTURE + SUMMARY + THIN CONTENT.

## Trunk architecture (MANDATORY SHAPE — branch-and-bottleneck)
The trunk is the main storyline every player experiences. Side branches are added
LATER by expansion; your job is a strong convergent spine:

- Output 1 prologue (root) + 3-4 trunk bottleneck nodes (kind="bottleneck") + at least {params.min_ending_count} ENDING node(s). NO DEAD_END nodes at trunk stage.
- TRUNK CHAIN RULE: the prologue and every non-final bottleneck has EXACTLY 2 choices, and BOTH choices point to the SAME next trunk node. The two choices MUST differ in "state_delta" (each writes different player-state facts) and in "resolution". The choice writes STATE, not a fork — forks are added later by expansion.
- The FINAL bottleneck's choices point to DIFFERENT ENDING nodes — 2 or 3 choices (3-way ending splits are allowed ONLY here, where every target is an ENDING).
- Trunk dramatic functions, in order (assign one per bottleneck):
  1. 锁定困局 lock-in (~25% mark): protagonist commits; the main dramatic question is posed and cannot be walked back.
  2. 中点反转 midpoint reversal (~50%): stakes raised hard — the threat turns personal or bigger; trajectory flips.
  3. 主问题揭晓 main culmination (~75%): the main question is ANSWERED (well or badly) and a NEW final-act tension takes over.
  4. 终极抉择 crisis (final bottleneck): true dilemma at maximum pressure — choice between irreconcilable goods or lesser of two evils; each option's cost is explicit and irreversible.
- Spread trunk nodes across chapters {min_ch}-{max_ch}: early / middle / late. The climax of the source story belongs in the LAST trunk node, played as a scene — never summarized away.
- THE PROLOGUE PLAYS THE SOURCE OPENING: the root node stages the original
  story's opening scene(s) from chapter {min_ch} — its setting, its inciting
  events, PLAYED as happening now. Foundation (world, identity, stakes) is laid
  there; do NOT relocate it to a later timeframe and narrate the opening as
  backstory.
  THE OPENING SCENE TO STAGE (root must open HERE — its WHERE/WHEN/inciting beat):
  {bible.get('opening_scene', '') or '（圣经未提供，以第 ' + str(min_ch) + ' 章正文开头为准）'}
  IMPORTANT: the bible's `setting` and `protagonist_goals` describe the LATER arc
  (the crisis the story builds toward) — do NOT let them pull the root's WHERE/WHEN
  to that crisis. The root stages the opening_scene above; background (identity,
  world, stakes) must surface through the opening's own live action and dialogue,
  not be summarized as a later situation.
- GLOSS IS PLAYED, NOT REMEMBERED: each sequence's bottleneck_gloss events must
  appear as live beats in that bottleneck node (正在发生的场景), never compressed
  into recollection/narration.
- Stage every scene WHERE AND WHEN the source stages it — the chapters carry
  the location/time signals; follow them. Location changes between nodes are
  free (write the cut).

## Choice quality (EVERY choice, trunk included)
{_CHOICE_DESIGN_DIGEST}

Additional trunk rules:
- "question" ≤30 Chinese chars
- CHOICE TIMING: the question must be FORCED by the node's final 1-2 beats — a surprise, reversal, or ultimatum at the tension peak (role: decision_trigger).
- "state_delta": 1-2 effects per choice. Declare new player.* facts in new_facts; never reference them in later requires/label_requires.
- Each choice MUST have: "label" (≤8 Chinese chars), "to", "resolution" (exactly 2 short beats)

## General rules
- Endings: ending="ENDING", no choices, no question
- DAG only — no cycles, no back-edges
- chapters: [start, end] — two-element array; EVERY node.chapters value MUST stay inside {min_ch}-{max_ch}
- kind: "prologue"|"scene"|"bottleneck"|"ending"
- entry_context / exit_context: WHERE·WHEN strings (REQUIRED for every node)
- planned_duration_min: expected final scene/prose shooting duration in minutes. Non-DEAD_END nodes MUST be 2.0-5.0.
- Output "skeleton" ONLY (5-8 structured beats: scene_header first, then core actions/dialogue meaning). Do NOT output a "content" field — prose is generated later from the skeleton.
- The "skeleton" beats ARE the sole plot record (there is NO separate summary field). Across the beats you MUST capture: characters present, key events in order, dialogue beats (who says what to whom), items/evidence, emotional turns. Every plot element must live in a skeleton beat.
- Keep produces/requires minimal. Do not add a requirement unless the node truly presupposes prior state.

## Fact rules — CRITICAL
- ONLY use fact IDs from the Registry below, OR declare new ones in "new_facts"
- NEVER set an invariant fact to a different value than its initial
- Do NOT use fact IDs not listed below without declaring them

## Registry (id: kind, init=value[,inv] — description)
{facts_desc}

Return ONLY valid JSON matching this EXACT schema:
{{{{
  "root": "n1",
  "new_facts": [{{{{"id": "player.x", "kind": "event", "gloss": "desc", "initial": false, "invariant": false}}}}],
  "nodes": {{{{
    "n1": {{{{
      "id": "n1", "kind": "prologue", "planned_duration_min": 2.5, "chapters": [1, 2], "covers": [],
      "skeleton": [
        {{"type": "scene_header", "location": "地点", "time": "时间", "characters": ["角色"]}},
        {{"type": "action", "text": "核心剧情动作节拍"}},
        {{"type": "dialogue", "speaker": "角色", "line": "关键对白意思"}}
      ],
      "entry_context": "地点·时间", "exit_context": "地点·时间",
      "produces": [{{{{"fact": "player.x", "value": true}}}}],
      "requires": [], "entry_invariants": [],
      "ending": "NONE",
      "question": "角色的内心两难",
      "choices": [
        {{{{"label": "动作A", "to": "t1", "resolution": ["结果1", "结果2"],
           "state_delta": [{{{{"fact": "player.trait_a", "value": true}}}}]}}}},
        {{{{"label": "动作B", "to": "t1", "resolution": ["结果1", "结果2"],
           "state_delta": [{{{{"fact": "player.trait_b", "value": true}}}}]}}}}
      ]
    }}}},
    "n2": {{{{
      "id": "n2", "kind": "ending", "planned_duration_min": 2.0, "chapters": [2, 3], "covers": [],
      "skeleton": [
        {{"type": "scene_header", "location": "地点", "time": "时间", "characters": ["角色A", "角色B"]}},
        {{"type": "action", "text": "结局核心动作"}},
        {{"type": "narration", "text": "结局：结局名称"}}
      ],
      "entry_context": "地点·时间", "exit_context": "地点·时间",
      "produces": [], "requires": [], "entry_invariants": [],
      "ending": "ENDING", "question": null, "choices": []
    }}}}
  }}}}
}}}}"""

    editor_section = ""
    if params.editor_notes:
        editor_section = f"""

## Editor's Notes (MUST follow)
{params.editor_notes}
"""

    user_a = f"""## Source Chapter Bounds
Available chapters: {min_ch}-{max_ch}. Do not output any node.chapters value outside this range.

## Bible
{json.dumps(bible, ensure_ascii=False, indent=2)}
{editor_section}{outline_section}
Create the TRUNK graph SKELETON: prologue → bottleneck chain (both choices of each non-final node to the SAME next node with different state_delta) → final bottleneck forking to ENDINGs. Each node's "skeleton" beats are the sole plot record and must be DETAILED (characters, events in order, dialogue beats, items, turning points) — there is NO separate summary field. Output "skeleton" beats only — NO "content" field. You MUST include at least {params.min_ending_count} ENDING nodes (ending="ENDING"). NO DEAD_END nodes."""

    log.info("  Cornerstone: generating skeleton...")
    data_a = _call_json(system_a, user_a, params, context="cornerstone skeleton",
                        schema=_SKELETON_CORNERSTONE_SCHEMA,
                        reasoning_effort=_structure_effort())

    # Parse new_facts
    new_decls = _parse_new_facts(data_a.get("new_facts", []))

    graph = _parse_graph(data_a)
    log.info(f"  Cornerstone skeleton: {len(graph.nodes)} nodes, {len(new_decls)} new facts")

    # Collapse guard: a trunk below the minimum plausible size means the
    # response degenerated (reasoning ate the budget / JSON tail collapsed).
    # Regenerate fresh instead of letting stabilize flail on a stump.
    min_trunk = 2 + params.min_ending_count  # prologue + ≥1 bottleneck + endings
    for _regen in range(3):
        if len(graph.nodes) >= min_trunk:
            break
        log.warning("  Cornerstone collapsed to %d nodes (<%d) — regenerating (%d/3)",
                    len(graph.nodes), min_trunk, _regen + 1)
        invalidate_cached_response(system_a, user_a, _SKELETON_CORNERSTONE_SCHEMA,
                                   _structure_effort())
        data_a = _call_json(system_a, user_a, params, context="cornerstone skeleton",
                            schema=_SKELETON_CORNERSTONE_SCHEMA,
                            reasoning_effort=_structure_effort())
        new_decls = _parse_new_facts(data_a.get("new_facts", []))
        graph = _parse_graph(data_a)
        log.info(f"  Cornerstone regen: {len(graph.nodes)} nodes")

    # ── Verify skeleton structure ──
    # Register new facts temporarily for validation
    temp_registry = dict(registry)
    for decl in new_decls:
        temp_registry[decl.id] = decl

    from .guaranteed import compute_guaranteed
    from .validation import validate_deterministic

    try:
        graph.topo_order()
    except ValueError:
        log.warning("  Cornerstone: cycle detected, breaking")
        from .harness import _break_cycles
        _break_cycles(graph)

    compute_guaranteed(graph, temp_registry)
    from .validation import validate_trunk_shape
    violations = validate_deterministic(graph, temp_registry, require_content=False,
                                        min_ending_count=params.min_ending_count)
    violations.extend(validate_trunk_shape(graph, params.min_ending_count))
    if violations:
        log.info(f"  Cornerstone: {len(violations)} violations, requesting fix...")
        violations_json = [
            {"node": v.node, "check": v.check, "problem": v.problem,
             "suggested_fix": v.suggested_fix}
            for v in violations
        ]
        fix_system = f"""Fix the violations in this interactive story graph SKELETON.
Return the COMPLETE fixed graph in the same JSON format.

## CRITICAL FORMAT RULES
- Output "skeleton" beats for ALL nodes (scene_header plus core plot actions/dialogue); no "content" field
- "planned_duration_min" MUST be present for ALL nodes and reflect intended final prose/shooting length
- "skeleton" beats are the sole plot record for each node (no separate summary field)
- Every non-ending node MUST have "question" and EXACTLY 2 "choices"
- Each choice format: {{"label": "动作", "to": "target_node_id", "resolution": ["结果1", "结果2"]}}
- "label" must be player action (≤8 chars), "to" must be a valid node ID
- Endings (ending="ENDING" or "DEAD_END"): question=null, choices=[]
- kind must be: "prologue"|"scene"|"bottleneck"|"ending"
- Every node MUST have entry_context and exit_context (WHERE·WHEN strings)

## Violations
{json.dumps(violations_json, ensure_ascii=False, indent=2)}

## Registry
{facts_desc}

Return ONLY valid JSON with root, new_facts, and nodes."""

        fix_user = f"Current graph:\n{json.dumps(data_a, ensure_ascii=False, indent=2)}"

        for _fix_attempt in range(JSON_RETRY_ATTEMPTS):
            data_fixed = _call_json(
                fix_system, fix_user, params,
                context="cornerstone skeleton fix", cacheable=False, schema=_SKELETON_CORNERSTONE_SCHEMA,
                reasoning_effort=_structure_effort(),
            )
            if "root" in data_fixed and "nodes" in data_fixed:
                break
            log.warning(
                "  Cornerstone fix returned incomplete data (attempt %d/%d), retrying",
                _fix_attempt + 1, JSON_RETRY_ATTEMPTS,
            )
        graph = _parse_graph(data_fixed)

        # Re-parse new_facts from fixed response
        new_decls = _parse_new_facts(data_fixed.get("new_facts", []))
        log.info(f"  Cornerstone fix: {len(graph.nodes)} nodes")

    # Preserve thin content. Phase 4 expands it; it is not discarded.

    return graph, new_decls


def _parse_chapters_field(raw) -> tuple[int, int]:
    """Robustly parse a chapters field into a (start, end) tuple."""
    if isinstance(raw, (list, tuple)):
        if len(raw) >= 2:
            return (int(raw[0]), int(raw[1]))
        elif len(raw) == 1:
            return (int(raw[0]), int(raw[0]))
    elif isinstance(raw, int):
        return (raw, raw)
    return (0, 0)


def _parse_requirement(r) -> Requirement | None:
    """Robustly parse a requirement from various LLM formats."""
    if isinstance(r, dict) and "fact" in r:
        return Requirement(fact=r["fact"], value=r.get("value", True))
    if isinstance(r, str):
        return Requirement(fact=r, value=True)
    return None


def _parse_requirements(raw) -> list[Requirement]:
    """Parse a list of requirements, tolerating mixed formats."""
    if not raw or not isinstance(raw, list):
        return []
    return [req for r in raw if (req := _parse_requirement(r)) is not None]


def _parse_effect(e) -> Effect | None:
    if isinstance(e, dict) and "fact" in e:
        return Effect(fact=e["fact"], value=e.get("value", True), beat=e.get("beat", ""))
    if isinstance(e, str):
        return Effect(fact=e, value=True, beat="")
    return None


def _parse_effects(raw) -> list[Effect]:
    """Parse a list of effects, tolerating mixed formats."""
    if not raw or not isinstance(raw, list):
        return []
    return [eff for e in raw if (eff := _parse_effect(e)) is not None]


def _canonical_goal_key(key: str) -> str:
    """Normalize goal aliases used by model outputs.

    The bible carries both the canonical survival goal id and a prose-label
    alias. Keep structured outputs on the canonical id so downstream validators
    do not see semantically duplicate keys.
    """
    if key == "活下来度过今夜":
        return "goal.survive"
    return key


def _parse_node(nid: str, nd: dict) -> Node:
    """Robustly parse a node dict into a Node object."""
    choices = []
    for c in nd.get("choices", []):
        if isinstance(c, dict) and ("to" in c or "label" in c or "next" in c or "text" in c):
            resolution = c.get("resolution", [])
            if isinstance(resolution, str):
                resolution = [resolution]
            raw_impacts = c.get("goal_impacts", {})
            goal_impacts = {}
            if isinstance(raw_impacts, dict):
                for k, v in raw_impacts.items():
                    k = _canonical_goal_key(str(k))
                    try:
                        f = float(v)
                    except (TypeError, ValueError):
                        continue
                    # Normalize to sign ints; drop zero-impact entries
                    if f > 0:
                        goal_impacts[str(k)] = 1
                    elif f < 0:
                        goal_impacts[str(k)] = -1
            choices.append(Choice(
                label=c.get("label", c.get("text", "")),
                label_requires=_parse_requirements(c.get("label_requires", [])),
                to=c.get("to", c.get("target", c.get("dst", c.get("next", "")))),
                resolution=resolution if isinstance(resolution, list) else [],
                state_delta=_parse_effects(c.get("state_delta", [])),
                cost=str(c.get("cost", "") or ""),
                goal_impacts=goal_impacts,
            ))

    kind = nd.get("kind", "scene")
    if kind not in ("prologue", "scene", "bottleneck", "ending"):
        # Any unknown/alias kind (e.g. "normal") maps to a plain scene.
        kind = "scene"

    raw_content = nd.get("content", [])
    raw_skeleton = nd.get("skeleton", [])
    skeleton_list: list[dict] = []
    content_list: list[dict] = []

    if isinstance(raw_skeleton, list) and raw_skeleton:
        from .models import make_action
        for el in raw_skeleton:
            if isinstance(el, dict) and "type" in el:
                skeleton_list.append(el)
            elif isinstance(el, str) and el.strip():
                skeleton_list.append(make_action(el.strip()))
    elif isinstance(raw_skeleton, str) and raw_skeleton.strip():
        from .models import _parse_prose_to_elements, make_scene_header
        skeleton_list = [make_scene_header("", "", [])] + _parse_prose_to_elements(raw_skeleton)

    if isinstance(raw_content, list) and raw_content:
        from .models import make_action
        for el in raw_content:
            if isinstance(el, dict) and "type" in el:
                content_list.append(el)
            elif isinstance(el, str) and el.strip():
                content_list.append(make_action(el.strip()))
    elif isinstance(raw_content, str) and raw_content.strip():
        from .models import _parse_prose_to_elements, make_scene_header
        content_list = [make_scene_header("", "", [])] + _parse_prose_to_elements(raw_content)

    # Legacy fallback: content but no skeleton → migrate content to skeleton
    if not skeleton_list and content_list:
        skeleton_list = list(content_list)
    # Legacy: summary but no skeleton → migrate summary to skeleton
    if not skeleton_list and nd.get("summary", ""):
        from .models import _parse_prose_to_elements, make_scene_header
        skeleton_list = [make_scene_header(
            nd.get("entry_context", "").split("·")[0] if nd.get("entry_context") else "",
            "", [],
        )] + _parse_prose_to_elements(nd.get("summary", ""))
    if not content_list and nd.get("prose", ""):
        from .models import _parse_prose_to_elements, make_scene_header
        scene_chars = nd.get("scene_characters", [])
        if isinstance(scene_chars, str):
            import re as _re
            scene_chars = [c.strip() for c in _re.split(r"[、,，]", scene_chars) if c.strip()]
        content_list = [make_scene_header(
            nd.get("scene_location", ""),
            nd.get("scene_time", ""),
            scene_chars if isinstance(scene_chars, list) else [],
        )] + _parse_prose_to_elements(nd.get("prose", ""))

    node = Node(
        id=nid,
        kind=kind,
        skeleton=skeleton_list,
        content=content_list,
        planned_duration_min=_parse_duration_field(nd.get("planned_duration_min", 2.0)),
        chapters=_parse_chapters_field(nd.get("chapters", [0, 0])),
        covers=nd.get("covers", []),
        produces=_parse_effects(nd.get("produces", [])),
        requires=_parse_requirements(nd.get("requires", [])),
        entry_invariants=_parse_requirements(nd.get("entry_invariants", [])),
        ending=nd.get("ending", "NONE"),
        question=nd.get("question"),
        choices=choices,
        entry_context=nd.get("entry_context", ""),
        exit_context=nd.get("exit_context", ""),
        sequence=(str(nd.get("sequence")) if isinstance(nd.get("sequence"), str)
                  and len(str(nd.get("sequence"))) == 1
                  and str(nd.get("sequence")).isalpha() else ""),
        arc_slot=(str(nd.get("arc_slot")) if nd.get("arc_slot") in (
            "hook", "lock_in", "first_attempt", "midpoint", "complication",
            "main_culmination", "crisis", "crisis_finale", "climax", "resolution",
        ) else ""),
        tension=int(nd.get("tension", 0) or 0),
        value=str(nd.get("value", "") or ""),
        opening_charge=_parse_charge(nd.get("opening_charge")),
        closing_charge=_parse_charge(nd.get("closing_charge")),
        turning_type=(str(nd.get("turning_type"))
                      if nd.get("turning_type") in ("action", "revelation") else ""),
        expectation=str(nd.get("expectation", "") or ""),
        result=str(nd.get("result", "") or ""),
    )
    if node.ending == "DEAD_END":
        node.planned_duration_min = max(0.5, min(1.5, node.planned_duration_min))
    else:
        node.planned_duration_min = max(2.0, min(5.0, node.planned_duration_min))
    return node


def _parse_charge(raw) -> str:
    """Accept only '+'/'-' (or 正/负 aliases); anything else is no-data."""
    s = str(raw or "").strip()
    if s.startswith(("+", "正")):
        return "+"
    if s.startswith(("-", "−", "负")):
        return "-"
    return ""


def _parse_duration_field(raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 2.0
    return max(0.5, min(5.0, value))


def _parse_subgraph_response(data: dict) -> tuple[dict[NodeId, Node], list[FactDecl]]:
    """Parse a creative_writing / creative_writing_fix response."""
    if not isinstance(data, dict):
        log.warning("Subgraph response was %s, expected object", type(data).__name__)
        return {}, []

    nodes = {}
    raw_nodes = data.get("nodes", {})
    if isinstance(raw_nodes, str):
        try:
            parsed_nodes = _parse_json_from_response(raw_nodes)
            if isinstance(parsed_nodes, dict):
                raw_nodes = parsed_nodes
        except Exception:
            pass
    if not isinstance(raw_nodes, dict):
        log.warning("Subgraph 'nodes' was %s, expected object", type(raw_nodes).__name__)
        raw_nodes = {}
    for nid, nd in raw_nodes.items():
        if not isinstance(nd, dict):
            log.warning("Node '%s' value is %s, skipping", nid, type(nd).__name__)
            continue
        nodes[nid] = _parse_node(nid, nd)

    new_decls = []
    new_decls.extend(_parse_new_facts(data.get("new_facts", [])))

    return nodes, new_decls


def _parse_new_facts(items: Any) -> list[FactDecl]:
    """Parse a `new_facts` array into FactDecl declarations, skipping malformed
    entries. Single source for what was 6 copy-pasted loops."""
    if not isinstance(items, list):
        return []
    return [
        FactDecl(id=f["id"], kind=f.get("kind", "event"), gloss=f.get("gloss", ""),
                 initial=f.get("initial", False), invariant=f.get("invariant", False))
        for f in items if isinstance(f, dict) and "id" in f
    ]


def _parse_graph(data: dict) -> Graph:
    """Parse a JSON graph dict into a Graph object."""
    graph = Graph(root=data["root"])
    for nid, nd in data["nodes"].items():
        graph.nodes[nid] = _parse_node(nid, nd)
    return graph


# ---------- §3.11 creative_writing ----------

def creative_writing(
    a_id: NodeId, b_id: NodeId, bible: dict, chapter_span: tuple[int, int],
    chapters_index: dict[int, str], unplaced_highlights: list[Highlight],
    goal: Goal, etype: str, params: Params,
    registry: Registry | None = None,
    a_context: dict | None = None,
    b_context: dict | None = None,
    extra_context: str = "",
    target_candidates: list[NodeId] | None = None,
    dead_end_allowed: bool = False,
) -> tuple[dict[NodeId, Node], list[FactDecl]]:
    """§3.11 — Generate interior subgraph between A and B."""
    highlights_desc = json.dumps(
        [{"id": h.id, "chapter": h.chapter, "weight": h.weight, "gloss": h.gloss}
         for h in sorted(unplaced_highlights, key=lambda h: -h.weight)[:8]],
        ensure_ascii=False,
    )
    # Filter entry state to only show set facts (not all False defaults)
    entry_facts = {
        k: v for k, v in goal.entryA_state.items()
        if v is not False and v is not VARIES
    }
    varying_desc = goal.varying_state if goal.varying_state else []

    goal_desc = json.dumps({
        "entryA_state": entry_facts,
        "exitB_contract": [{"fact": r.fact, "value": r.value} for r in goal.exitB_contract],
        "invariants": goal.invariants,
        "varying_DO_NOT_REFERENCE": varying_desc,
    }, ensure_ascii=False, indent=2)

    chapters_text = ""
    for ch in range(chapter_span[0], chapter_span[1] + 1):
        if ch in chapters_index:
            chapters_text += f"\n--- Chapter {ch} ---\n{chapters_index[ch]}\n"

    candidates_desc = json.dumps([b_id] + list(target_candidates or []), ensure_ascii=False)
    if dead_end_allowed:
        dead_end_rule = (
            f"- DEAD-END BUDGET OPEN: you SHOULD give one interior choice a new DEAD_END node "
            f"(ending=\"DEAD_END\", no choices/question, planned_duration_min 0.5-1.0) — a real "
            f"dramatized failure with a price (短剧式 BE), not filler."
        )
    else:
        dead_end_rule = "- Dead-end budget is FULL: do NOT create DEAD_END nodes."
    shape_rules = f"""- Create 1-2 NEW interior scene nodes between "{a_id}" and "{b_id}" (plus optionally ONE DEAD_END per the budget rule below).
- "{a_id}" gets exactly ONE replacement choice pointing to your first new interior node. The harness preserves its other existing edge — A ends with 2 choices to DIFFERENT nodes.
- Each interior node has EXACTLY 2 choices. Each choice picks a target from:
  TARGET CANDIDATES (all of these flow into "{b_id}" without skipping it): {candidates_desc}
  plus: your other new interior node (if you create two), or your new DEAD_END (if budgeted).
  Prefer two DIFFERENT targets; both-choices-to-"{b_id}"-with-different-state_delta only as a last resort.
{dead_end_rule}
- "{b_id}" is an immutable already-validated boundary. Include it only as an unchanged endpoint; do NOT modify its content, produces, requires, ending, or choices.
- Interior nodes must contain a real dramatic beat: a gratification payoff (爽点) or a reversal from the unplaced highlights below — not connective filler."""

    registry_desc = _compact_registry(registry) if registry else "(no registry available)"

    _ac = a_context or {}
    _bc = b_context or {}
    a_exit_ctx = _ac.get("exit_context", "(unknown)")
    a_location = _ac.get("location", "(unknown)")
    b_entry_ctx = _bc.get("entry_context", "(unknown)")
    b_location = _bc.get("location", "(unknown)")

    system = f"""{_CREATIVE_WRITING_SKELETON_MD}

## Current task
Expansion type: {etype}
Endpoint A: {a_id}
Endpoint B: {b_id}

## Registry (id: kind, init=value[,inv] — description)
{registry_desc}

## Goal (frozen seams)
{goal_desc}

IRON RULE: You MUST NOT mention, reference, or assume any item, event, or fact
listed in "varying_DO_NOT_REFERENCE". These facts exist on SOME paths only.

## Scene anchors (PLOT continuity — location cuts are FREE)
Endpoint A "{a_id}" exits at: {a_exit_ctx}
Endpoint B "{b_id}" enters at: {b_entry_ctx}

Continuity is about PLOT, not coordinates: a cut to a new location/time is
normal film grammar (写出转场即可). What must hold: time moves forward, and the
causal chain from A's exit into B's entry stays coherent. Stage each scene
WHERE THE SOURCE STORY stages it — the original chapters carry the location
signals; follow them.

## Unplaced highlights in this span
{highlights_desc}
{extra_context}
## Source chapters (span {chapter_span[0]}-{chapter_span[1]})
{chapters_text}

## Small expansion contract
{shape_rules}

## Output requirements (SKELETON ONLY)
- Output "skeleton" ONLY: 5-8 structured beats (scene_header first). Do NOT output a "content" field — prose comes later.
- The "skeleton" beats are the sole plot record (no separate summary field); they must carry every character, event, dialogue point, item, and turn
- Every node MUST include "entry_context" and "exit_context" (WHERE/WHEN)
- Every node MUST include "kind" ("prologue"|"scene"|"bottleneck"|"ending")
- Every node MUST include "planned_duration_min" (expected final prose/shooting duration in minutes)
- Every choice MUST include "resolution" (exactly 2 short beats showing choice outcome)
- Choice "label" must be ≤8 Chinese chars, player action (not outcome)
- "question" must be ≤30 Chinese chars
- **CRITICAL**: Every non-ending node MUST have EXACTLY 2 choices. The 2 choices may share the SAME target node ONLY when their "state_delta" differ (choice writes state instead of forking). Otherwise targets must be distinct.
- Every node MUST carry the scene contract: "value" (价值轴), "opening_charge"/"closing_charge" (ONLY "+" or "-", must differ), "turning_type" ("action"|"revelation"), "tension" (1-5), "expectation"/"result" (result deviates), "sequence" (copy from endpoint B's sequence letter).
- Every choice MUST carry "cost" (irreversible price, one sentence) and "goal_impacts" over the protagonist goals (integers; a true dilemma = every option negative on some goal).
- Ending/DEAD_END nodes must have 0 choices.
- "goal_impacts" keys MUST come verbatim from the protagonist goals: {json.dumps([g.get("id") for g in (bible or {}).get("protagonist_goals", [])], ensure_ascii=False)} — never synonyms, never English ids.
- Prefer reusing existing fact IDs from the registry. If a new fact is needed, declare it in new_facts.
- Keep produces/requires minimal. Do not add a requirement unless the node truly presupposes prior state.

Return ONLY valid JSON:
{{
  "nodes": {{
    "{a_id}": {{ ... updated A with new choices, skeleton: [...], summary: "..." ... }},
    "interior_node_id": {{ ... skeleton: [...], summary: "..." ... }},
    "{b_id}": {{ ... unchanged B boundary endpoint ... }}
  }},
  "new_facts": [
    {{"id": "player.x", "kind": "event", "gloss": "...", "initial": false, "invariant": false}}
  ]
}}"""

    user = f"""## Compact bible
{json.dumps(_compact_bible(bible), ensure_ascii=False, indent=2)}

Generate the bounded small subgraph SKELETON. Structure + summary + thin plot content only. Return only JSON."""

    data = _call_json(system, user, params, context=f"expansion {a_id}->{b_id}",
                      schema=_SKELETON_SUBGRAPH_SCHEMA,
                      reasoning_effort=_structure_effort())
    return _parse_subgraph_response(data)


# ---------- §3.12 creative_writing_fix ----------

def creative_writing_fix(
    a_id: NodeId, b_id: NodeId, bible: dict, chapter_span: tuple[int, int],
    chapters_index: dict[int, str], unplaced_highlights: list[Highlight],
    goal: Goal, etype: str, subgraph: dict[NodeId, Node],
    feedback: Feedback, params: Params,
    a_context: dict | None = None,
    b_context: dict | None = None,
    registry: Registry | None = None,
    extra_context: str = "",
    target_candidates: list[NodeId] | None = None,
    dead_end_allowed: bool = False,
) -> tuple[dict[NodeId, Node], list[FactDecl]]:
    """§3.12 — Fix a subgraph based on validation feedback.

    Receives the SAME context the generator had (candidate menu, dead-end
    budget, sequence obligations) — a fix must not violate the contract it
    repairs."""
    highlights_desc = json.dumps(
        [{"id": h.id, "chapter": h.chapter, "weight": h.weight, "gloss": h.gloss}
         for h in sorted(unplaced_highlights, key=lambda h: -h.weight)[:12]],
        ensure_ascii=False,
    )
    chapters_text = ""
    for ch in range(chapter_span[0], chapter_span[1] + 1):
        if ch in chapters_index:
            chapters_text += f"\n--- Chapter {ch} ---\n{chapters_index[ch]}\n"

    entry_facts = {
        k: v for k, v in goal.entryA_state.items()
        if v is not False and v is not VARIES
    }
    goal_desc = json.dumps({
        "entryA_state": entry_facts,
        "exitB_contract": [{"fact": r.fact, "value": r.value} for r in goal.exitB_contract],
        "invariants": goal.invariants,
        "varying_DO_NOT_REFERENCE": goal.varying_state,
    }, ensure_ascii=False, indent=2)

    # Serialize current subgraph
    sub_json = {}
    for nid, node in subgraph.items():
        sub_json[nid] = {
            "id": nid,
            "skeleton": node.skeleton,
            "content": node.content,
            "summary": node.get_summary(),
            "planned_duration_min": node.planned_duration_min,
            "chapters": list(node.chapters),
            "covers": node.covers,
            "kind": node.kind,
            "produces": [{"fact": e.fact, "value": e.value} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "entry_invariants": [{"fact": r.fact, "value": r.value} for r in node.entry_invariants],
            "ending": node.ending,
            "question": node.question,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "choices": [{"label": c.label, "to": c.to,
                         "resolution": list(c.resolution),
                         "label_requires": [{"fact": r.fact, "value": r.value} for r in c.label_requires]}
                        for c in node.choices],
        }

    violations_json = [
        {"node": v.node, "check": v.check, "severity": v.severity,
         "problem": v.problem, "suggested_fix": v.suggested_fix}
        for v in feedback.violations
    ]

    _fix_ac = a_context or {}
    _fix_bc = b_context or {}
    _fix_a_exit_ctx = _fix_ac.get("exit_context", "(unknown)")
    _fix_a_location = _fix_ac.get("location", "(unknown)")
    _fix_b_entry_ctx = _fix_bc.get("entry_context", "(unknown)")
    _fix_b_location = _fix_bc.get("location", "(unknown)")

    system = f"""{_CREATIVE_WRITING_SKELETON_MD}

## Fix request (SKELETON ONLY)
You previously generated a skeleton subgraph that has validation violations.
## Generation contract (unchanged — your fix must still satisfy it)
Target candidates (all flow into "{b_id}" without skipping it): {json.dumps([b_id] + list(target_candidates or []), ensure_ascii=False)}
Dead-end budget: {"OPEN — one DEAD_END allowed" if dead_end_allowed else "FULL — do NOT create DEAD_END nodes"}
{extra_context}
## Protagonist goals (goal_impacts keys MUST come from this list verbatim)
{json.dumps([g.get("id") for g in (bible or {}).get("protagonist_goals", [])], ensure_ascii=False)}

Fix the listed violations one by one, in order. Deterministic violations (D1-D11)
are AUTHORITATIVE.

Rules:
- Make the smallest edit that fixes each listed violation.
- Do not rewrite unrelated nodes or unrelated fields.
- Do not introduce new node IDs unless the listed violation cannot be fixed otherwise.
- Preserve the expansion contract for A={a_id}, B={b_id}, etype={etype}.
- "content" MUST remain thin plot content. Do not polish it into final prose; Phase 4 does that later.
- Update the "skeleton" beats if structural changes alter the node's events (they are the sole plot record).
- If you add a new fact ID, declare it in new_facts.
- Ordinary first appearances of people/items/events should be introduced in summary.
  Do NOT add them to requires unless the node truly presupposes they were established earlier.
- If a violation is about an unnecessary prerequisite, remove the requires entry;
  only add produces/new_facts if later nodes depend on it.

## Goal/state contract
{goal_desc}

## Scene anchors (PLOT continuity — location cuts are FREE)
Endpoint A "{a_id}":
  exit_context: {_fix_a_exit_ctx}
  scene location: {_fix_a_location}
Endpoint B "{b_id}":
  entry_context: {_fix_b_entry_ctx}
  scene location: {_fix_b_location}

Time moves forward; the causal chain from A's exit into B's entry stays coherent. Location cuts are fine — stage scenes where the source does.

## Weighted highlights in this span
{highlights_desc}

## Source chapters for this expansion
{chapters_text}

## Previous subgraph
{json.dumps(sub_json, ensure_ascii=False, indent=2)}

## Violations to fix
{json.dumps(violations_json, ensure_ascii=False, indent=2)}

Return ONLY valid JSON with the fixed skeleton subgraph.
Include "new_facts" if you need to register new facts."""

    user = f"Bible: {json.dumps(bible, ensure_ascii=False)}\nExpansion: {etype}, A={a_id}, B={b_id}"

    data = _call_json(system, user, params, context=f"fix {a_id}->{b_id}", cacheable=False,
                      schema=_SKELETON_SUBGRAPH_SCHEMA,
                      reasoning_effort=_structure_effort())
    return _parse_subgraph_response(data)


def creative_graph_fix(
    graph: Graph,
    bible: dict,
    chapters_index: dict[int, str],
    highlights: list[Highlight],
    feedback: Feedback,
    params: Params,
) -> tuple[Graph, list[FactDecl]]:
    """Fix exact full-graph validation failures without changing harness rules."""
    graph_json: dict[str, Any] = {
        "root": graph.root,
        "nodes": {},
    }
    for nid, node in graph.nodes.items():
        graph_json["nodes"][nid] = {
            "id": nid,
            "kind": node.kind,
            "skeleton": node.skeleton,
            "content": node.content,
            "summary": node.get_summary(),
            "planned_duration_min": node.planned_duration_min,
            "chapters": list(node.chapters),
            "covers": node.covers,
            "produces": [{"fact": e.fact, "value": e.value} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "entry_invariants": [{"fact": r.fact, "value": r.value} for r in node.entry_invariants],
            "ending": node.ending,
            "question": node.question,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "choices": [
                {
                    "label": c.label,
                    "to": c.to,
                    "resolution": list(c.resolution),
                    "label_requires": [
                        {"fact": r.fact, "value": r.value} for r in c.label_requires
                    ],
                }
                for c in node.choices
            ],
        }

    violations_json = [
        {
            "node": v.node,
            "check": v.check,
            "severity": v.severity,
            "problem": v.problem,
            "suggested_fix": v.suggested_fix,
        }
        for v in feedback.violations
    ]

    chapter_ids = sorted({
        ch
        for node in graph.nodes.values()
        for ch in range(node.chapters[0], node.chapters[1] + 1)
    })
    violating_nodes = {v.node for v in feedback.violations}
    relevant_chapters = sorted({
        ch
        for nid in violating_nodes
        if nid in graph.nodes
        for ch in range(graph.nodes[nid].chapters[0], graph.nodes[nid].chapters[1] + 1)
    }) or chapter_ids
    highlights_desc = json.dumps(
        [
            {"id": h.id, "chapter": h.chapter, "weight": h.weight, "gloss": h.gloss}
            for h in sorted(highlights, key=lambda h: -h.weight)
            if h.chapter in set(relevant_chapters)
        ][:16],
        ensure_ascii=False,
        indent=2,
    )
    source_excerpt = ""
    for ch in relevant_chapters:
        if ch in chapters_index:
            source_excerpt += f"\n--- Chapter {ch} ---\n{chapters_index[ch][:4000]}\n"

    system = f"""{_CREATIVE_WRITING_MD}

## Full graph repair
You are repairing an already-generated interactive story graph after full-graph validation.
Fix the EXACT violations listed below, whether they come from old nodes or newly generated nodes.

Rules:
- Return the COMPLETE graph, not a partial patch.
- Preserve node IDs and edge targets unless a violation explicitly requires changing them.
- Preserve each node's existing skeleton beats (the sole plot record) and content unless the listed violation explicitly targets that node's plot/content.
- Fix the listed violations one by one, in order; do not chase unrelated improvements.
- Make the smallest graph/prose/state edit that fixes each listed violation.
- Preserve the strict binary contract: every non-ending node has exactly 2 choices; the 2 choices may share a target ONLY if their state_delta differ, otherwise targets must differ; ENDING/DEAD_END nodes have 0 choices.
- Preserve DAG reachability and keep every non-ending node able to reach an ENDING.
- Do not invent fallback prose. Any changed visible prose must be written from the source/bible.
- Deterministic violations D1-D10 are authoritative.
- Semantic violations S1-S5 must be fixed in prose, labels, facts, requirements, or local topology as appropriate.
- If content mentions a path-dependent item/person/event, fix it with the smallest coherent edit:
  remove the assumption, introduce it locally in content, or add produces/new_facts when later
  nodes depend on it. Add requires only when the node truly presupposes prior state already
  guaranteed on every incoming path.
- If feedback says "missing requires" for a first-appearing object/person/event, do NOT blindly
  add requires. Either introduce it locally in the node prose, establish it upstream with
  source-grounded prose plus produces/new_facts, or remove the assumption.

## Violations to fix
{json.dumps(violations_json, ensure_ascii=False, indent=2)}

Return ONLY valid JSON with root, new_facts, and nodes."""

    user = f"""## Compact bible
{json.dumps(_compact_bible(bible), ensure_ascii=False, indent=2)}

## Source excerpt
{source_excerpt}

## Weighted highlights for relevant chapters
{highlights_desc}

## Current full graph
{json.dumps(graph_json, ensure_ascii=False, indent=2)}
"""

    data = _call_json(system, user, params, context="full graph fix", cacheable=False,
                      schema=_CORNERSTONE_SCHEMA,
                      reasoning_effort=_structure_effort())
    fixed = _parse_graph(data)
    for nid, old_node in graph.nodes.items():
        new_node = fixed.nodes.get(nid)
        if not new_node:
            continue
        if not new_node.content and old_node.content:
            new_node.content = list(old_node.content)
            log.info("  Full-graph repair preserved existing content for %s", nid)
        if not new_node.skeleton and old_node.skeleton:
            new_node.skeleton = list(old_node.skeleton)
            log.info("  Full-graph repair preserved existing skeleton for %s", nid)
    new_decls = _parse_new_facts(data.get("new_facts", []))
    return fixed, new_decls


# ---------- §3.14 validate_semantic ----------

def validate_semantic(
    graph: Graph, region: list[NodeId] | None, params: Params
) -> list[Violation]:
    """§3.14 semantic — LLM-based meaning/voice/faithfulness check."""
    nodes_to_check = region if region else list(graph.nodes.keys())

    # Serialize the region with path info for convergence nodes
    region_json = {}
    for nid in nodes_to_check:
        if nid not in graph.nodes:
            continue
        node = graph.nodes[nid]
        node_data = {
            "skeleton": node.skeleton,
            "content": node.content,
            "kind": node.kind,
            "summary": node.get_summary(),
            "planned_duration_min": node.planned_duration_min,
            "produces": [{"fact": e.fact, "value": e.value} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "question": node.question,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "choices": [
                {"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts}
                for c in node.choices
            ],
            "ending": node.ending,
        }
        # Add path info for convergence nodes (multiple parents)
        parents = [pid for pid, pn in graph.nodes.items()
                   for c in pn.choices if c.to == nid]
        if len(parents) > 1:
            all_paths = _trace_all_paths_to(nid, graph)
            path_info = []
            for path in all_paths:
                path_nodes = [p for p in path if p != nid and p in graph.nodes]
                path_info.append({
                    "route": " → ".join(path),
                    "summaries": {p: graph.nodes[p].get_summary() for p in path_nodes if graph.nodes[p].get_summary()},
                })
            node_data["_convergence_paths"] = path_info
        region_json[nid] = node_data

    system = _VALIDATION_MD

    user = f"""Validate this region of the interactive story graph:

{json.dumps(region_json, ensure_ascii=False, indent=2)}

Note: this may be a scoped region, not the complete graph. Choice targets that
are not included in this JSON may still exist in the full graph; do not report
missing/dead-link violations for omitted external targets. Deterministic code
has already checked real graph reachability and target existence.

Important state-model rule: a person/item/event first appearing in this node is
normally introduced locally in prose, not added to requires. Suggest requires
only when the node truly presupposes prior state already guaranteed before entry.
For ordinary first appearances, suggest local prose introduction, produces, or
new_facts if later nodes depend on the fact.

Question/choice alignment (check S4): For each node with a question and choices,
verify that the choice labels semantically relate to the question posed. The
question should frame the dilemma that the choices resolve. Report violations if:
- The question mentions options that don't exist as choices
- Choice labels are unrelated to the question's framing
- The question asks "A or B?" but neither A nor B appears as a choice label

Path-dependent content (check S5): For nodes with "_convergence_paths" (reachable
from multiple paths), check if the prose references specific characters, items, or
events that only happen on ONE path. Report violations if:
- Prose mentions a character who is only introduced on one path (e.g., a character
  met in node X, but the node is also reachable without going through X)
- Prose assumes the player has an item obtained on only one path
- Prose uses definite references ("那个人", "那把刀") to things not guaranteed on all paths
This is CRITICAL — path-dependent prose is a plot hole that breaks the story.

Return a JSON list of violations (empty list = pass)."""

    try:
        data = _call_json(
            system, user, params,
            context="semantic validation", cacheable=False, top_level="array", schema=_VIOLATIONS_SCHEMA,
        )
    except json.JSONDecodeError:
        log.warning("Semantic validation LLM call failed to return valid JSON; treating as pass")
        return []

    return _filter_semantic_violations(data, scoped_region=bool(region))


def _filter_semantic_violations(
    data: list[dict], *, scoped_region: bool = False,
) -> list[Violation]:
    """Shared post-processing filter for semantic validation results."""
    violations = []
    for v in data:
        problem = v.get("problem", "")
        suggested_fix = v.get("suggested_fix", "")
        if scoped_region and (
            "not defined in the provided region" in problem
            or "not defined in provided region" in problem
            or "provided region" in problem and "not defined" in problem
            or "未在提供的区域" in problem
        ):
            continue
        if (
            "\u4eba\u5217\u8868" in problem
            or "\u201c\u4eba\u201d\u5217\u8868" in problem
            or "\u201c\u4eba\u201d \u5217\u8868" in problem
            or "people list" in problem.lower()
        ):
            continue
        if "requires" in problem or "requires" in suggested_fix or "前置条件" in problem:
            suggested_fix = (
                "Do not add requires unless this fact is already guaranteed before the node. "
                "Prefer the smallest coherent fix: introduce the element locally in this node's prose, "
                "remove the assumption, or add produces/new_facts on an upstream node if later nodes depend on it."
            )
            problem = (
                f"{problem} Treat this as a possible unstated assumption, not automatically as a missing requires entry."
            )
        violations.append(Violation(
            node=v.get("node", ""),
            check=v.get("check", "other"),
            severity=v.get("severity", "med"),
            problem=problem,
            suggested_fix=suggested_fix,
        ))
    return violations


def validate_semantic_node(
    node: Node, memory: "NodeMemory", params: Params,
) -> list[Violation]:
    """Light per-node semantic validation with compressed DFS reader memory.

    Args:
        node: The node to validate.
        memory: NodeMemory with accumulated ancestor context.
        params: Harness params (LLM budget etc).

    Returns:
        List of semantic violations for this single node.
    """
    # Build compact payload. Keep this small: Phase 4.5 runs one call per node
    # after structure/prose have already passed stronger deterministic gates.
    reader_has_seen = [
        {
            "node": nid,
            "summary": summ,
            "skeleton_beats": [
                bt[:60] for bt in bts[:8]
            ],
        }
        for (nid, summ), (_, bts) in zip(
            memory.ancestor_summaries[-5:],
            memory.ancestor_skeleton_beats[-5:],
        )
    ]
    # Pad if skeleton_beats list is shorter than summaries
    while len(reader_has_seen) < len(memory.ancestor_summaries[-5:]):
        idx = len(reader_has_seen)
        nid, summ = memory.ancestor_summaries[-5:][idx]
        reader_has_seen.append({"node": nid, "summary": summ, "skeleton_beats": []})
    established_facts = dict(list(memory.established_facts.items())[-15:])
    content_text = node.get_prose()
    if len(content_text) > 1400:
        content_text = content_text[:1000] + "\n...[truncated]...\n" + content_text[-400:]
    node_data = {
        "id": node.id,
        "kind": node.kind,
        "summary": node.get_summary(),
        "skeleton_beats": [el.get("text", "") or el.get("line", "")
                          for el in node.skeleton
                          if el.get("type", "") not in ("scene_header", "namecard")
                          and (el.get("text", "") or el.get("line", ""))],
        "planned_duration_min": node.planned_duration_min,
        "content_text": content_text,
        "entry_context": node.entry_context,
        "exit_context": node.exit_context,
        "ending": node.ending,
        "question": node.question,
        "choices": [
            {"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts}
            for c in node.choices
        ],
        "produces": [{"fact": e.fact, "value": e.value} for e in node.produces],
        "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
    }

    payload = {
        "reader_has_seen": reader_has_seen,
        "established_facts": established_facts,
        "known_characters": sorted(memory.known_characters)[:20],
        "last_exit_context": memory.last_exit_context,
        "is_convergence": memory.is_convergence,
        "current_node": node_data,
    }

    system = _VALIDATION_MD
    convergence_note = ""
    if memory.is_convergence:
        convergence_note = (
            "\n\nIMPORTANT: This is a CONVERGENCE node (reachable from multiple paths). "
            "reader_has_seen only includes GUARANTEED ancestors — nodes every possible "
            "path passes through. The prose must NOT reference characters, items, or "
            "events from non-guaranteed ancestors. Flag S5 violations for any such references."
        )

    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    log.debug(
        "  Semantic payload %s: payload=%d chars ancestors=%d/%d facts=%d/%d chars=%d content=%d chars convergence=%s",
        node.id,
        len(payload_json),
        len(reader_has_seen), len(memory.ancestor_summaries),
        len(established_facts), len(memory.established_facts),
        len(payload["known_characters"]), len(content_text),
        memory.is_convergence,
    )

    user = f"""Lightly validate this single node of the interactive story graph.

Compressed DFS reader memory and current node:
{payload_json}

Rules:
- Only validate current_node.
- This is not a full-graph audit.
- The graph shape, reachability, scene continuity, schema, and final deterministic rules were already checked.
- reader_has_seen, established_facts, known_characters, and last_exit_context are the only guaranteed prior context.

Important state-model rule: a person/item/event first appearing in this node is
normally introduced locally in prose, not added to requires. Suggest requires
only when the node truly presupposes prior state already guaranteed before entry.

Question/choice alignment (check S4): verify choice labels semantically relate to the question.

Narration function (check S8): every narration element may ONLY carry (1) background/setting
or (2) a character's interior thought/emotion. Flag S8 (severity high) for any narration that
carries a CRITICAL EVENT — plot turn, the occurrence or outcome of a conflict, a key action, a
major reveal, or a key item/evidence appearing or changing hands — instead of dramatizing it via
action+dialogue. Test: if deleting that narration line leaves the reader unaware "something big
happened", it is narrating a critical event → violation. Do NOT flag background, interiority, or
a brief (≤2 sentence) prologue establishing narration.

Opening anchoring (check S9, ONLY when current_node.kind == "prologue"): the root must STAGE the
story's literal opening scene (the very first beat), not jump to a later crisis. Flag S9 (high) if
the prologue's identity/backstory/ability-origin is delivered as a narration info-dump (a narration
line that spells out the protagonist's hidden identity or prior history) instead of surfacing
through the protagonist's own on-screen actions and dialogue. Do NOT flag a ≤2-sentence time/place
establishing narration.

Path-dependent content (check S5): if this is a convergence node, check for references to
characters/items/events that are NOT in reader_has_seen or known_characters — those would
only exist on some paths, not all.{convergence_note}

Return JSON object: {{"violations": []}} when clean."""

    try:
        data = _call_json(
            system, user, params,
            context=f"semantic_node_{node.id}", cacheable=False,
            schema=_VIOLATIONS_OBJECT_SCHEMA,
        )
    except json.JSONDecodeError:
        log.warning("Per-node semantic validation failed for %s; treating as pass", node.id)
        return []

    return _filter_semantic_violations(data.get("violations", []))


def validate_skeleton_node_semantic(
    node: Node,
    graph: Graph,
    params: Params,
) -> list[Violation]:
    """Light semantic check for skeleton-only local consistency before prose."""
    payload = _skeleton_node_payload(node, graph)
    system = """You validate ONE skeleton node before prose generation.
Do not review style. Do not request more context. Deterministic graph shape has already been checked.

Check only local contract consistency:
- the skeleton beats (thin_content) must agree with produces
- question must agree with choices and choice resolutions
- choice resolutions must not contradict produces or the skeleton beats
- if a fact is produced by this node, the skeleton beats must establish it before choices
- if a choice resolution changes the state differently per choice, that state must not be produced unconditionally by the node

Return JSON object: {"violations": []} when clean."""
    user = f"""Validate this skeleton node contract:
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}

Report only concrete contradictions that can be fixed by editing this one node's skeleton beats, produces, question, or choices."""
    data = _call_json(
        system, user, params,
        context=f"skeleton_node_semantic_{node.id}", cacheable=False,
        schema=_VIOLATIONS_OBJECT_SCHEMA,
    )
    return _filter_semantic_violations(data.get("violations", []))


def fix_skeleton_node_semantics(
    node: Node,
    graph: Graph,
    violations: list[Violation],
    params: Params,
    allowed_fact_ids: set[str] | None = None,
    memory_context: dict | None = None,
    protagonist_goals: list[str] | None = None,
) -> tuple[Node | None, list[dict]]:
    """Fix one skeleton node's semantic contract. May also suggest upstream fixes.

    Returns (fixed_node, upstream_fixes). upstream_fixes is a list of dicts
    with keys: node_id, produces_to_add, produces_to_remove, summary_patch.
    If fix fails, returns (None, []).
    """
    payload = _skeleton_node_payload(node, graph)
    violations_json = [
        {
            "node": v.node,
            "check": v.check,
            "severity": v.severity,
            "problem": v.problem,
            "suggested_fix": v.suggested_fix,
        }
        for v in violations
    ]
    parent_payloads = []
    for pid in graph.predecessors(node.id):
        p = graph.nodes[pid]
        parent_payloads.append({
            "id": p.id,
            "summary": p.get_summary(),
            "produces": [{"fact": e.fact, "value": e.value} for e in p.produces],
            "choices": [
                {"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts}
                for c in p.choices
            ],
        })
    system = f"""{_CREATIVE_WRITING_SKELETON_MD}

## Skeleton repair with upstream propagation
Fix the current node's semantic contract. If the violation cannot be resolved
by editing the current node alone (e.g. a fact must be produced on only one
choice edge, not unconditionally), suggest upstream_fixes to parent nodes.

Allowed edits on current node:
- summary, thin content, planned_duration_min
- produces, requires (only if truly needed)
- question, choices labels and resolution beats
- entry_context/exit_context (only if required)

Upstream fixes (in upstream_fixes array):
- produces_to_add: facts a parent should produce on the edge leading to this node
- produces_to_remove: facts a parent should stop producing unconditionally
- summary_patch: brief instruction to patch a parent's summary

Forbidden:
- Do not add polished prose. content MUST remain thin plot content.
- Do not change node id, kind, ending, chapters, covers, or choice target ids.
- Do not introduce new facts. Use existing fact ids or remove incorrect produces.
- Every fact id in produces/requires MUST be in the allowed fact ids list below.
- Do not rewrite unrelated plot; make the smallest fix for the listed violations.
- SEAMS: keep entry/exit contexts PLOT-coherent with parents/children (time
  forward, causal chain intact). Location itself may differ — a written scene
  cut is fine.

Key rules:
- If a choice resolution says a fact may differ by choice, that fact cannot be in
  this node's unconditional produces. Move it to a parent's choice-edge or remove it.
- If produces declares a fact, the summary must establish it before the choice point.
- If reader memory says something is not guaranteed, do not presuppose it.
- If removing a produce from this node would break a child's requires, add that
  produce to the parent node on the relevant choice edge instead.

Return JSON object: {{"node": <fixed node>, "upstream_fixes": [<optional>]}}"""
    allowed_fact_text = "\n".join(sorted(allowed_fact_ids or set()))
    goals_text = json.dumps(protagonist_goals or [], ensure_ascii=False)
    user = f"""## Protagonist goals (goal_impacts keys MUST come from this list verbatim; never invent synonyms or English ids)
{goals_text}

## Allowed fact ids
{allowed_fact_text}

## Guaranteed reader memory before this node
{json.dumps(memory_context or {}, ensure_ascii=False, indent=2)}

## Parent nodes
{json.dumps(parent_payloads[-4:], ensure_ascii=False, indent=2)}

## FROZEN child entry contexts (exit_context must stay compatible)
{json.dumps([
    {"child": c.to, "entry_context": graph.nodes[c.to].entry_context}
    for c in node.choices if c.to in graph.nodes
], ensure_ascii=False)}

## Node contract
{json.dumps(payload, ensure_ascii=False, indent=2)}

## Violations
{json.dumps(violations_json, ensure_ascii=False, indent=2)}

Return the fixed node and any upstream_fixes needed."""
    try:
        data = _call_json(
            system, user, params,
            context=f"skeleton_node_fix_{node.id}", cacheable=False,
            schema=_SKELETON_NODE_FIX_SCHEMA,
        )
    except json.JSONDecodeError as e:
        log.warning("Skeleton node fix failed for %s: %s", node.id, e)
        return None, []
    fixed = _parse_node(node.id, data.get("node", {}))
    fixed.id = node.id
    fixed.kind = node.kind
    fixed.ending = node.ending
    fixed.chapters = node.chapters
    fixed.covers = list(node.covers)
    fixed.planned_duration_min = _parse_duration_field(fixed.planned_duration_min)
    if len(fixed.choices) == len(node.choices):
        for i, choice in enumerate(fixed.choices):
            choice.to = node.choices[i].to
    upstream = data.get("upstream_fixes") or []
    return fixed, upstream


def _skeleton_node_payload(node: Node, graph: Graph) -> dict:
    parents = [
        {
            "id": pid,
            "summary": graph.nodes[pid].get_summary(),
            "produces": [
                {"fact": e.fact, "value": e.value}
                for e in graph.nodes[pid].produces
            ],
            "choice_to_this": [
                {
                    "label": c.label,
                    "resolution": list(c.resolution),
                }
                for c in graph.nodes[pid].choices
                if c.to == node.id
            ],
        }
        for pid in graph.nodes
        if any(c.to == node.id for c in graph.nodes[pid].choices)
    ]
    children = [
        {
            "choice_label": c.label,
            "to": c.to,
            "resolution": list(c.resolution),
            "child_summary": graph.nodes[c.to].get_summary() if c.to in graph.nodes else "",
        }
        for c in node.choices
    ]
    return {
        "current_node": {
            "id": node.id,
            "kind": node.kind,
            "skeleton": node.skeleton,
            "planned_duration_min": node.planned_duration_min,
            "produces": [{"fact": e.fact, "value": e.value, "beat": e.beat} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "ending": node.ending,
            "question": node.question,
            "choices": [
                {"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts}
                for c in node.choices
            ],
        },
        "parents": parents[-4:],
        "children": children,
    }


# ---------- Prose writing (final pass) ----------

def _sanitize_content(raw_content: list, node_id: str) -> tuple[list, int]:
    """Sanitize content elements. Returns (sanitized_list, num_filtered)."""
    from .models import make_action
    _VALID_FIELDS = {
        "scene_header": {"type", "location", "time", "characters"},
        "action": {"type", "text", "shot"},
        "dialogue": {"type", "speaker", "line", "emotion"},
        "narration": {"type", "text"},
        "namecard": {"type", "name", "title"},
    }
    _REQUIRED_FIELDS = {
        "scene_header": {"location", "time"},
        "action": {"text"},
        "dialogue": {"speaker", "line"},
        "narration": {"text"},
        "namecard": {"name", "title"},
    }
    sanitized = []
    filtered = 0
    for i, el in enumerate(raw_content):
        if not isinstance(el, dict) or "type" not in el:
            if isinstance(el, str) and el.strip():
                sanitized.append(make_action(el.strip()))
            else:
                filtered += 1
            continue
        etype = el["type"]
        valid = _VALID_FIELDS.get(etype)
        required = _REQUIRED_FIELDS.get(etype)
        if valid is None:
            log.debug("  Prose %s: skipping unknown element type %r at index %d", node_id, etype, i)
            filtered += 1
            continue
        if required and not all(isinstance(el.get(f), str) for f in required):
            log.warning("  Prose %s: element at index %d (type=%s) missing required fields — skipping",
                        node_id, i, etype)
            filtered += 1
            continue
        extra_keys = set(el.keys()) - valid
        if extra_keys:
            # Benign annotations (deepseek emits id/role on every element);
            # the element itself is well-formed — strip and keep.
            log.debug("  Prose %s: stripping extra keys %s at index %d (type=%s)",
                      node_id, extra_keys, i, etype)
            el = {k: v for k, v in el.items() if k in valid}
        sanitized.append(el)
    return sanitized, filtered


def _trace_all_paths_to(node_id: str, graph: Graph) -> list[list[str]]:
    """Return all root→node_id paths as lists of node IDs."""
    paths = []
    def _dfs(current: str, path: list[str]):
        if current == node_id:
            paths.append(list(path))
            return
        if current not in graph.nodes:
            return
        for c in graph.nodes[current].choices:
            if c.to not in path:  # avoid cycles
                path.append(c.to)
                _dfs(c.to, path)
                path.pop()
    _dfs(graph.root, [graph.root])
    return paths


def _build_incoming_edges_info(node: Node, graph: Graph) -> str:
    """Build a description of all incoming paths to this node for path-aware prose."""
    incoming = []
    for nid, n in graph.nodes.items():
        for c in n.choices:
            if c.to == node.id:
                incoming.append({
                    "from": nid,
                    "choice_label": c.label,
                    "resolution": list(c.resolution),
                    "source_summary": n.get_summary(),
                })
    if not incoming:
        return ""

    # Trace full paths to identify which characters/events are path-specific
    all_paths = _trace_all_paths_to(node.id, graph)
    path_summaries = []
    for path in all_paths:
        nodes_on_path = [nid for nid in path if nid != node.id and nid in graph.nodes]
        summaries = [f"{nid}: {graph.nodes[nid].get_summary()}" for nid in nodes_on_path if graph.nodes[nid].get_summary()]
        characters = set()
        for nid in nodes_on_path:
            for el in graph.nodes[nid].content:
                if isinstance(el, dict):
                    if el.get("type") == "namecard":
                        characters.add(el.get("name", ""))
                    elif el.get("type") == "dialogue":
                        characters.add(el.get("speaker", ""))
        path_summaries.append({
            "nodes": nodes_on_path,
            "summaries": summaries,
            "characters_introduced": sorted(c for c in characters if c),
        })

    lines = ["## Incoming paths (IMPORTANT: prose must work for ALL paths)"]
    for i, ps in enumerate(path_summaries):
        lines.append(f"\n### Path {i+1}: {' → '.join(ps['nodes'])} → {node.id}")
        for s in ps['summaries']:
            lines.append(f"  - {s}")
        if ps['characters_introduced']:
            lines.append(f"  Characters met on this path: {', '.join(ps['characters_introduced'])}")

    # Find characters that are path-specific (not on all paths)
    if len(path_summaries) > 1:
        all_char_sets = [set(ps['characters_introduced']) for ps in path_summaries]
        common_chars = set.intersection(*all_char_sets) if all_char_sets else set()
        all_chars = set.union(*all_char_sets) if all_char_sets else set()
        path_specific = all_chars - common_chars
        if path_specific:
            lines.append(f"\n⚠️ PATH-SPECIFIC characters (NOT available on all paths): {', '.join(sorted(path_specific))}")
            lines.append("You MUST NOT reference these characters by name or assume the reader has met them.")
            lines.append("If you need to introduce any of them, do so as a fresh first encounter.")

    lines.append("")
    lines.append(
        "CRITICAL: Do NOT reference events, characters, or items that only happen on one incoming path. "
        "The reader may have arrived via ANY of the paths above."
    )
    return "\n".join(lines)


def fix_summary_violations(
    node: Node, graph: Graph, violation_feedback: str, params: Params,
) -> str | None:
    """Fix a node's summary to remove ungrounded assertions flagged by semantic validation.

    Called when prose regen has failed 2+ times for the same node — the issue is
    in the summary itself, not just the prose.

    Returns fixed summary, or None if no fix needed / failed.
    """
    # Build context: what prior nodes establish
    parents = [pid for pid, pn in graph.nodes.items()
               for c in pn.choices if c.to == node.id]
    parent_info = []
    for pid in parents:
        pn = graph.nodes[pid]
        parent_info.append({
            "id": pid,
            "summary": pn.get_summary() or "",
            "produces": [{"fact": e.fact, "value": e.value} for e in (pn.produces or [])],
        })

    system = """You are a story editor fixing ungrounded assertions in an interactive story node's summary.

The semantic validator found violations that persist after multiple prose regenerations.
The issue is in the SUMMARY itself — it asserts things that aren't established by prior nodes.

Fix the summary by:
1. Removing or replacing assertions about character knowledge/actions that aren't grounded
2. Keeping the same dramatic arc and core events
3. Making dialogue/confrontation points rely only on what prior nodes establish
4. If a character confronts the protagonist, the confrontation reason must be grounded in prior events

Return JSON: {"fixed_summary": "...the fixed summary..."}"""

    user = f"""## Node: {node.id} (kind={node.kind}, ending={node.ending})
Current summary: {node.get_summary()}

## Prior nodes that can reach this node:
{json.dumps(parent_info, ensure_ascii=False, indent=2)}

## Violations to fix:
{violation_feedback}

Rewrite the summary to remove the ungrounded assertions while keeping the same dramatic structure."""

    try:
        data = _call_json(
            system, user, params,
            context="summary_violation_fix", cacheable=False,
            schema=_SUMMARY_VIOLATION_FIX_SCHEMA,
        )
        fixed = data.get("fixed_summary", "")
        if fixed and fixed != node.get_summary():
            return fixed
    except Exception as e:
        log.warning(f"  Summary violation fix failed for {node.id}: {e}")
    return None


def fix_s4_question(
    node: Node, problem: str, params: Params,
) -> tuple[str, list[str]] | None:
    """Rewrite a node's question+choices to form a coherent inner dilemma.

    Returns (new_question, [label_a, label_b]) or None on failure.
    """
    choice_info = []
    for c in node.choices:
        choice_info.append({"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts})

    system = """You are an interactive story editor. Rewrite the question and choice labels to form a COHERENT inner dilemma.

Rules:
- question ≤ 30 Chinese characters, must be a character's inner conflict (not "如何应对/怎么办")
- Each label ≤ 8 Chinese characters, describes a player ACTION (different verbs)
- The question must frame the tension that the two choices resolve
- Keep the same narrative direction — don't change what happens, just how it's phrased

Return ONLY JSON: {"question": "...", "labels": ["动作A", "动作B"]}"""

    user = f"""Current node summary: {node.get_summary()}

Current question: {node.question}
Current choices: {json.dumps(choice_info, ensure_ascii=False)}

Problem: {problem}

Rewrite the question and labels to form a clear inner dilemma."""

    try:
        data = _call_json(
            system, user, params,
            context="s4_fix", cacheable=False,
            schema=_S4_FIX_SCHEMA,
        )
        q = data.get("question", "")
        labels = data.get("labels", [])
        if q and len(labels) >= 2:
            return q, labels[:2]
    except Exception as e:
        log.warning(f"  S4 LLM fix failed: {e}")
    return None


def recast_competing_goods(
    node: Node, defects: list, params: Params, goal_ids: list[str] | None = None,
) -> bool:
    """Recast a dominated/no-pull node's choices into competing goods, in place.

    Rewrites question + both labels + costs + goal_impacts so each option buys a
    DISTINCT positive good and forfeits the other. Mutates node.choices and
    node.question on success. Returns True if applied.
    """
    choice_info = [
        {"label": c.label, "cost": c.cost, "goal_impacts": c.goal_impacts}
        for c in node.choices
    ]
    defect_text = "; ".join(d for _, d in defects)
    goals_line = f"\n合法的 goal_impacts 键（只能用这些）：{goal_ids}" if goal_ids else ""

    system = """你是互动剧选择设计师。当前节点的两个选项是"被支配/无收获"的坏选择
（approach-avoidance：做大胆的事 vs 忍气吞声/同一目标不同手段）。把它重铸为
**竞争性收益（competing goods）**：两个选项各争取一个玩家都想要的、不同的正向收获，
选一个就放弃另一个。

规则：
- 先在本场景找两个都积极、玩家都想要、且不同的收获 A 和 B（财富/真相/情报/立威/
  盟友/时机/保命…）。选项1争取A（代价=失去B），选项2争取B（代价=失去A）。
- 每个 label ≤8字，动词开头的具体动作（争/夺/取/搜/护/换…），禁否定/忍让态度词。
- 两选项的 goal_impacts 必须各自有正项、方向相反（各得一目标、各舍一目标），互不支配。
- question ≤30字，含"还是"，两边都点名正向目标：「为A舍B，还是为B舍A？」
- 不改变剧情走向，只重新切分这一刻玩家在争取什么。""" + goals_line + """

只返回 JSON：{"question":"...","choices":[{"label":"...","gain":"...","cost":"...","goal_impacts":{...}},{...}]}"""

    user = f"""节点 summary：{node.get_summary()}

当前 question：{node.question}
当前 choices：{json.dumps(choice_info, ensure_ascii=False)}

问题：{defect_text}

把它重铸成两个竞争性收益的选择。"""

    try:
        data = _call_json(system, user, params, context="competing_goods_recast",
                          cacheable=False, schema=_COMPETING_GOODS_SCHEMA)
        q = data.get("question", "")
        new_choices = data.get("choices", [])
        if not q or len(new_choices) < 2:
            return False
        gid_set = set(goal_ids) if goal_ids else None
        for c, nc in zip(node.choices, new_choices[:2]):
            c.label = nc.get("label", c.label)
            c.cost = nc.get("cost", c.cost)
            gi = nc.get("goal_impacts", {}) or {}
            clean = {}
            for k, v in gi.items():
                k = _canonical_goal_key(str(k))
                if gid_set is not None and k not in gid_set:
                    continue
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                clean[k] = max(-1, min(1, iv))
            if clean:
                c.goal_impacts = clean
        node.question = q
        return True
    except Exception as e:
        log.warning("  competing-goods recast failed: %s", e)
        return False


def fill_prose(
    node: Node, bible: dict, params: Params,
    graph: Graph | None = None,
    violation_feedback: str | None = None,
    chapters_index: dict[int, str] | None = None,
    first_appearing: list[str] | None = None,
    known_characters: list[str] | None = None,
) -> list:
    """Fill detailed content for a single skeleton node. Returns content array.

    Uses CREATIVE_WRITING_PROSE.md instructions.
    Processes one node at a time — can be parallelized across nodes.

    If graph is provided, includes incoming edge info for path-aware prose.
    If violation_feedback is provided, includes it as guidance for regeneration.
    """
    # Build compact node skeleton for the prompt
    node_skeleton = {
        "id": node.id,
        "kind": node.kind,
        "skeleton": node.skeleton,
        "planned_duration_min": node.planned_duration_min,
        "entry_context": node.entry_context,
        "exit_context": node.exit_context,
        "ending": node.ending,
        "question": node.question,
        "choices": [
            {"label": c.label, "to": c.to, "resolution": list(c.resolution),
             "state_delta": [{"fact": e.fact, "value": e.value} for e in c.state_delta],
             "cost": c.cost, "goal_impacts": c.goal_impacts}
            for c in node.choices
        ],
        "produces": [{"fact": e.fact, "value": e.value, "beat": e.beat} for e in node.produces],
        "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
    }

    system = f"""{_CREATIVE_WRITING_PROSE_MD}"""

    # Build path-aware incoming edges info
    # For convergence nodes (>1 parent), do NOT show path details —
    # the LLM uses path info to infer and write path-specific content.
    # Instead, add a strict convergence warning.
    incoming_info = ""
    if graph is not None:
        parents = [pid for pid, pn in graph.nodes.items()
                   for c in pn.choices if c.to == node.id]
        if len(parents) > 1:
            # Extract character names from summary to whitelist
            bible_chars = set()
            if bible:
                for c in bible.get("characters", []):
                    name = c.get("name", "")
                    if name and name in node.get_summary():
                        bible_chars.add(name)
            char_list = "、".join(sorted(bible_chars)) if bible_chars else "(无具名角色)"
            incoming_info = (
                "## ⚠️ CONVERGENCE NODE WARNING — 严格限制\n"
                f"This node is reached from {len(parents)} different paths.\n"
                "You MUST write prose that works for ALL paths.\n\n"
                f"**允许出场的角色（仅限）**: {char_list}\n"
                "**绝对禁止**:\n"
                "- 不得出现上述白名单之外的任何角色（包括圣经中的其他角色）\n"
                "- 不得使用定指引用（'那人'、'此人'、'先前那位'）— 暗示读者已认识某人\n"
                "- 不得描写角色易容、变装等细节 — 某些读者可能不知道这些信息\n"
                "- 不得引用任何'证据'、'密信'、'线索'等具体物品 — 不同路径获得不同物品\n"
                "- 如果 summary 使用模糊表述（如'暗中相援之人'），prose 也必须保持模糊\n"
                "\n**开场必须 RECAP（汇合节点定位手法）**：第一个 scene_header 之后的 1-2 个"
                "元素必须是就地盘点式重述——角色在场内清点当前处境、风险与下一步打算"
                "（只用所有路径都成立的事实）。这既是路径中立的开场，也让观众重新定位。\n"
            )
        else:
            incoming_info = _build_incoming_edges_info(node, graph)

    # Build violation feedback section
    violation_section = ""
    if violation_feedback:
        forbidden = _extract_forbidden_phrases(violation_feedback)
        forbidden_section = ""
        if forbidden:
            forbidden_section = (
                "\nForbidden phrases/events inferred from feedback. Do not include these exact strings, "
                "close paraphrases, or back-references to the same prior event:\n"
                + "\n".join(f"- {p}" for p in forbidden[:12])
                + "\n"
            )
        violation_section = f"""
## HARD previous violations to fix
The previous prose for this node had the following problems. Fix them in this generation:
{violation_feedback}

{forbidden_section}
Rules for these violations:
- Treat feedback as higher priority than the bible and current wording.
- The forbidden list is a hard substring ban. Do not output any listed phrase verbatim.
- If feedback says a back-reference is unsupported, remove the back-reference completely.
- If feedback says a named character is not in known_characters, reader_has_seen, or guaranteed ancestors, do not mention that character's name at all in this node. Use a neutral local introduction such as "一名亲随" only if the skeleton supports it.
- Do not write "previously", "again", "still", "that same", "earlier", or equivalent wording unless it is guaranteed in the node skeleton/requires.
- Do not use "认出", "再见", "仍旧", "早已", "旧识", "熟悉", or equivalent recognition wording for any person/item unless guaranteed by requires or ancestors.
- If the event must happen, write it as happening NOW in this node, not as something that already happened.
"""

    # For convergence nodes, filter bible to only whitelisted characters
    compact = _compact_bible(bible)
    if graph is not None:
        parents = [pid for pid, pn in graph.nodes.items()
                   for c in pn.choices if c.to == node.id]
        if len(parents) > 1 and compact.get("characters"):
            summary_text = node.get_summary()
            compact["characters"] = [
                c for c in compact["characters"]
                if c.get("name", "") and c["name"] in summary_text
            ]

    # B3: aftermath/target no-overlap — show each choice's target opening so
    # the aftermath stops BEFORE it (aftermath = transition; target owns the event)
    aftermath_boundaries = ""
    if graph is not None and node.choices:
        lines = []
        for c in node.choices:
            tgt = graph.nodes.get(c.to)
            if not tgt:
                continue
            opening = []
            for el in (tgt.skeleton or []):
                if isinstance(el, dict) and el.get("type") != "scene_header":
                    t = (el.get("text") or el.get("line") or "")[:50]
                    if t:
                        opening.append(t)
                if len(opening) >= 2:
                    break
            if opening:
                lines.append(f"- 选择「{c.label}」之后的下一场从这里开始：{' / '.join(opening)}")
        if lines:
            aftermath_boundaries = (
                "## Aftermath 边界（硬性）\n"
                "每个 aftermath 必须停在对应下一场的开场之前——绝不可重复或预演下一场"
                "已包含的事件（事件归下一场所有，aftermath 只写选择的即时后果与过渡）：\n"
                + "\n".join(lines) + "\n\n"
            )

    # W1: source-text borrowing — the original novel owns dialogue/humor/detail
    source_section = ""
    if chapters_index:
        span_texts = []
        total = 0
        for ch in range(node.chapters[0], node.chapters[1] + 1):
            t = chapters_index.get(ch, "")
            if t:
                span_texts.append(f"--- 第{ch}章 ---\n{t}")
                total += len(t)
            if total > 6000:
                break
        if span_texts:
            source_section = (
                "## 原著片段（本节点对应章节）\n"
                "优先借用原文的对白、比喻、幽默感与场景细节——原文的语言质感高于你的默认文风。\n"
                "硬性边界：只为骨架已包含的事件借用文字；禁止从原文引入骨架之外的新剧情、新人物、新物品。\n\n"
                + "\n".join(span_texts)[:6500] + "\n"
            )

    # W4: per-playthrough first-appearance (computed from graph memory)
    cast_section = ""
    namecard_section = ""
    if first_appearing is not None or known_characters is not None:
        cast_section = (
            "## 角色出场状态（由全图计算，必须遵守）\n"
            f"本节点首次出场（必须加 namecard 并自然引入）: {json.dumps(first_appearing or [], ensure_ascii=False)}\n"
            f"观众已认识（禁止 namecard、禁止重复自我介绍）: {json.dumps(known_characters or [], ensure_ascii=False)}\n"
        )
    if first_appearing:
        char_by_name = {
            str(c.get("name", "")): c
            for c in (compact.get("characters") or [])
            if isinstance(c, dict) and c.get("name")
        }
        checklist_lines = []
        for name in first_appearing:
            ch = char_by_name.get(name, {})
            role = str(ch.get("role", "")).strip()
            desc = str(ch.get("description", "")).strip()
            meta = " / ".join([x for x in (role, desc) if x])
            if meta:
                checklist_lines.append(f"- {name}: {meta}")
            else:
                checklist_lines.append(f"- {name}")
        namecard_section = (
            "## 必写 namecard 清单（硬性）\n"
            "下面这些角色在本节点必须各自出现一次 namecard，且必须早于其第一句对白/首次关键动作。\n"
            "不要把它们留给后续重试，也不要只靠 scene_header 里的角色名单代替。\n"
            + "\n".join(checklist_lines) + "\n\n"
        )

    user = f"""## Compact bible
{json.dumps(compact, ensure_ascii=False, indent=2)}

## Node skeleton
{json.dumps(node_skeleton, ensure_ascii=False, indent=2)}

{source_section}
{cast_section}
{namecard_section}
{incoming_info}
{violation_section}
Write detailed structured content for this single node.
Expand from "thin_content": preserve every plot beat, fact, character, and choice setup it contains.
You may add camera language, pacing, sensory detail, and fuller dialogue, but you must not add new plot events.
Target richness: about 360-480 Chinese text chars per planned_duration_min minute; non-terminal scenes should feel shootable and dialogue-rich, not like a synopsis.
For prologue nodes, after the first scene_header, include a fuller background narration that names the protagonist's modern-agent/modern-person identity when supported by the bible or summary.
{aftermath_boundaries}## Aftermath 支线段落（非结局节点必须输出）
For EVERY choice, also write an "aftermaths" entry: 3-6 dramatized elements (action/dialogue/narration)
showing the IMMEDIATE consequence of that choice — played at the end of this node after the player selects.
- 戏剧化呈现，不是概述：把 resolution 两拍扩成可拍摄的小场景（关键对白、动作、对手反应）。
- 路径专属内容写在这里（汇合目标节点必须保持路径中立）；持久后果只能通过 state_delta 携带。
- label 必须与 choices 中的 label 一字不差。结局节点输出 "aftermaths": []。

Return ONLY valid JSON: {{"content": [...], "aftermaths": [{{"label": "...", "elements": [...]}}]}}
CRITICAL: "content" MUST be a JSON array of objects, not a string, not markdown, not screenplay text encoded as one string."""

    max_attempts = JSON_RETRY_ATTEMPTS
    for attempt in range(max_attempts):
        log.info("  Prose fill %s attempt %d/%d", node.id, attempt + 1, max_attempts)
        try:
            data = _call_json(
                system, user, params,
                context=f"prose {node.id}" + (f" (attempt {attempt+1})" if attempt > 0 else ""),
                schema=_PROSE_FILL_SCHEMA,
            )
        except json.JSONDecodeError as e:
            log.warning("  Prose fill for %s failed JSON parse: %s", node.id, e)
            if attempt < max_attempts - 1:
                continue
            return []

        raw_content = data.get("content", [])
        if not isinstance(raw_content, list):
            log.warning("  Prose fill for %s: content is %s, not list", node.id, type(raw_content).__name__)
            if attempt < max_attempts - 1:
                continue
            return []

        sanitized, filtered = _sanitize_content(raw_content, node.id)

        # Auto-regen if >20% of elements were corrupted (#4)
        if raw_content and filtered / len(raw_content) > 0.2:
            log.warning("  Prose %s: %d/%d elements corrupted (%.0f%%) — %s",
                        node.id, filtered, len(raw_content),
                        100 * filtered / len(raw_content),
                        "retrying" if attempt < max_attempts - 1 else "accepting")
            if attempt < max_attempts - 1:
                continue

        # Enforce the duration-scaled length floor HERE, on every candidate —
        # regens with violation feedback otherwise silently shrink prose and
        # the D9 length check only catches it at final validation.
        import re as _re

        from .models import render_content_to_text
        text = render_content_to_text(sanitized)
        text_len = len(_re.sub(r"\s+", "", text))
        duration = float(getattr(node, "planned_duration_min", 0) or 0)
        if node.ending == "DEAD_END":
            min_len = max(120, int(duration * 150))
        else:
            min_len = max(420, int(duration * 220))
        if text_len < min_len:
            log.warning("  Prose %s: %d chars < floor %d — %s",
                        node.id, text_len, min_len,
                        "retrying with length feedback" if attempt < max_attempts - 1
                        else "accepting (final validation will self-heal)")
            # A short response must not be replayed from cache on a future run
            invalidate_cached_response(system, user, _PROSE_FILL_SCHEMA, None)
            if attempt < max_attempts - 1:
                user = user + (f"\n\n## LENGTH REQUIREMENT (attempt {attempt + 2})\n"
                               f"上一版只有 {text_len} 字，必须≥{min_len} 字。"
                               f"保持剧情节拍不变，用更充分的动作、对白与氛围细节扩写。")
                continue

        # W3: apply per-choice aftermath blocks (success path only). Each
        # aftermath plays at the END of this node after the player selects.
        raw_aftermaths = data.get("aftermaths", [])
        if isinstance(raw_aftermaths, list) and node.choices:
            by_label = {}
            for am in raw_aftermaths:
                if isinstance(am, dict) and isinstance(am.get("elements"), list):
                    cleaned, _ = _sanitize_content(am["elements"], node.id)
                    if cleaned:
                        by_label[str(am.get("label", ""))] = cleaned
            for choice in node.choices:
                if choice.label in by_label:
                    choice.aftermath = by_label[choice.label]
            missing = [c.label for c in node.choices if not c.aftermath]
            if missing:
                log.warning("  Prose %s: missing aftermath for choices %s",
                            node.id, missing)

        return sanitized
    return []


def _extract_forbidden_phrases(feedback: str) -> list[str]:
    """Extract short quoted fragments from semantic feedback for negative prompts."""
    import re
    phrases: list[str] = []
    for pattern in (r"'([^']{2,80})'", r'"([^"]{2,80})"', r"「([^」]{2,80})」", r"“([^”]{2,80})”"):
        for match in re.findall(pattern, feedback):
            text = match.strip()
            if text and text not in phrases:
                phrases.append(text)
    for keyword in ("之前打断", "先前打断", "打断过", "那只手", "旧伤", "再次"):
        if keyword in feedback and keyword not in phrases:
            phrases.append(keyword)
    return phrases
