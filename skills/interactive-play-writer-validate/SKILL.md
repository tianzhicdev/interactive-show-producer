---
name: interactive-play-writer-validate
description: "Standalone validation gate: runs IO + LLM judge on a state.json, produces pass/warn/fail report."
---

# /interactive-play-writer-validate — Validation Gate

Run comprehensive validation on a state.json to determine if it can proceed to the next step. Combines deterministic IO checks with semantic LLM judge checks.

## Parameters

| Parameter | Required | Default | Example |
|-----------|----------|---------|---------|
| `--state` | Yes | - | `~/Downloads/play_spine_xxx/state.json` |
| `--step` | No | auto-detect | `step-2`, `step-3` |
| `--output` | No | same dir as state.json | `/path/to/output` |

## Gate Rules

- **step-2 → step-3**: must PASS or WARN to proceed to script writing
- **step-3 → step-4 (upload)**: must PASS or WARN to proceed to database import
- **FAIL** = any hard-fail LLM question OR any blocking IO error → cannot proceed
- **WARN** = soft-fails only → proceed with warnings logged
- **PASS** = all checks pass → proceed

## Execution Phases

### Phase 1: LOAD

```python
import sys
sys.path.insert(0, "skills/interactive-play-writer/lib")
from data_model import load_state
from validate_comprehensive import build_validation_prompts, build_report, format_report_md

state = load_state(project_dir)
step = args.get("step") or state.step
```

### Phase 2: IO VALIDATION

Run the deterministic validator:

```python
from validate_spine import validate_spine

io_result = validate_spine(state)
# io_result has: ok, errors (list of (category, message)), warnings, advisory
```

If IO validation has blocking errors, log them. Continue to LLM validation anyway
to provide a complete report.

### Phase 3: LLM VALIDATION

Build and execute LLM judge prompts for each node:

```python
prompt_tasks = build_validation_prompts(state, step=step)

# Execute in parallel (Task agents, up to 5 concurrent):
llm_reports = {}
for task in prompt_tasks:
    # LLM CALL: task["prompt"] → raw response
    report = parse_judge_response(raw, task["questions"], task["node_id"], task["step"])
    llm_reports[task["node_id"]] = report
```

For efficiency, batch nodes into parallel groups of up to 5.

### Phase 4: REPORT

Merge IO and LLM results into a unified report:

```python
report = build_report(state, io_result_dict, llm_reports, step=step)

# Save report
import json
report_path = f"{output_dir}/validation_report.json"
with open(report_path, "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# Save human-readable markdown
md_path = f"{output_dir}/validation_report.md"
with open(md_path, "w") as f:
    f.write(format_report_md(report))

# Also store in state for downstream gate checks
state.validation_reports[step] = report
save_state(state, project_dir)
```

### Phase 5: GATE

Announce the result:

```
if report["overall_result"] == "PASS":
    print("✅ PASS — all checks passed. Ready to proceed.")
elif report["overall_result"] == "WARN":
    print(f"⚠️ WARN — {report['summary']['soft_fails']} soft-fails. Can proceed with warnings.")
    # Print each warning
else:
    print(f"❌ FAIL — {report['summary']['hard_fails']} hard-fails, {report['summary']['io_errors']} IO errors.")
    print("Cannot proceed to next step. Fix the issues and re-validate.")
    # Print each failure with reasoning
```

## Output

```
$OUTPUT_DIR/
  validation_report.json    ← Machine-readable (conforms to validation_report.schema.json)
  validation_report.md      ← Human-readable summary
```

## IO Check Categories

### Step-2 IO Checks (from validate_spine.py)
- DAG integrity (edges valid, no self-loops)
- Reachability (all nodes reachable from entry)
- Registry consistency (effects/predicates reference declared vars)
- Bottleneck invariants
- Duration budget
- Edge labels ≤ 8 CJK chars
- Path budget (playthrough target × 1.2)
- Structural requirements (three-way forks, dead end ratio)

### Step-3 IO Checks (per script)
- 场/景 header present
- 选择 NNN + 问题：format
- ▲ stage directions present
- ━━━ branch section format
- No template artifacts (regex)
- Character count within budget
- Choice block targets match DAG edges

## LLM Judge Questions

### Step-2 (15 questions per node)
See `llm_judge.py` → `S2_QUESTIONS` for full list.
Categories: OBJECT, CHOICE, CONTINUITY, STATE, DRAMA

### Step-3 (15 questions per script)
See `llm_judge.py` → `S3_QUESTIONS` for full list.
Categories: ALIGNMENT, TENSION, NAMING, CHARACTER, SCENE, FORMAT

## Definition of Done

- [ ] Report JSON conforms to `validation_report.schema.json`
- [ ] All nodes with content are checked (skips empty-beat nodes at step-2)
- [ ] Gate result is clearly announced
- [ ] Report saved to both JSON and markdown
- [ ] State.validation_reports updated
