---
name: interactive-play-writer-characters-intro
description: "Produce important characters' background introductions from a guideline + raw story. Outputs a character bible with ~300-character Chinese bios."
---

# /interactive-play-writer-characters-intro

从大纲/改编指南 + 原文，提取重要角色并撰写角色背景介绍。每个角色约 300 字中文背景简介，用于互动剧开篇角色介绍卡。

## Parameters

Parse from user command:

| Parameter | Required | Default | Example |
|-----------|----------|---------|---------|
| `--story` | Yes | - | `~/novels/凡人仙葫.txt` |
| `--guideline` | Yes | - | `~/Downloads/凡人仙葫大纲.pages` or `.docx` |
| `--output` | No | `~/Downloads` | `/path/to/output` |
| `--note` | No | `""` | `"重点关注女性角色"` |

## Language Rule

All output in **Chinese**. JSON keys stay English, values Chinese.

## Execution Phases

### Phase 1: INIT

```bash
SKILL_DIR="skills/interactive-play-writer-characters-intro"
PROJECT_DIR="$OUTPUT_DIR/characters_intro_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$PROJECT_DIR"
```

Save parameters to `$PROJECT_DIR/args.json`.

### Phase 2: PARSE GUIDELINE

Read the guideline file. Support both `.docx` and `.pages`:

- `.docx`: Extract via python-docx
- `.pages`: Use macOS `textutil -convert txt -stdout` to extract plain text. If that fails, unzip and read `preview.jpg` as image.

```python
# .docx
from docx import Document
doc = Document(guideline_path)
guideline_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

# .pages fallback
import subprocess
result = subprocess.run(['textutil', '-convert', 'txt', '-stdout', guideline_path], capture_output=True, text=True)
guideline_text = result.stdout
```

Save to `$PROJECT_DIR/guideline.txt`.

### Phase 3: DETECT CHAPTER RANGE

**Auto-detect chapter range from guideline**. Scan for patterns like:
- "第1章到第80章", "第 1-80 章", "对应原著第1章到第80章"
- "前80章", "1-80章"
- Episode-to-chapter mappings like "改编范围：原著第 1-9 章" — find the max chapter

Extract the chapter range `[start, end]`. If none found, use all chapters.

### Phase 4: READ RAW STORY (SCOPED)

Read **only** the chapters within the detected range from the raw story file.

Detect chapter boundaries by scanning for lines matching `第N章` patterns. Only load text from `第{start}章` through the end of `第{end}章`.

**Do NOT read the entire raw story** — it can be 100k+ lines. Read only what the guideline covers.

Save the scoped text to `$PROJECT_DIR/story_scoped.txt`.

### Phase 5: EXTRACT CHARACTER LIST

From the **guideline** (primary) and **scoped story** (supplementary), identify all important characters.

Priority order:
1. Characters explicitly named in the guideline — these are **always included**
2. Characters who appear repeatedly in the scoped story with significant actions

For each character, extract from guideline + story:
- Name (名字)
- Identity/role (身份)
- Key traits (性格特征)
- Relationships to other characters (人物关系)
- Background context (背景)

Save to `$PROJECT_DIR/character_list.json`:
```json
[
  {
    "name": "张二狗",
    "identity": "底层农家少年",
    "traits": ["老实本分", "初心不改"],
    "relationships": ["小娥子（妹妹）", "老骗子（师傅）"],
    "source": "guideline+story"
  }
]
```

### Phase 6: WRITE CHARACTER BACKGROUNDS

For each character, write a **background introduction** (~300 Chinese characters).

**Writing Guidelines:**
- **Tone**: 第三人称，类似角色小传/档案卡，语言简练有画面感
- **Content**: 角色的出身、身份、性格、处境、与其他角色的关系
- **NOT included**: 不要剧透角色在剧中的具体行动和结局，只提供"出场前"的背景信息
- **Length**: 约 250-350 字，不宜太长
- **Style**: 可以有一两句点睛之笔，暗示角色的命运走向或内在矛盾，但不明说

**Template per character:**

```
【角色名】

身份：一句话身份描述

正文（约300字背景介绍）
```

### Phase 7: OUTPUT

Produce the following files in `$PROJECT_DIR/`:

1. **characters_intro.md** — All character bios in order of importance (protagonist first)
2. **characters_intro.json** — Structured data:

```json
{
  "project": "凡人仙葫",
  "chapter_range": "第1-80章",
  "characters": [
    {
      "name": "张二狗",
      "identity": "底层农家少年",
      "bio": "（约300字背景介绍）"
    }
  ]
}
```

3. **characters_intro.docx** — Formatted Word document with character bios (use python-docx, same CJK font patterns as other skills)

Generate the `.docx` using python-docx:

```python
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# Title
title = doc.add_heading('角色背景介绍', level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

# Subtitle with project info
subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run(f'改编范围：{chapter_range}')
run.font.size = Pt(12)

doc.add_paragraph()  # spacer

for char in characters:
    # Character name heading
    h = doc.add_heading(char['name'], level=1)

    # Identity line
    p = doc.add_paragraph()
    run = p.add_run(f"身份：{char['identity']}")
    run.font.size = Pt(11)
    run.bold = True

    # Bio
    p = doc.add_paragraph(char['bio'])
    p.style.font.size = Pt(11)

    doc.add_paragraph()  # spacer between characters

doc.save(output_path)
```

### Phase 8: SUMMARY

Print a summary to the user:
- Number of characters extracted
- Character names listed
- Output file paths
