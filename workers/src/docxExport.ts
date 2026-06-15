/**
 * DOCX export for interactive drama deliverables.
 * Generates per-episode script DOCX files plus metadata documents.
 */

import type { NeonSQL } from "./db.ts";
import type { Env } from "./env.ts";
import {
  getProject,
  getLatestStorySummary,
  getLatestWorldSettings,
  getCharacters,
  getDagNodes,
  getDagEdges,
  getAllSceneScripts,
  insertExportArtifact,
  updateGenerationJob,
  updateProjectStatus,
} from "./db.ts";
import type { CharacterProfile, WorldSettings } from "@tomato/domain/dagTypes.ts";
import { zipSync } from "fflate";

interface DocxContent {
  title: string;
  sections: { heading: string; body: string }[];
}

function buildDocxXml(content: DocxContent): string {
  const escapedSections = content.sections.map((s) => {
    const heading = escapeXml(s.heading);
    const paras = s.body
      .split("\n")
      .filter((l) => l.trim())
      .map(
        (line) => `<w:p><w:r><w:t xml:space="preserve">${escapeXml(line)}</w:t></w:r></w:p>`
      )
      .join("");
    return `<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>${heading}</w:t></w:r></w:p>${paras}`;
  });

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>${escapeXml(content.title)}</w:t></w:r></w:p>
${escapedSections.join("")}
</w:body>
</w:document>`;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function buildMinimalDocx(documentXml: string): Uint8Array {
  const encoder = new TextEncoder();

  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`;

  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;

  const docRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>`;

  return zipSync({
    "[Content_Types].xml": encoder.encode(contentTypes),
    "_rels/.rels": encoder.encode(rels),
    "word/_rels/document.xml.rels": encoder.encode(docRels),
    "word/document.xml": encoder.encode(documentXml),
  });
}

// --- Document: 互动剧本标准化表 ---
function generateStandardization(
  projectName: string,
  nodeCount: number,
  endingCount: number,
  hiddenEndingCount: number,
  choiceCount: number,
  episodeCount: number
): DocxContent {
  return {
    title: `${projectName} - 互动剧本标准化表`,
    sections: [
      {
        heading: "项目基本信息",
        body: [
          `项目名称：${projectName}`,
          `总集数：${episodeCount}`,
          `总场景数：${nodeCount}`,
          `结局数：${endingCount}`,
          `隐藏结局数：${hiddenEndingCount}`,
          `互动选择点：${choiceCount}`,
          `生成时间：${new Date().toLocaleDateString("zh-CN")}`,
        ].join("\n"),
      },
      {
        heading: "剧本规格",
        body: [
          "格式标准：互动剧标准",
          "对话标记：角色名：对话内容",
          "动作标记：▲动作描述",
          "内心独白：角色名（os）：独白内容",
          "字幕旁白：字幕：旁白内容",
          "互动标记：【互动】",
        ].join("\n"),
      },
    ],
  };
}

// --- Document: 世界/角色设定文档 ---
function generateWorldCharacters(
  projectName: string,
  worldSettings: WorldSettings | null,
  characters: { name: string; profile_data: CharacterProfile }[]
): DocxContent {
  const worldSection = worldSettings
    ? [
        `时代背景：${worldSettings.era ?? "未设定"}`,
        `主要地点：${worldSettings.location ?? "未设定"}`,
        `世界规则：${worldSettings.rules ?? "未设定"}`,
        `基调：${worldSettings.tone ?? "未设定"}`,
        `主题：${(worldSettings.themes ?? []).join("、")}`,
        worldSettings.power_system ? `力量体系：${worldSettings.power_system}` : "",
        worldSettings.factions ? `势力阵营：${worldSettings.factions}` : "",
      ]
        .filter(Boolean)
        .join("\n")
    : "尚未生成";

  const charSections = characters.map((c) => ({
    heading: `角色：${c.name}`,
    body: [
      `性格特点：${c.profile_data.personality ?? "未设定"}`,
      `外貌描述：${c.profile_data.appearance ?? "未设定"}`,
      `能力特长：${c.profile_data.abilities ?? "未设定"}`,
      `目标动机：${c.profile_data.goals ?? "未设定"}`,
      `人物关系：${c.profile_data.relationships ?? "未设定"}`,
      c.profile_data.backstory ? `背景故事：${c.profile_data.backstory}` : "",
    ]
      .filter(Boolean)
      .join("\n"),
  }));

  return {
    title: `${projectName} - 世界/角色设定文档`,
    sections: [
      { heading: "世界观设定", body: worldSection },
      ...charSections,
    ],
  };
}

// --- Document: 剧情/交互设定文档 ---
function generatePlotInteraction(
  projectName: string,
  nodes: { node_key: string; title: string; summary: string | null; scene_type: string; is_ending: boolean; is_hidden_ending: boolean; episode_number: number | null; episode_title: string | null }[],
  edges: { source_node_key: string; target_node_key: string; choice_label: string | null; choice_index: number }[]
): DocxContent {
  const overview = [
    `总节点数：${nodes.length}`,
    `互动选择点：${nodes.filter((n) => n.scene_type === "choice").length}`,
    `结局数：${nodes.filter((n) => n.is_ending && !n.is_hidden_ending).length}`,
    `隐藏结局数：${nodes.filter((n) => n.is_hidden_ending).length}`,
  ].join("\n");

  const choiceNodes = nodes.filter((n) => n.scene_type === "choice");
  const choiceSections = choiceNodes.map((node) => {
    const nodeEdges = edges
      .filter((e) => e.source_node_key === node.node_key)
      .sort((a, b) => a.choice_index - b.choice_index);

    return {
      heading: `互动节点 [${node.node_key}] ${node.title}`,
      body: [
        node.summary ?? "",
        "",
        "选项：",
        ...nodeEdges.map(
          (e) =>
            `  ${e.choice_index + 1}. ${e.choice_label ?? "继续"} → [${e.target_node_key}] ${nodes.find((n) => n.node_key === e.target_node_key)?.title ?? ""}`
        ),
      ].join("\n"),
    };
  });

  const endingNodes = nodes.filter((n) => n.is_ending);
  const endingSection = {
    heading: "结局一览",
    body: endingNodes
      .map(
        (n) =>
          `[${n.node_key}] ${n.title}${n.is_hidden_ending ? " (隐藏结局)" : ""}\n  ${n.summary ?? ""}`
      )
      .join("\n\n"),
  };

  return {
    title: `${projectName} - 剧情/交互设定文档`,
    sections: [
      { heading: "剧情概览", body: overview },
      ...choiceSections,
      endingSection,
    ],
  };
}

// --- Per-Episode Script Document ---
function generateEpisodeScript(
  projectName: string,
  episodeNumber: number,
  episodeTitle: string,
  nodes: { node_key: string; title: string; scene_type: string }[],
  edges: { source_node_key: string; target_node_key: string }[],
  scripts: Map<string, string>
): DocxContent {
  const epLabel = `EP${String(episodeNumber).padStart(2, "0")}`;

  // Topological sort within episode nodes
  const nodeKeySet = new Set(nodes.map((n) => n.node_key));
  const adjacency = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const node of nodes) {
    adjacency.set(node.node_key, []);
    inDegree.set(node.node_key, 0);
  }
  for (const edge of edges) {
    // Only include edges within this episode's nodes
    if (nodeKeySet.has(edge.source_node_key) && nodeKeySet.has(edge.target_node_key)) {
      adjacency.get(edge.source_node_key)?.push(edge.target_node_key);
      inDegree.set(edge.target_node_key, (inDegree.get(edge.target_node_key) ?? 0) + 1);
    }
  }

  const sorted: string[] = [];
  const queue: string[] = [];
  for (const [key, deg] of inDegree) {
    if (deg === 0) queue.push(key);
  }
  while (queue.length > 0) {
    const current = queue.shift()!;
    sorted.push(current);
    for (const child of adjacency.get(current) ?? []) {
      inDegree.set(child, (inDegree.get(child) ?? 0) - 1);
      if (inDegree.get(child) === 0) queue.push(child);
    }
  }

  const sections = sorted.map((nodeKey) => {
    const node = nodes.find((n) => n.node_key === nodeKey);
    const script = scripts.get(nodeKey);
    return {
      heading: `[${nodeKey}] ${node?.title ?? ""}`,
      body: script ?? "[剧本尚未生成]",
    };
  });

  return {
    title: `${projectName} - ${epLabel} ${episodeTitle}`,
    sections,
  };
}

// --- Full Script (fallback for projects without episodes) ---
function generateFullScript(
  projectName: string,
  nodes: { node_key: string; title: string; scene_type: string }[],
  edges: { source_node_key: string; target_node_key: string }[],
  scripts: Map<string, string>
): DocxContent {
  const adjacency = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const node of nodes) {
    adjacency.set(node.node_key, []);
    inDegree.set(node.node_key, 0);
  }
  for (const edge of edges) {
    adjacency.get(edge.source_node_key)?.push(edge.target_node_key);
    inDegree.set(edge.target_node_key, (inDegree.get(edge.target_node_key) ?? 0) + 1);
  }

  const sorted: string[] = [];
  const queue: string[] = [];
  for (const [key, deg] of inDegree) {
    if (deg === 0) queue.push(key);
  }
  while (queue.length > 0) {
    const current = queue.shift()!;
    sorted.push(current);
    for (const child of adjacency.get(current) ?? []) {
      inDegree.set(child, (inDegree.get(child) ?? 0) - 1);
      if (inDegree.get(child) === 0) queue.push(child);
    }
  }

  const sections = sorted.map((nodeKey) => {
    const node = nodes.find((n) => n.node_key === nodeKey);
    const script = scripts.get(nodeKey);
    return {
      heading: `[${nodeKey}] ${node?.title ?? ""}`,
      body: script ?? "[剧本尚未生成]",
    };
  });

  return {
    title: `${projectName} - 完整剧本正文`,
    sections,
  };
}

// --- Main Export Function ---
export async function generateAllExports(
  sql: NeonSQL,
  _env: Env,
  projectId: string,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const [worldSettingsRow, characters, dagNodes, dagEdges, sceneScripts] = await Promise.all([
    getLatestWorldSettings(sql, projectId),
    getCharacters(sql, projectId),
    getDagNodes(sql, projectId),
    getDagEdges(sql, projectId),
    getAllSceneScripts(sql, projectId),
  ]);

  const worldSettings = (worldSettingsRow?.setting_data ?? null) as WorldSettings | null;
  const charData = characters.map((c) => ({
    name: c.name,
    profile_data: c.profile_data as CharacterProfile,
  }));
  const scriptMap = new Map(sceneScripts.map((s) => [s.node_key, s.content]));

  const endingCount = dagNodes.filter((n) => n.is_ending && !n.is_hidden_ending).length;
  const hiddenEndingCount = dagNodes.filter((n) => n.is_hidden_ending).length;
  const choiceCount = dagNodes.filter((n) => n.scene_type === "choice").length;

  // Group nodes by episode
  const episodeMap = new Map<number, { title: string; nodes: typeof dagNodes }>();
  for (const node of dagNodes) {
    if (node.episode_number != null) {
      if (!episodeMap.has(node.episode_number)) {
        episodeMap.set(node.episode_number, {
          title: node.episode_title ?? `EP${String(node.episode_number).padStart(2, "0")}`,
          nodes: [],
        });
      }
      episodeMap.get(node.episode_number)!.nodes.push(node);
    }
  }
  const episodeNumbers = [...episodeMap.keys()].sort((a, b) => a - b);
  const hasEpisodes = episodeNumbers.length > 0;

  // Clear old exports
  await sql`DELETE FROM export_artifacts WHERE project_id = ${projectId}`;

  // Generate metadata documents
  const metaDocs = [
    {
      type: "standardization",
      content: generateStandardization(project.name, dagNodes.length, endingCount, hiddenEndingCount, choiceCount, episodeNumbers.length),
      fileName: `${project.name}_互动剧本标准化表.docx`,
    },
    {
      type: "world_characters",
      content: generateWorldCharacters(project.name, worldSettings, charData),
      fileName: `${project.name}_世界角色设定文档.docx`,
    },
    {
      type: "plot_interaction",
      content: generatePlotInteraction(project.name, dagNodes, dagEdges),
      fileName: `${project.name}_剧情交互设定文档.docx`,
    },
  ];

  for (const doc of metaDocs) {
    const xml = buildDocxXml(doc.content);
    const data = buildMinimalDocx(xml);
    await insertExportArtifact(sql, projectId, doc.type, data, doc.fileName);
  }

  // Generate per-episode or full script
  if (hasEpisodes) {
    for (const epNum of episodeNumbers) {
      const ep = episodeMap.get(epNum)!;
      const epLabel = `EP${String(epNum).padStart(2, "0")}`;
      const content = generateEpisodeScript(
        project.name,
        epNum,
        ep.title,
        ep.nodes,
        dagEdges,
        scriptMap
      );
      const xml = buildDocxXml(content);
      const data = buildMinimalDocx(xml);
      await insertExportArtifact(
        sql,
        projectId,
        `episode_script_${epLabel}`,
        data,
        `互动剧本_${project.name}_${epLabel}.docx`
      );
    }
  } else {
    // Fallback: single full script
    const content = generateFullScript(project.name, dagNodes, dagEdges, scriptMap);
    const xml = buildDocxXml(content);
    const data = buildMinimalDocx(xml);
    await insertExportArtifact(sql, projectId, "full_script", data, `${project.name}_完整剧本正文.docx`);
  }

  await updateGenerationJob(sql, jobId, "done", 1);
  await updateProjectStatus(sql, projectId, "done");
}
