# Offline Script Production Process

This document describes the offline (CLI/Python) workflow for producing interactive show scripts from raw source material. This process was used to produce the v2 script for "公路求生：无限进化".

## Overview

The offline pipeline takes a raw web novel + reviewer feedback and produces a complete interactive script package:

```
Raw Novel (.txt)
  + Existing Script v1 (.docx)
  + Outline (.docx)
  + Reviewer Feedback (.xlsx)
        │
        ▼
  ┌─────────────────────┐
  │  Claude Code (CLI)  │
  │  + Python scripts   │
  └─────────────────────┘
        │
        ▼
  Output Package:
    ├── 互动剧本 EP01-02.docx
    ├── 互动剧本 EP03-04.docx
    ├── 互动剧本 EP05-06.docx
    ├── 互动剧本大纲.docx
    ├── 互动结构图.pdf
    └── 全剧摘要.md
```

## Input Files

| File | Format | Purpose |
|------|--------|---------|
| Raw novel | `.txt` | Full source text (~3MB for 公路求生) |
| Existing script v1 | `.docx` | Previous version to improve upon |
| Outline | `.docx` | Original story outline for format reference |
| Reviewer feedback | `.xlsx` | Structured feedback with scores and notes |

## Output Files

| File | Format | Generator Script | Purpose |
|------|--------|-----------------|---------|
| EP01-02 script | `.docx` | `generate_script.py` | Interactive script scenes 1-2 |
| EP03-04 script | `.docx` | `generate_script_ep03_04.py` | Interactive script scenes 3-4 |
| EP05-06 script | `.docx` | `generate_script_ep05_06.py` | Interactive script scenes 5-6 |
| Full outline | `.docx` | `generate_outline.py` | Story bible matching original outline format |
| Story graph | `.pdf` | `render_graph_pdf.py` | Visual flowchart of all interactive nodes |
| Story summary | `.md` | `generate_summary.py` | Markdown summary of the full story |

## Tools & Dependencies

### Python Libraries

| Library | Purpose | Install |
|---------|---------|---------|
| `python-docx` | Generate .docx script files | `pip install python-docx` |
| `openpyxl` | Read .xlsx reviewer feedback | `pip install openpyxl` |
| `graphviz` (Python) | Graph construction API | `pip install graphviz` |
| `graphviz` (system) | Render graphs to PDF | `brew install graphviz` |

### Why Graphviz for the Story Graph

We evaluated multiple options for rendering the interactive structure flowchart to PDF:

| Library | Auto Layout | CJK Support | PDF Output | Verdict |
|---------|-------------|-------------|------------|---------|
| **Graphviz** | Excellent (`dot` engine) | Yes (set `fontname`) | Native vector PDF | **Winner** |
| matplotlib | None (manual x,y) | Fragile (font detection issues) | Raster-in-PDF | Ugly, overlapping nodes |
| Mermaid CLI | Good | Yes (via Chromium) | Browser print-to-PDF | Heavy deps (Node + Chromium) |
| ReportLab | None | Excellent | Native PDF | No auto layout |
| PyCairo + Pango | None | Excellent | Native PDF | Overkill, no layout |

**Key lesson**: matplotlib is terrible for flowcharts — no automatic layout means manually positioning every node with (x, y) coordinates, which causes overlapping on complex graphs. Graphviz's `dot` engine handles hierarchical flowcharts natively.

**CJK font setup for Graphviz on macOS**:
```python
CJK_FONT = 'Heiti SC'  # Available via fontconfig on macOS
# Set on graph, node, AND edge attributes:
g.attr('graph', fontname=CJK_FONT)
g.attr('node', fontname=CJK_FONT)
g.attr('edge', fontname=CJK_FONT)
```

Verify font availability: `fc-match "Heiti SC"` should return `STHeiti Medium.ttc`.

### Multi-page PDF Merging

Graphviz renders one graph per PDF. To merge into a single multi-page PDF:

```python
# Preferred: pypdf
from pypdf import PdfMerger
merger = PdfMerger()
for f in pdf_files:
    merger.append(f)
merger.write(output_path)

# Fallback: macOS built-in
/System/Library/Automator/Combine\ PDF\ Pages.action/Contents/MacOS/join -o output.pdf page1.pdf page2.pdf
```

