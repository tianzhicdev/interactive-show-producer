#!/usr/bin/env node
/**
 * Seed an interactive show project from local generated data into existing tables.
 * This creates a project in "done" status so it can be viewed in the standard UI.
 *
 * Usage:
 *   DATABASE_URL=... node scripts/seed-review-data.mjs \
 *     --data-dir ~/Downloads/interactive_show_v2_20260530 \
 *     --name "凡人仙葫"
 */

import { neon } from "@neondatabase/serverless";
import { readFileSync, existsSync } from "fs";
import { join, resolve } from "path";
import { parseArgs } from "util";

// --- CLI args ---
const { values: args } = parseArgs({
  options: {
    "data-dir": { type: "string" },
    name: { type: "string" },
  },
});

const dataDir = resolve(args["data-dir"] || ".");
const projectName = args.name || "Untitled Project";

if (!existsSync(join(dataDir, "structure.json"))) {
  console.error(`Error: structure.json not found in ${dataDir}`);
  process.exit(1);
}

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error("Error: DATABASE_URL env var required");
  process.exit(1);
}

const sql = neon(DATABASE_URL);

// --- Load data ---
const structure = JSON.parse(readFileSync(join(dataDir, "structure.json"), "utf-8"));
const scriptsDir = join(dataDir, "scripts");

function loadScript(episodeId) {
  const path = join(scriptsDir, `${episodeId}.txt`);
  if (existsSync(path)) return readFileSync(path, "utf-8");
  return null;
}

