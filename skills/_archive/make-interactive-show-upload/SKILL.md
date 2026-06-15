---
name: make-interactive-show-upload
description: "Upload a completed interactive show (state.json) to the web app database."
---

# /make-interactive-show-upload

将 `/make-interactive-show` 生成的 `state.json` 上传到 Web 应用数据库。

## 参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--file` | 是 | - | `state.json` 路径或包含 `state.json` 的项目目录 |
| `--name` | 否 | `metadata.title` | 项目名称 |
| `--database-url` | 否 | `$DATABASE_URL` | Neon 数据库连接 URL |
| `--replace` | 否 | `false` | 删除同名旧项目后再上传 |

## 执行流程

### Step 1: 加载与验证

1. 解析 `--file` 参数：
   - 如果是目录路径，寻找 `state.json`
   - 如果是文件路径，直接加载
2. 验证 `state.json` 包含必要字段：`metadata`, `structure`, `scripts`, `story_bible`
3. 确定项目名称：`--name` > `metadata.title` > 文件名
4. 确定数据库 URL：`--database-url` > `$DATABASE_URL`

### Step 2: 生成并运行上传脚本

生成一个临时 Node.js 脚本（使用 `@neondatabase/serverless`），执行以下操作：

#### 2a. 可选：清理旧数据

如果 `--replace` 为 true：
```sql
DELETE FROM projects WHERE name = $name
```
（CASCADE 会自动清理所有关联数据）

#### 2b. 创建项目

```sql
INSERT INTO projects (name, status, model_profile_id, steering_notes)
VALUES ($name, 'done', 'default', $note)
RETURNING id
```

`steering_notes` 取自 `metadata.note`。

#### 2c. 插入 dag_nodes

每个 episode 一条记录。Position 计算算法：

```
X_STEP = 280
Y_SPREAD = 180

共同集 (thread === "共同"):
  x = 递增 * X_STEP, y = 0

分支集:
  同一列中的分支集按 Y_SPREAD 垂直扇出
  offset = (index - (count-1)/2) * Y_SPREAD
```

字段映射：
- `node_key` = episode.id (如 "EP01")
- `title` = episode.title
- `summary` = episode.summary
- `scene_type` = 如果该集有 fork_choice 则 "choice"，否则 "normal"
- `is_ending` = 该集包含 ending 类型场景
- `episode_number` = 从 ID 解析的数字 (EP01 → 1)
- `episode_title` = episode.title
- `position_x`, `position_y` = 计算值

#### 2d. 插入 dag_edges

从 `fork_points` 推导边：
1. 分叉点集 → 每条线程的第一集（带 `choice_label` = 线程名）
2. 线程内集 → 下一集（顺序边）
3. 线程最后一集 → `convergence_episode`（汇聚边）
4. 共同集之间的顺序边（排除已有 fork 边的）

#### 2e. 插入 scene_scripts

从 `scripts` 对象读取每集脚本文本：
```json
{
  "EP01": "脚本文本...",
  "EP02": "脚本文本..."
}
```

如果 `scripts` 不存在，从 `$PROJECT_DIR/scripts/EP01.txt` 等文件读取。

#### 2f. 插入 story_summaries

将 `story_bible` 序列化为 JSON 文本存入 `story_summaries.content`。

#### 2g. 插入 world_settings

将以下数据组合存入 `world_settings.setting_data`：
```json
{
  "player_stats": [...],
  "fork_points": [...],
  "endings": [...],
  "dead_ends": [...],
  "ability_registry": [...],
  "character_lifecycle": [...],
  "object_registry": [...],
  "threshold_triggers": [...]
}
```

#### 2h. 插入 characters

从 `story_bible.characters` 提取角色数据。每个角色一条记录：
- `name` = character.name
- `profile_data` = 完整角色 JSON（性格、背景、能力等）

### Step 3: 验证

上传完成后运行验证查询：

```sql
SELECT
  (SELECT COUNT(*) FROM dag_nodes WHERE project_id = $id) as nodes,
  (SELECT COUNT(*) FROM dag_edges WHERE project_id = $id) as edges,
  (SELECT COUNT(*) FROM scene_scripts WHERE project_id = $id) as scripts,
  (SELECT COUNT(*) FROM characters WHERE project_id = $id) as characters
```

打印统计信息。

### Step 4: 报告

向用户报告：
1. 项目 ID
2. 上传统计（节点数、边数、脚本数、角色数）
3. 项目 URL：`/project/{project_id}`

## 上传脚本模板

在项目目录中生成 `upload.mjs`，内容基于 `scripts/seed-review-data.mjs` 的逻辑：