## Process Steps

### 1. Script Generation

Each `generate_script_*.py` file contains the full script text as a Python string and uses `python-docx` to produce formatted .docx output. The scripts embed:

- Scene headers with structured metadata (ID, name, chapter ref, scene type, location, time, characters)
- Prose with stage directions (▲ markers)
- Dialogue blocks
- Interactive choice blocks with option labels, descriptions, stat changes, and jump targets
- System popup descriptions

**Why Python generators instead of writing .docx directly?**
- Claude Code can generate and iterate on Python code more reliably than binary .docx
- The script text is version-controlled as source code
- Re-running a generator reproduces the exact same .docx
- Easy to make surgical edits and re-render

### 2. Feedback Verification

After generating all episodes, compare the new script against the old one and the reviewer feedback spreadsheet:

1. Read all generated .docx files (via `python-docx`)
2. Read the feedback .xlsx (via `openpyxl`)
3. Check every feedback point is addressed
4. Edit scripts in-place if any feedback was missed

### 3. Story Graph Generation

The story graph (`render_graph_pdf.py`) renders the interactive structure as a multi-page PDF flowchart using Graphviz.

**Graph node types and styles**:

| Type | Shape | Color | Use |
|------|-------|-------|-----|
| Scene | Rounded box | Light blue `#e3f2fd` | Story scenes (C1, C2, ...) |
| Choice | Diamond | Light orange `#fff3e0` | Interactive decision points (Q1, Q2, ...) |
| Option | Rounded box | Light purple `#f3e5f5` | Choice options (A, B, C) |
| Dead end | Box | Red `#ffcdd2` | Game over paths |
| Converge | Rounded box | Blue `#bbdefb` | Points where branches merge |
| Next episode | Double octagon | Teal `#b2dfdb` | Episode transition |
| Note | Note shape | Light yellow `#fffde7` | Hidden elements, conditions |

**Critical: Data consistency**

The graph data MUST match the actual generated scripts exactly. Before rendering, verify every node against the script source:

- Choice count per node
- Option labels (A/B/C/D)
- Stat changes (trust, durability, San, physique values)
- Scene flow (what connects to what)
- Dead ends and conditional options
- Hidden ending prerequisites

### 4. Outline Generation

The outline (`generate_outline.py`) produces a .docx matching the format of the original `《房车》大纲.docx`, containing:

1. Overall story summary & adaptation notes
2. World settings
3. Character profiles
4. Per-episode outlines
5. Interactive structure statistics
6. Production notes

## Script Format Reference

### Scene Header
```
场景编号：EP01-C1
场景名称：灰雾之醒
章节参考：第1-3章
场景类型：世界观引入/角色建立
地点：末世公路·破旧房车内
时间：清晨·灰雾逼近
出场人物：林辉
```

### Interactive Choice Block
```
【互动节点 EP01-Q1】首次遭遇丧尸

A.【果断反击】用扳手迎击丧尸头部 → 跳转C2.A
B.【回车固守】立即退回房车 → 跳转C2.B
C.【引诱陷阱】将资源箱扔向丧尸 → 跳转C2.C

倒计时：10秒
默认选项：B
```

### System Popup
```
【系统提示】
体魄：5→7 | 获得：低级进化碎片×1
```

## File Organization

```
interactive-show-producer/
├── generate_script.py          # EP01-02 generator
├── generate_script_ep03_04.py  # EP03-04 generator
├── generate_script_ep05_06.py  # EP05-06 generator
├── generate_outline.py         # Full outline generator
├── generate_summary.py         # Story summary generator
├── generate_story_graph.py     # Mermaid markdown graph
├── render_graph_pdf.py         # Graphviz PDF graph renderer
└── docs/
    └── offline-script-production.md  # This file
```

Output goes to `~/Downloads/`:
```
~/Downloads/
├── 公路求生_互动剧本v2_EP01-02.docx
├── 公路求生_互动剧本v2_EP03-04.docx
├── 公路求生_互动剧本v2_EP05-06.docx
├── 公路求生_互动剧本大纲v2.docx
├── 公路求生_互动结构图v2.pdf
└── 公路求生_全剧摘要v2.md
```