// --- Parse episode number from ID like "EP01", "EP03a", "EP12b" ---
function parseEpisodeNumber(epId) {
  const m = epId.match(/^EP(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

// --- Compute DAG positions ---
function computePositions(episodes, forkPoints) {
  const positions = {};
  const X_STEP = 280;
  const Y_MAIN = 300;   // spread between top-level fork threads
  const Y_SUB = 240;    // spread for sub-fork threads within parent band

  // 1. Build DAG adjacency from fork_points
  const adj = {};
  const epIds = episodes.map((e) => e.id);
  const epSet = new Set(epIds);
  for (const id of epIds) adj[id] = [];

  const forkSources = new Set(forkPoints.map((f) => f.fork_choice.split("-")[0]));
  const commonEps = episodes.filter((e) => e.thread === "共同").map((e) => e.id);
  for (let i = 0; i < commonEps.length - 1; i++) {
    if (!forkSources.has(commonEps[i])) adj[commonEps[i]].push(commonEps[i + 1]);
  }
  for (const fork of forkPoints) {
    const src = fork.fork_choice.split("-")[0];
    for (const data of Object.values(fork.threads)) {
      const eps = data.episodes;
      if (epSet.has(eps[0])) adj[src].push(eps[0]);
      for (let i = 0; i < eps.length - 1; i++) adj[eps[i]].push(eps[i + 1]);
      if (fork.convergence_episode && epSet.has(fork.convergence_episode)) {
        adj[eps[eps.length - 1]].push(fork.convergence_episode);
      }
    }
  }

  // 2. Longest-path column assignment (topological order)
  const inDeg = {};
  for (const id of epIds) inDeg[id] = 0;
  for (const id of epIds) for (const t of adj[id]) inDeg[t]++;
  const col = {};
  for (const id of epIds) col[id] = 0;
  const queue = epIds.filter((id) => inDeg[id] === 0);
  while (queue.length > 0) {
    const node = queue.shift();
    for (const next of adj[node]) {
      col[next] = Math.max(col[next], col[node] + 1);
      if (--inDeg[next] === 0) queue.push(next);
    }
  }

  // 3. Row (y) assignment via fork thread hierarchy
  // Map each episode to its fork thread baseline
  const epToThread = {};
  for (const fork of forkPoints) {
    Object.entries(fork.threads).forEach(([, data], idx) => {
      for (const epId of data.episodes) {
        epToThread[epId] = { forkId: fork.id, threadIndex: idx, threadCount: Object.keys(fork.threads).length };
      }
    });
  }

  // Identify sub-forks: forks whose after_episode belongs to another fork's thread
  const forkParent = {};
  for (const fork of forkPoints) {
    const afterEp = fork.fork_choice.split("-")[0];
    if (epToThread[afterEp]) forkParent[fork.id] = epToThread[afterEp];
  }

  function getY(epId) {
    const info = epToThread[epId];
    if (!info) return 0; // common episode
    const parent = forkParent[info.forkId];
    const spread = parent ? Y_SUB : Y_MAIN;
    const parentBaseline = parent ? getY(parent.forkId + "_baseline_" + parent.threadIndex) : 0;
    // Center threads around parent baseline
    const offset = (info.threadIndex - (info.threadCount - 1) / 2) * spread;
    return parentBaseline + offset;
  }

  // Pre-compute parent thread baselines (for sub-forks to reference)
  // A top-level fork thread's baseline = its centered offset from 0
  // We use getY on any episode in that thread
  // But we need to handle the recursive case: compute top-level first, then sub-forks
  const threadBaseline = {};
  for (const fork of forkPoints) {
    const isSubFork = !!forkParent[fork.id];
    Object.entries(fork.threads).forEach(([, data], idx) => {
      const count = Object.keys(fork.threads).length;
      const spread = isSubFork ? Y_SUB : Y_MAIN;
      let parentY = 0;
      if (isSubFork) {
        const p = forkParent[fork.id];
        const parentKey = `${p.forkId}_${p.threadIndex}`;
        parentY = threadBaseline[parentKey] || 0;
      }
      const offset = (idx - (count - 1) / 2) * spread;
      const key = `${fork.id}_${idx}`;
      threadBaseline[key] = parentY + offset;
      for (const epId of data.episodes) {
        positions[epId] = { x: col[epId] * X_STEP, y: parentY + offset };
      }
    });
  }

  // Common episodes at y=0
  for (const epId of commonEps) {
    positions[epId] = { x: col[epId] * X_STEP, y: 0 };
  }

  return positions;
}

// --- Derive edges from fork_points ---
function deriveEdges(episodes, forkPoints) {
  const edges = [];
  const epSet = new Set(episodes.map((e) => e.id));
  let choiceIdx = 0;

  for (const fork of forkPoints) {
    const forkEpId = fork.fork_choice.split("-")[0];
    const threads = Object.entries(fork.threads);

    threads.forEach(([threadName, threadData], ti) => {
      const first = threadData.episodes[0];
      if (epSet.has(first)) {
        edges.push({ source: forkEpId, target: first, label: threadName, choiceIndex: ti });
      }
      // Sequential within thread
      for (let i = 0; i < threadData.episodes.length - 1; i++) {
        edges.push({ source: threadData.episodes[i], target: threadData.episodes[i + 1], label: null, choiceIndex: 0 });
      }
      // Convergence: last branch -> convergence episode
      const last = threadData.episodes[threadData.episodes.length - 1];
      if (fork.convergence_episode && epSet.has(fork.convergence_episode)) {
        edges.push({ source: last, target: fork.convergence_episode, label: null, choiceIndex: 0 });
      }
    });
  }

  // Sequential edges between common episodes not already covered
  const commonEps = episodes.filter((e) => e.thread === "共同").map((e) => e.id);
  const sourcesWithFork = new Set(edges.filter((e) => e.label).map((e) => e.source));
  const convergenceTargets = new Set(
    edges.filter((e) => !e.label && edges.some((fe) => fe.label && fe.source === e.source?.split?.("-")?.[0]))
      .map((e) => e.target)
  );
  // Simpler: just check if edge already exists
  const edgeSet = new Set(edges.map((e) => `${e.source}->${e.target}`));

  for (let i = 0; i < commonEps.length - 1; i++) {
    const src = commonEps[i];
    const tgt = commonEps[i + 1];
    // Skip if this common ep has fork edges going out
    if (sourcesWithFork.has(src)) continue;
    // Skip if target is a convergence point (has incoming edges from branches)
    if (edges.some((e) => e.target === tgt)) continue;
    if (!edgeSet.has(`${src}->${tgt}`)) {
      edges.push({ source: src, target: tgt, label: null, choiceIndex: 0 });
    }
  }

  return edges;
}

// --- Determine scene_type for an episode ---
function getSceneType(epId, forkPoints) {
  // Episodes that have a fork choice after them are "choice" type
  for (const fork of forkPoints) {
    const forkEpId = fork.fork_choice.split("-")[0];
    if (forkEpId === epId) return "choice";
  }
  return "normal";
}

// --- Main ---
async function main() {
  console.log(`Seeding from: ${dataDir}`);
  console.log(`Project name: ${projectName}`);

  const episodes = structure.episodes;
  const forkPoints = structure.fork_points || [];
  const positions = computePositions(episodes, forkPoints);
  const edges = deriveEdges(episodes, forkPoints);

  // 1. Create project with status=done
  const projectRows = await sql`
    INSERT INTO projects (name, status, model_profile_id)
    VALUES (${projectName}, 'done', 'default')
    RETURNING id
  `;
  const projectId = projectRows[0].id;
  console.log(`Created project: ${projectId}`);

  // 2. Insert dag_nodes (one per episode, version=1)
  const version = 1;
  for (const ep of episodes) {
    const pos = positions[ep.id] || { x: 0, y: 0 };
    const epNum = parseEpisodeNumber(ep.id);
    const sceneType = getSceneType(ep.id, forkPoints);

    await sql`
      INSERT INTO dag_nodes (project_id, version, node_key, title, summary, scene_type, is_ending, is_hidden_ending, episode_number, episode_title, position_x, position_y)
      VALUES (${projectId}, ${version}, ${ep.id}, ${ep.title}, ${ep.summary || null}, ${sceneType}, false, false, ${epNum}, ${ep.title}, ${pos.x}, ${pos.y})
    `;
  }
  console.log(`Inserted ${episodes.length} dag_nodes`);

  // 3. Insert dag_edges (version=1)
  for (const edge of edges) {
    await sql`
      INSERT INTO dag_edges (project_id, version, source_node_key, target_node_key, choice_label, choice_index)
      VALUES (${projectId}, ${version}, ${edge.source}, ${edge.target}, ${edge.label || null}, ${edge.choiceIndex})
    `;
  }
  console.log(`Inserted ${edges.length} dag_edges`);

  // 4. Insert scene_scripts (version=1, content from script files)
  let scriptCount = 0;
  for (const ep of episodes) {
    const scriptText = loadScript(ep.id);
    if (scriptText) {
      await sql`
        INSERT INTO scene_scripts (project_id, node_key, version, content, status)
        VALUES (${projectId}, ${ep.id}, ${version}, ${scriptText}, 'ready')
      `;
      scriptCount++;
    }
  }
  console.log(`Inserted ${scriptCount} scene_scripts`);

  // 5. Insert story summary from story_bible.json if available
  const biblePath = join(dataDir, "story_bible.json");
  if (existsSync(biblePath)) {
    const bible = JSON.parse(readFileSync(biblePath, "utf-8"));
    const summaryText = typeof bible === "string" ? bible : JSON.stringify(bible, null, 2);
    await sql`
      INSERT INTO story_summaries (project_id, version, content)
      VALUES (${projectId}, ${version}, ${summaryText})
    `;
    console.log("Inserted story_summary from story_bible.json");
  }

  console.log(`\nDone! Project ID: ${projectId}`);
  console.log(`View at: /project/${projectId}`);
}

main().catch((err) => {
  console.error("Seed failed:", err);
  process.exit(1);
});
