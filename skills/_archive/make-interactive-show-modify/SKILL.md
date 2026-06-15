---
name: make-interactive-show-modify
description: "Modify an existing interactive show script based on notes/feedback. Reads from a previously produced project state."
---

# /make-interactive-show-modify

Modify an existing interactive show by loading its project state and applying changes.

## Arguments

| Arg | Required | Default | Example |
|-----|----------|---------|---------|
| `--file` | Yes | - | Path to `state.json` or the project directory |
| `--note` | Yes | - | `"make the protagonist braver, add subplot"` |
| `--episodes` | No | keep | Change episode count |
| `--lang` | No | keep | Change language |

## Execution

### Step 1: Load state

Read the state.json from `--file` (if it's a directory, look for `state.json` inside it; if it's the PDF, look for `state.json` in the same directory or a sibling `project/` folder).

Print a summary of what exists: title, episodes, total choices, endings.

### Step 2: Analyze the modification request

Read the `--note` carefully. Determine which parts of the show need to change:

- **Character changes** → update story_bible.characters + `optional_characters` (if recruitment affected), then regenerate affected scripts
- **Tone/style changes** → regenerate all scripts with new creative direction, update `satisfaction_beats` to match new tone
- **Plot changes** → update story_bible, restructure episodes if needed, update `ability_registry` / `consequence_ledger` / `power_curve`, regenerate scripts
- **Structure changes** → update structure.json + `entry_state`/`exit_state` for affected episodes, regenerate affected scripts
- **Add/remove episodes** → restructure, update `power_curve` + episode transitions, regenerate
- **Ability/power changes** → update `ability_registry`, verify downstream usage, update `power_curve`

**Impact analysis**: For each change, trace downstream effects:
1. Does this change affect `ability_registry`? (new ability introduced/removed)
2. Does this change affect `optional_characters`? (character recruitment changed)
3. Does this change break any `consequence_ledger` entries? (delayed effects disrupted)
4. Does this change break `entry_state`/`exit_state` continuity between episodes?
5. Does this change remove any `satisfaction_beats`? (must ensure each episode still has ≥ 1)

Tell the user what you plan to change before proceeding. Use AskUserQuestion if the scope is ambiguous.

### Step 3: Apply modifications

For each affected component:
1. Update story_bible.json if world/character changes are needed
2. Update structure.json if episode/choice structure changes
3. Regenerate affected episode scripts (use Task agents for parallelism)
4. Keep unchanged scripts as-is

### Step 4: VERIFY consistency

Same verification process as /make-interactive-show Step 7 (all 6 rounds):

**基础校验（Rounds 1-3）**:
- 脚本 → 结构一致性（场景编号、决策点、跳转目标）
- 脚本 → 故事圣经一致性（角色名、世界观）
- 交叉校验（structure.json ↔ story_bible.json）

**因果校验（Rounds 4-6）**:
- **能力因果**：修改涉及新能力/武器时，验证 `ability_registry` 是否更新，使用时机是否在引入之后
- **可选角色与后果兑现**：修改涉及角色加入/离开时，验证 `optional_characters` 和 `consequence_ledger` 是否同步更新，受影响集的差异化处理是否完整
- **力量曲线与过渡**：修改涉及战斗/能力场景时，验证 `power_curve` 增幅合理，相邻集 `exit_state` → `entry_state` 连续
- **爽点校验**：验证修改后每集仍有 ≥ 1 个爽点，`satisfaction_beats` 是否需要更新

**脚本是源真相。** 不一致 → 更新 structure.json / story_bible.json 以匹配脚本。重复直到零不一致。

### Step 5: Re-render

Update state.json with all changes, then run the renderer:

```bash
SKILL_DIR="/Users/biubiu/projects/interactive-show-producer/skills/make-interactive-show"
python "$SKILL_DIR/lib/renderer.py" "$PROJECT_DIR"
```

### Step 6: Report

Show the user:
1. What was changed (diff summary)
2. Updated file locations
3. Verification results
