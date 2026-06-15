"""LLM-as-judge validation for step-2 (expansion) and step-3 (scripts).

30 questions total: 15 per step.  Each question is scored pass/fail by the
LLM with reasoning.  Hard-fail triggers a retry; soft-fail is logged as a
warning.

No LLM calls happen here — this module builds prompts, parses responses,
and formats retry feedback.  The caller (SKILL.md executor) makes the
actual LLM call.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ── Data structures ──────────────────────────────────────────────────

@dataclass
class JudgeQuestion:
    id: str                                    # "S2_OBJ_01"
    category: str                              # "OBJECT_TRACKING"
    text_zh: str                               # question text (Chinese)
    severity: Literal["hard", "soft"] = "hard" # both hard and soft trigger retry
    step: Literal["step-2", "step-3"] = "step-2"
    context_keys: list[str] = field(default_factory=list)  # which context fields needed
    condition: str = ""                        # optional: only ask if condition met (e.g. "prologue")


@dataclass
class JudgeVerdict:
    question_id: str
    answer: bool          # True = pass, False = fail
    reasoning: str = ""
    severity: Literal["hard", "soft"] = "soft"


@dataclass
class JudgeReport:
    target_id: str               # node ID or script ID
    step: str                    # "step-2" or "step-3"
    verdicts: list[JudgeVerdict] = field(default_factory=list)
    hard_fails: list[str] = field(default_factory=list)    # question IDs
    soft_fails: list[str] = field(default_factory=list)
    retry_needed: bool = False   # True if any fail (hard or soft)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "step": self.step,
            "verdicts": [asdict(v) for v in self.verdicts],
            "hard_fails": self.hard_fails,
            "soft_fails": self.soft_fails,
            "retry_needed": self.retry_needed,
        }


# ── Step-2 questions (per node expansion) ────────────────────────────

S2_QUESTIONS: list[JudgeQuestion] = [
    # OBJECT tracking
    JudgeQuestion(
        id="S2_OBJ_01", category="OBJECT",
        text_zh="节拍中提及的物品或概念（武器、信件、密道等）是否都有前置引入？即：每个物品在被使用前，是否在先前节拍、圣经、或路径历史中出现过？",
        severity="hard", step="step-2",
        context_keys=["parent_beats", "path_content", "bible"],
    ),
    JudgeQuestion(
        id="S2_OBJ_02", category="OBJECT",
        text_zh="依赖状态变量的物品（如 has_sword=true 才有剑）是否与 guaranteed_state 一致？是否存在引用了 varying_state 中才有的物品？",
        severity="hard", step="step-2",
        context_keys=["guaranteed_state", "varying_state"],
    ),
    JudgeQuestion(
        id="S2_OBJ_03", category="OBJECT",
        text_zh="已经被消耗、摧毁或交出的物品是否正确缺席？（例如已烧毁的信件不应再次出现）",
        severity="hard", step="step-2",
        context_keys=["path_content", "accumulated_state"],
    ),
    # CHOICE quality
    JudgeQuestion(
        id="S2_CHO_01", category="CHOICE",
        text_zh="parent_beats 的最后一条是否为未解决的张力顶点（主角被逼入困境，需要立即抉择），而非已经释放的结果？",
        severity="hard", step="step-2",
        context_keys=["parent_beats"],
    ),
    JudgeQuestion(
        id="S2_CHO_02", category="CHOICE",
        text_zh="choice_question 是否与节拍到达的场景状态一致？（问题描述的困境是否确实存在于节拍结尾？）",
        severity="hard", step="step-2",
        context_keys=["parent_beats", "choice_question"],
    ),
    JudgeQuestion(
        id="S2_CHO_03", category="CHOICE",
        text_zh="各选择是否都是主角的主动行动抉择（而非被动遭遇或结果描述）？测试：「我选择{label}」是否通顺？",
        severity="hard", step="step-2",
        context_keys=["edges"],
    ),
    # CONTINUITY
    JudgeQuestion(
        id="S2_CON_01", category="CONTINUITY",
        text_zh="每个子节点的 entry_context 是否从父节点的 exit_context + edge resolution 可以自然到达？（不存在无桥接的时间/地点跳跃）",
        severity="hard", step="step-2",
        context_keys=["parent_exit_context", "nodes", "edges"],
    ),
    JudgeQuestion(
        id="S2_CON_02", category="CONTINUITY",
        text_zh="每条 edge 的 resolution 是否有效桥接了父场景到子场景？（是否展示了选择的直接后果，并过渡到下一个场景？）",
        severity="hard", step="step-2",
        context_keys=["edges", "nodes"],
    ),
    JudgeQuestion(
        id="S2_CON_03", category="CONTINUITY",
        text_zh="子节点的第一条 beat 是否从 edge resolution 之后开始？（没有重复叙述 resolution 中已经发生的事）",
        severity="soft", step="step-2",
        context_keys=["edges", "nodes"],
    ),
    JudgeQuestion(
        id="S2_CON_04", category="CONTINUITY",
        text_zh="所有出现的角色是否都在圣经角色列表或先前节拍中已经出现过？（没有凭空冒出的新角色）",
        severity="hard", step="step-2",
        context_keys=["bible", "path_content", "parent_beats", "nodes"],
    ),
    # STATE coherence
    JudgeQuestion(
        id="S2_STA_01", category="STATE",
        text_zh="edge effects（状态变更）是否与 resolution 描述的剧情一致？（例如：resolution 说主角拿到了剑，effects 中是否有 has_sword=true？）",
        severity="hard", step="step-2",
        context_keys=["edges"],
    ),
    JudgeQuestion(
        id="S2_STA_02", category="STATE",
        text_zh="是否避免了在节拍/摘要中引用 varying_state 中的事件或物品？（这些在不同路径上可能不存在）",
        severity="hard", step="step-2",
        context_keys=["varying_state", "parent_beats", "nodes"],
    ),
    JudgeQuestion(
        id="S2_STA_03", category="STATE",
        text_zh="内容是否与 bible 中的 canon_facts 一致？（没有矛盾之处）",
        severity="hard", step="step-2",
        context_keys=["bible"],
    ),
    # DRAMA
    JudgeQuestion(
        id="S2_DRA_01", category="DRAMA",
        text_zh="情节是否朝着下一个 bottleneck 推进（或有意地远离它形成死胡同），而非在原地转圈？",
        severity="soft", step="step-2",
        context_keys=["next_bottleneck", "nodes"],
    ),
    JudgeQuestion(
        id="S2_DRA_02", category="DRAMA",
        text_zh="每条 beat 是否包含了：谁（角色名）、为什么（动机）、做了什么（行动）、在哪里/何时（场景）？",
        severity="soft", step="step-2",
        context_keys=["parent_beats", "nodes"],
    ),
]


# ── Step-3 questions (per script) ────────────────────────────────────

S3_QUESTIONS: list[JudgeQuestion] = [
    # ALIGNMENT (script ↔ beats)
    JudgeQuestion(
        id="S3_ALI_01", category="ALIGNMENT",
        text_zh="脚本是否按顺序戏剧化了该节点的所有 beats？（每条 beat 都有对应的场景/台词段落）",
        severity="hard", step="step-3",
        context_keys=["beats", "script"],
    ),
    JudgeQuestion(
        id="S3_ALI_02", category="ALIGNMENT",
        text_zh="脚本是否避免了 beats 之外的额外情节事件？（没有自创重大剧情）",
        severity="hard", step="step-3",
        context_keys=["beats", "script"],
    ),
    JudgeQuestion(
        id="S3_ALI_03", category="ALIGNMENT",
        text_zh="选择区块（选择 NNN / 问题 / 选项）是否与 DAG 的出边完全一致？（选项数、目标节点、标签都匹配）",
        severity="hard", step="step-3",
        context_keys=["edges", "script"],
    ),
    # TENSION
    JudgeQuestion(
        id="S3_TEN_01", category="TENSION",
        text_zh="选择点处是否有未解决的张力？（选择前的内容没有提前解决冲突）",
        severity="hard", step="step-3",
        context_keys=["script"],
    ),
    JudgeQuestion(
        id="S3_TEN_02", category="TENSION",
        text_zh="问题行（问题：xxx）与脚本到该点的状态是否一致？（问题描述的情境确实存在于脚本中）",
        severity="hard", step="step-3",
        context_keys=["script", "choice_question"],
    ),
    # NAMING
    JudgeQuestion(
        id="S3_NAM_01", category="NAMING",
        text_zh="脚本中的人名、地名、术语是否与 bible 一致？（没有写错名字或用了不同称呼）",
        severity="hard", step="step-3",
        context_keys=["bible", "script"],
    ),
    JudgeQuestion(
        id="S3_NAM_02", category="NAMING",
        text_zh="重复出现的概念是否使用了相同的术语？（没有同一物品用不同名字）",
        severity="soft", step="step-3",
        context_keys=["script", "parent_scripts"],
    ),
    # CHARACTER
    JudgeQuestion(
        id="S3_CHR_01", category="CHARACTER",
        text_zh="所有在场景中活跃的角色是否都在 人：头部列出？",
        severity="soft", step="step-3",
        context_keys=["script"],
    ),
    JudgeQuestion(
        id="S3_CHR_02", category="CHARACTER",
        text_zh="首次出场的重要角色是否有【人物卡】？",
        severity="soft", step="step-3",
        context_keys=["script", "parent_scripts", "bible"],
    ),
    JudgeQuestion(
        id="S3_CHR_03", category="CHARACTER",
        text_zh="角色是否拥有不可能的知识或物品？（例如：角色不应知道他们没有参与的事件）",
        severity="hard", step="step-3",
        context_keys=["script", "guaranteed_state", "varying_state"],
    ),
    # SCENE
    JudgeQuestion(
        id="S3_SCN_01", category="SCENE",
        text_zh="脚本的开场（第一个▲段落和场/景/时头部）是否与节点的 entry_context 一致？",
        severity="hard", step="step-3",
        context_keys=["script", "entry_context"],
    ),
    JudgeQuestion(
        id="S3_SCN_02", category="SCENE",
        text_zh="EP01（prologue）是否以旁白开场建立世界观？（以「旁白：」开头的段落描述世界背景）",
        severity="hard", step="step-3",
        context_keys=["script"],
        condition="prologue",
    ),
    # FORMAT
    JudgeQuestion(
        id="S3_FMT_01", category="FORMAT",
        text_zh="选择区块格式是否正确？（选择 NNN + 问题：xxx + 选项 NNN-A/B/C 格式完整）",
        severity="hard", step="step-3",
        context_keys=["script"],
    ),
    JudgeQuestion(
        id="S3_FMT_02", category="FORMAT",
        text_zh="脚本中是否不含模板残留物？（如「（≤8字）」「[待填写]」「xxx」等占位符）",
        severity="hard", step="step-3",
        context_keys=["script"],
    ),
    JudgeQuestion(
        id="S3_SCN_03", category="SCENE",
        text_zh="舞台指示（▲段落）是否有影视感？（包含镜头提示如特写/中景/全景，有画面感的动作描写）",
        severity="soft", step="step-3",
        context_keys=["script"],
    ),
]


# ── Filtering ────────────────────────────────────────────────────────

def filter_questions_for_node(
    questions: list[JudgeQuestion],
    node_kind: str,
) -> list[JudgeQuestion]:
    """Filter questions based on node kind (handles conditional questions)."""
    result = []
    for q in questions:
        if q.condition:
            if q.condition == "prologue" and node_kind != "prologue":
                continue
        result.append(q)
    return result


# ── Prompt building ──────────────────────────────────────────────────

def build_judge_prompt(
    questions: list[JudgeQuestion],
    context: dict[str, Any],
) -> str:
    """Build the LLM judge prompt from questions + context.

    The judge receives context and answers each question with
    {"answer": true/false, "reasoning": "..."}.
    """
    lines = [
        "你是一位互动影游脚本质量审核员。请根据以下上下文，逐一回答每个审核问题。",
        "",
        "## 审核上下文",
        "",
    ]

    # Add context sections
    for key, value in context.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"### {key}")
            lines.append("```json")
            lines.append(json.dumps(value, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        elif isinstance(value, str) and len(value) > 100:
            lines.append(f"### {key}")
            lines.append(value)
            lines.append("")
        else:
            lines.append(f"- **{key}**: {value}")

    lines.append("")
    lines.append("## 审核问题")
    lines.append("")

    for q in questions:
        severity_tag = "🔴 硬性" if q.severity == "hard" else "🟡 建议"
        lines.append(f"**{q.id}** [{severity_tag}] [{q.category}]")
        lines.append(f"  {q.text_zh}")
        lines.append("")

    lines.append("## 输出格式")
    lines.append("")
    lines.append("请以 JSON 对象输出，每个问题 ID 为 key：")
    lines.append("```json")
    lines.append("{")
    sample_ids = [q.id for q in questions[:2]]
    for sid in sample_ids:
        lines.append(f'  "{sid}": {{"answer": true, "reasoning": "通过原因"}},')
    lines.append("  ...")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("- answer: true = 通过, false = 不通过")
    lines.append("- reasoning: 简要说明原因（中文，1-2句）")
    lines.append("")
    lines.append("只输出 JSON，不要其他内容。")

    return "\n".join(lines)


# ── Context builders ─────────────────────────────────────────────────

def build_step2_judge_context(
    expansion: dict[str, Any],
    prompt_context: dict[str, Any],
) -> dict[str, Any]:
    """Build context dict for step-2 LLM judge from expansion output + prompt context."""
    ctx: dict[str, Any] = {}

    # From expansion output
    ctx["parent_beats"] = expansion.get("parent_beats", [])
    ctx["parent_exit_context"] = expansion.get("parent_exit_context", "")
    ctx["choice_question"] = expansion.get("choice_question", "")
    ctx["nodes"] = expansion.get("nodes", [])
    ctx["edges"] = expansion.get("edges", [])

    # From prompt context
    ctx["accumulated_state"] = prompt_context.get("accumulated_state", {})
    ctx["guaranteed_state"] = prompt_context.get("guaranteed_state", {})
    ctx["varying_state"] = prompt_context.get("varying_state", {})
    ctx["next_bottleneck"] = prompt_context.get("next_bottleneck")
    ctx["path_content"] = prompt_context.get("path_content", [])

    # Bible (compact)
    if "bible" in prompt_context:
        ctx["bible"] = prompt_context["bible"]

    return ctx


def build_step3_judge_context(
    script: str,
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    bible: dict[str, Any] | None,
    guaranteed_state: dict[str, Any],
    varying_state: dict[str, list[Any]],
    parent_scripts: dict[str, str] | None = None,
    chapter_excerpts: list[str] | None = None,
) -> dict[str, Any]:
    """Build context dict for step-3 LLM judge."""
    ctx: dict[str, Any] = {
        "script": script,
        "node_id": node.get("id", ""),
        "node_kind": node.get("kind", "scene"),
        "beats": node.get("beats", []),
        "entry_context": node.get("entry_context", ""),
        "exit_context": node.get("exit_context", ""),
        "choice_question": node.get("choice_question", ""),
        "edges": edges,
        "guaranteed_state": guaranteed_state,
        "varying_state": varying_state,
    }
    if bible:
        ctx["bible"] = bible
    if parent_scripts:
        ctx["parent_scripts"] = parent_scripts
    if chapter_excerpts:
        ctx["chapter_excerpts"] = chapter_excerpts
    return ctx


# ── Response parsing ─────────────────────────────────────────────────

def parse_judge_response(
    raw: str,
    questions: list[JudgeQuestion],
    target_id: str,
    step: str,
) -> JudgeReport:
    """Parse LLM judge response JSON into a JudgeReport.

    Tolerant: extracts JSON from markdown code blocks, handles partial responses.
    """
    # Extract JSON from possible markdown code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if json_match:
        raw_json = json_match.group(1).strip()
    else:
        # Try the whole string as JSON
        raw_json = raw.strip()

    # Parse
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        # Fallback: treat everything as failed (will trigger retry)
        return JudgeReport(
            target_id=target_id,
            step=step,
            verdicts=[],
            hard_fails=[q.id for q in questions if q.severity == "hard"],
            soft_fails=[q.id for q in questions if q.severity == "soft"],
            retry_needed=True,
        )

    question_map = {q.id: q for q in questions}
    verdicts: list[JudgeVerdict] = []
    hard_fails: list[str] = []
    soft_fails: list[str] = []

    for q in questions:
        entry = data.get(q.id, {})
        if isinstance(entry, dict):
            answer = bool(entry.get("answer", True))
            reasoning = str(entry.get("reasoning", ""))
        elif isinstance(entry, bool):
            answer = entry
            reasoning = ""
        else:
            answer = True  # missing = assume pass
            reasoning = "未回答"

        verdict = JudgeVerdict(
            question_id=q.id,
            answer=answer,
            reasoning=reasoning,
            severity=q.severity,
        )
        verdicts.append(verdict)

        if not answer:
            if q.severity == "hard":
                hard_fails.append(q.id)
            else:
                soft_fails.append(q.id)

    return JudgeReport(
        target_id=target_id,
        step=step,
        verdicts=verdicts,
        hard_fails=hard_fails,
        soft_fails=soft_fails,
        retry_needed=len(hard_fails) > 0 or len(soft_fails) > 0,
    )


# ── Retry feedback ───────────────────────────────────────────────────

def format_retry_feedback(report: JudgeReport) -> str:
    """Format a JudgeReport into feedback for the LLM to fix issues on retry."""
    lines = [
        "## 质量审核反馈 — 需要修改",
        "",
    ]

    if report.hard_fails:
        lines.append("### 🔴 必须修正（硬性要求）")
        lines.append("")
        for v in report.verdicts:
            if v.question_id in report.hard_fails:
                lines.append(f"- **{v.question_id}**: {v.reasoning}")
        lines.append("")

    if report.soft_fails:
        lines.append("### 🟡 必须修正（质量要求）")
        lines.append("")
        for v in report.verdicts:
            if v.question_id in report.soft_fails:
                lines.append(f"- **{v.question_id}**: {v.reasoning}")
        lines.append("")

    lines.append("请修正以上所有问题后重新输出。硬性要求和质量要求都必须通过。")
    return "\n".join(lines)