```javascript
#!/usr/bin/env node
import { neon } from "@neondatabase/serverless";
import { readFileSync } from "fs";

const DATABASE_URL = process.env.DATABASE_URL;
const sql = neon(DATABASE_URL);

// 从命令行参数读取
const stateFile = process.argv[2];
const projectName = process.argv[3] || "Untitled";
const replace = process.argv[4] === "--replace";

const state = JSON.parse(readFileSync(stateFile, "utf-8"));
const structure = state.structure;
const scripts = state.scripts || {};
const storyBible = state.story_bible;
const episodes = structure.episodes;
const forkPoints = structure.fork_points || [];

// --- Position computation ---
function computePositions(episodes, forkPoints) {
  const positions = {};
  const X_STEP = 280;
  const Y_SPREAD = 180;

  const branchMap = {};
  for (const fork of forkPoints) {
    const threads = Object.entries(fork.threads);
    threads.forEach(([, threadData], threadIndex) => {
      threadData.episodes.forEach((epId) => {
        branchMap[epId] = { forkId: fork.id, threadIndex, threadCount: threads.length };
      });
    });
  }

  const forkStructure = {};
  for (const fork of forkPoints) {
    const threads = Object.values(fork.threads).map((t) => t.episodes);
    forkStructure[fork.id] = { maxLen: Math.max(...threads.map((t) => t.length)), threads };
  }

  const commonIds = new Set(episodes.filter((e) => e.thread === "共同").map((e) => e.id));
  const placed = new Set();
  let xPos = 0;

  for (const ep of episodes) {
    if (placed.has(ep.id)) continue;
    if (commonIds.has(ep.id)) {
      positions[ep.id] = { x: xPos, y: 0 };
      placed.add(ep.id);
      xPos += X_STEP;
    } else {
      const branch = branchMap[ep.id];
      if (!branch) {
        positions[ep.id] = { x: xPos, y: 0 };
        placed.add(ep.id);
        xPos += X_STEP;
        continue;
      }
      const fork = forkStructure[branch.forkId];
      if (!fork) continue;
      for (let col = 0; col < fork.maxLen; col++) {
        const colEps = [];
        for (const thread of fork.threads) {
          if (col < thread.length) colEps.push(thread[col]);
        }
        colEps.forEach((epId, idx) => {
          const offset = (idx - (colEps.length - 1) / 2) * Y_SPREAD;
          positions[epId] = { x: xPos, y: offset };
          placed.add(epId);
        });
        xPos += X_STEP;
      }
    }
  }
  return positions;
}

// --- Edge derivation ---
function deriveEdges(episodes, forkPoints) {
  const edges = [];
  const epSet = new Set(episodes.map((e) => e.id));

  for (const fork of forkPoints) {
    const forkEpId = fork.fork_choice.split("-")[0];
    const threads = Object.entries(fork.threads);
    threads.forEach(([threadName, threadData], ti) => {
      const first = threadData.episodes[0];
      if (epSet.has(first)) edges.push({ source: forkEpId, target: first, label: threadName, choiceIndex: ti });
      for (let i = 0; i < threadData.episodes.length - 1; i++) {
        edges.push({ source: threadData.episodes[i], target: threadData.episodes[i + 1], label: null, choiceIndex: 0 });
      }
      const last = threadData.episodes[threadData.episodes.length - 1];
      if (fork.convergence_episode && epSet.has(fork.convergence_episode)) {
        edges.push({ source: last, target: fork.convergence_episode, label: null, choiceIndex: 0 });
      }
    });
  }

  const commonEps = episodes.filter((e) => e.thread === "共同").map((e) => e.id);
  const sourcesWithFork = new Set(edges.filter((e) => e.label).map((e) => e.source));
  const edgeSet = new Set(edges.map((e) => `${e.source}->${e.target}`));
  for (let i = 0; i < commonEps.length - 1; i++) {
    const src = commonEps[i], tgt = commonEps[i + 1];
    if (sourcesWithFork.has(src)) continue;
    if (edges.some((e) => e.target === tgt)) continue;
    if (!edgeSet.has(`${src}->${tgt}`)) edges.push({ source: src, target: tgt, label: null, choiceIndex: 0 });
  }
  return edges;
}

async function main() {
  // Optional: replace existing
  if (replace) {
    const existing = await sql`SELECT id FROM projects WHERE name = ${projectName}`;
    for (const row of existing) {
      await sql`DELETE FROM projects WHERE id = ${row.id}`;
      console.log(`Deleted existing project: ${row.id}`);
    }
  }

  // 1. Create project
  const note = state.metadata?.note || null;
  const [{ id: projectId }] = await sql`
    INSERT INTO projects (name, status, model_profile_id, steering_notes)
    VALUES (${projectName}, 'done', 'default', ${note})
    RETURNING id
  `;
  console.log(`Created project: ${projectId}`);

  // 2. dag_nodes
  const positions = computePositions(episodes, forkPoints);
  const version = 1;
  const forkEpIds = new Set(forkPoints.map((fp) => fp.fork_choice.split("-")[0]));

  for (const ep of episodes) {
    const pos = positions[ep.id] || { x: 0, y: 0 };
    const epNum = parseInt((ep.id.match(/^EP(\d+)/) || [])[1] || "0", 10);
    const sceneType = forkEpIds.has(ep.id) ? "choice" : "normal";
    const isEnding = (ep.scenes || []).some((s) => s.type === "ending");

    await sql`
      INSERT INTO dag_nodes (project_id, version, node_key, title, summary, scene_type, is_ending, is_hidden_ending, episode_number, episode_title, position_x, position_y)
      VALUES (${projectId}, ${version}, ${ep.id}, ${ep.title}, ${ep.summary || null}, ${sceneType}, ${isEnding}, false, ${epNum}, ${ep.title}, ${pos.x}, ${pos.y})
    `;
  }
  console.log(`Inserted ${episodes.length} dag_nodes`);

  // 3. dag_edges
  const edges = deriveEdges(episodes, forkPoints);
  for (const edge of edges) {
    await sql`
      INSERT INTO dag_edges (project_id, version, source_node_key, target_node_key, choice_label, choice_index)
      VALUES (${projectId}, ${version}, ${edge.source}, ${edge.target}, ${edge.label || null}, ${edge.choiceIndex})
    `;
  }
  console.log(`Inserted ${edges.length} dag_edges`);

  // 4. scene_scripts
  let scriptCount = 0;
  for (const ep of episodes) {
    const scriptText = scripts[ep.id];
    if (scriptText) {
      await sql`
        INSERT INTO scene_scripts (project_id, node_key, version, content, status)
        VALUES (${projectId}, ${ep.id}, ${version}, ${scriptText}, 'ready')
      `;
      scriptCount++;
    }
  }
  console.log(`Inserted ${scriptCount} scene_scripts`);

  // 5. story_summary
  if (storyBible) {
    const summaryText = typeof storyBible === "string" ? storyBible : JSON.stringify(storyBible, null, 2);
    await sql`
      INSERT INTO story_summaries (project_id, version, content)
      VALUES (${projectId}, ${version}, ${summaryText})
    `;
    console.log("Inserted story_summary");
  }

  // 6. world_settings
  const settingData = {
    player_stats: structure.player_stats || [],
    fork_points: forkPoints,
    endings: structure.endings || [],
    dead_ends: structure.dead_ends || [],
    ability_registry: structure.ability_registry || [],
    character_lifecycle: structure.character_lifecycle || [],
    object_registry: structure.object_registry || [],
    threshold_triggers: structure.threshold_triggers || [],
  };
  await sql`
    INSERT INTO world_settings (project_id, version, setting_data)
    VALUES (${projectId}, ${version}, ${JSON.stringify(settingData)})
  `;
  console.log("Inserted world_settings");

  // 7. characters
  const characters = storyBible?.characters || storyBible?.角色 || [];
  const charArray = Array.isArray(characters) ? characters : Object.values(characters);
  for (const char of charArray) {
    const charName = char.name || char.名字 || "未知";
    await sql`
      INSERT INTO characters (project_id, version, name, profile_data)
      VALUES (${projectId}, ${version}, ${charName}, ${JSON.stringify(char)})
    `;
  }
  console.log(`Inserted ${charArray.length} characters`);

  // 8. Verify
  const [counts] = await sql`
    SELECT
      (SELECT COUNT(*) FROM dag_nodes WHERE project_id = ${projectId})::int as nodes,
      (SELECT COUNT(*) FROM dag_edges WHERE project_id = ${projectId})::int as edges,
      (SELECT COUNT(*) FROM scene_scripts WHERE project_id = ${projectId})::int as scripts,
      (SELECT COUNT(*) FROM characters WHERE project_id = ${projectId})::int as characters
  `;
  console.log("\n=== Upload Complete ===");
  console.log(`Nodes: ${counts.nodes} | Edges: ${counts.edges} | Scripts: ${counts.scripts} | Characters: ${counts.characters}`);
  console.log(`Project ID: ${projectId}`);
  console.log(`View at: /project/${projectId}`);
}

main().catch((err) => { console.error("Upload failed:", err); process.exit(1); });
```

## 执行步骤

1. 加载 `state.json`，验证必要字段
2. 将上述脚本模板写入临时文件 `$PROJECT_DIR/upload.mjs`，替换硬编码值
3. 运行：
   ```bash
   DATABASE_URL="$DATABASE_URL" node "$PROJECT_DIR/upload.mjs" "$STATE_FILE" "$PROJECT_NAME" [--replace]
   ```
4. 检查输出，确认上传成功
5. 报告项目 URL

## 错误处理

- 如果 `state.json` 缺少必要字段 → 报错并退出
- 如果 `DATABASE_URL` 未设置 → 提示用户设置
- 如果 `--replace` 但旧项目不存在 → 忽略，继续创建
- 如果上传中途失败 → 报告错误，建议用 `--replace` 重试
