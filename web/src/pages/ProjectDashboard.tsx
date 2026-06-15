import { useParams, Link } from "react-router-dom";
import { useEffect, useState, useCallback, useRef } from "react";
import { useProject } from "@/hooks/useProject";
import { usePolling } from "@/hooks/usePolling";
import { apiGet, apiPost } from "@/lib/api";
import { DagGraphView } from "@/components/DagGraphView";
import { DagOutlineView } from "@/components/DagOutlineView";
import { SceneEditor } from "@/components/SceneEditor";
import { ExportPanel } from "@/components/ExportPanel";
import { ProgressBar } from "@/components/ProgressBar";
import { WorldSettingsEditor } from "@/components/WorldSettingsEditor";
import { CharacterEditor } from "@/components/CharacterEditor";
import { EditableText } from "@/components/EditableText";
import { Tutorial } from "@/components/Tutorial";
import { Comments } from "@/components/Comments";

type LeftTab = "graph" | "outline" | "summary" | "world" | "characters" | "comments";

interface StageStatus {
  queued: number;
  running: number;
  done: number;
  failed: number;
  total: number;
}

interface PipelineStatus {
  project_status: string;
  elapsed_seconds: number;
  stages: {
    summarize_chunk: StageStatus;
    summarize_merge: StageStatus;
    world_settings: StageStatus;
    characters: StageStatus;
    dag_skeleton: StageStatus;
    scene_script: StageStatus;
  };
}

interface Phase1Status {
  project_status: string;
  pipeline: {
    summarize_chunk: { queued: number; running: number; done: number; failed: number };
    summarize_merge: { queued: number; running: number; done: number; failed: number };
    world_settings: { queued: number; running: number; done: number; failed: number };
    characters: { queued: number; running: number; done: number; failed: number };
    dag_skeleton: { queued: number; running: number; done: number; failed: number };
  };
}

interface ScriptGenStatus {
  project_status: string;
  scene_scripts: { queued: number; running: number; done: number; failed: number };
  per_node: { node_key: string; status: string; progress: number; error: string | null }[];
}

export function ProjectDashboard() {
  const { id } = useParams<{ id: string }>();
  const projectId = id!;
  const {
    outline,
    loading,
    fetchOutline,
    startPipeline,
    startPhase1,
    approvePhase1,
    startScriptGen,
    exportDeliverables,
  } = useProject(projectId);

  const [leftTab, setLeftTab] = useState<LeftTab>("graph");
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedNodeKeys, setSelectedNodeKeys] = useState<Set<string>>(new Set());
  const [batchRegenerating, setBatchRegenerating] = useState(false);

  async function withLoading(key: string, fn: () => Promise<unknown>) {
    setActionLoading(key);
    try {
      await fn();
      await fetchOutline();
    } finally {
      setActionLoading(null);
    }
  }

  function toggleNodeKey(key: string) {
    setSelectedNodeKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleBatchRegenerate() {
    if (selectedNodeKeys.size === 0) return;
    setBatchRegenerating(true);
    try {
      await apiPost("regenerate-nodes", {
        project_id: projectId,
        node_keys: [...selectedNodeKeys],
      });
    } finally {
      setBatchRegenerating(false);
      setSelectedNodeKeys(new Set());
      setMultiSelectMode(false);
    }
  }

  const isPipelineRunning = outline?.project.status === "pipeline_running";
  const isPhase1Running = outline?.project.status === "phase1_running";
  const isPhase2Running = outline?.project.status === "phase2_running";
  const isRunning = isPipelineRunning || isPhase1Running || isPhase2Running;

  const fetchPipelineStatus = useCallback(
    () => apiGet<PipelineStatus>(`get-pipeline-status?project_id=${projectId}`),
    [projectId]
  );
  const fetchPhase1Status = useCallback(
    () => apiGet<Phase1Status>(`get-phase1-status?project_id=${projectId}`),
    [projectId]
  );
  const fetchScriptGenStatus = useCallback(
    () => apiGet<ScriptGenStatus>(`get-script-gen-status?project_id=${projectId}`),
    [projectId]
  );

  const { data: pipelineStatus } = usePolling(fetchPipelineStatus, 3000, isPipelineRunning);
  const { data: phase1Status } = usePolling(fetchPhase1Status, 3000, isPhase1Running);
  const { data: scriptGenStatus } = usePolling(fetchScriptGenStatus, 3000, isPhase2Running);

  useEffect(() => {
    fetchOutline();
  }, [fetchOutline]);

  // Refetch outline when phase transitions complete
  useEffect(() => {
    if (pipelineStatus?.project_status === "done" && outline?.project.status === "pipeline_running") {
      fetchOutline();
    }
    if (phase1Status?.project_status === "phase1_ready" && outline?.project.status === "phase1_running") {
      fetchOutline();
    }
    if (scriptGenStatus?.project_status === "phase2_ready" && outline?.project.status === "phase2_running") {
      fetchOutline();
    }
  }, [pipelineStatus, phase1Status, scriptGenStatus, outline, fetchOutline]);

  if (loading && !outline) {
    return <div className="flex items-center justify-center min-h-screen text-gray-400">加载中...</div>;
  }

  const project = outline?.project;
  const dagNodes = outline?.dag.nodes ?? [];
  const dagEdges = outline?.dag.edges ?? [];

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Top Bar */}
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-red-600 font-bold">互动剧</Link>
          <span className="text-gray-300">/</span>
          <span className="font-medium">{project?.name ?? "..."}</span>
          <StatusBadge status={project?.status ?? "draft"} />
        </div>
        <div className="flex items-center gap-2">
          {project?.status === "draft" && (
            <>
              <button
                onClick={() => withLoading("pipeline", startPipeline)}
                disabled={!!actionLoading}
                className="px-3 py-1.5 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:opacity-50"
              >
                {actionLoading === "pipeline" ? "启动中..." : "开始生成"}
              </button>
              <button
                onClick={() => withLoading("phase1", startPhase1)}
                disabled={!!actionLoading}
                className="px-3 py-1.5 bg-gray-200 text-gray-600 rounded text-sm hover:bg-gray-300 disabled:opacity-50"
              >
                {actionLoading === "phase1" ? "启动中..." : "仅 Phase 1"}
              </button>
            </>
          )}
          {project?.status === "phase1_ready" && (
            <>
              <button
                onClick={() => withLoading("approve", approvePhase1)}
                disabled={!!actionLoading}
                className="px-3 py-1.5 bg-green-500 text-white rounded text-sm hover:bg-green-600 disabled:opacity-50"
              >
                {actionLoading === "approve" ? "批准中..." : "批准 Phase 1"}
              </button>
              <button
                onClick={() => withLoading("scriptgen", startScriptGen)}
                disabled={!!actionLoading}
                className="px-3 py-1.5 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:opacity-50"
              >
                {actionLoading === "scriptgen" ? "启动中..." : "开始生成剧本"}
              </button>
            </>
          )}
          {/* 导出交付物 — hidden for now */}
        </div>
      </header>

      {/* Tutorial (only when phase1 is ready or later) */}
      {project?.status === "phase1_ready" && (
        <div className="px-4 pt-2 shrink-0">
          <Tutorial
            id="dashboard-editing"
            title="编辑与审核互动剧大纲"
            steps={[
              "点击图形中的节点查看和编辑场景详情",
              "在下方面板编辑故事总结、世界观和角色设定",
              "悬停任何内容区域会出现「编辑」按钮",
              "满意后点击「批准 Phase 1」→「开始生成剧本」进入下一阶段",
            ]}
          />
        </div>
      )}

      {/* Progress Bar (when running) */}
      {isPipelineRunning && pipelineStatus && (
        <div className="bg-white border-b px-4 py-3 shrink-0">
          <UnifiedPipelineProgress status={pipelineStatus} />
        </div>
      )}
      {isPhase1Running && phase1Status && (
        <div className="bg-white border-b px-4 py-2 shrink-0">
          <Phase1Progress status={phase1Status} />
        </div>
      )}
      {isPhase2Running && scriptGenStatus && (
        <div className="bg-white border-b px-4 py-2 shrink-0">
          <Phase2Progress status={scriptGenStatus} />
        </div>
      )}

      {/* Main Content — left 1/3 tabs, right 2/3 script */}
      <div className="flex-1 flex min-h-0">
        {/* Left Panel: unified tabs */}
        <div className="w-1/3 min-w-[320px] flex flex-col border-r bg-white">
          <div className="bg-white border-b px-3 py-1.5 flex items-center gap-1 flex-wrap shrink-0">
            {([
              ["graph", "图形"],
              ["outline", "大纲"],
              ["summary", "总结"],
              ["world", "世界观"],
              ["characters", "角色"],
              ["comments", "评论"],
            ] as [LeftTab, string][]).map(([tab, label]) => (
              <button
                key={tab}
                onClick={() => setLeftTab(tab)}
                className={`px-2 py-1 rounded text-sm ${leftTab === tab ? "bg-red-50 text-red-600 font-medium" : "text-gray-500 hover:bg-gray-50"}`}
              >
                {label}
              </button>
            ))}
            {/* 批量选择 — hidden for now */}
          </div>
          <div className="flex-1 min-h-0 overflow-auto">
            {leftTab === "graph" && (
              <DagGraphView
                nodes={dagNodes}
                edges={dagEdges}
                selectedNodeKey={selectedNodeKey}
                onNodeSelect={setSelectedNodeKey}
                selectedNodeKeys={selectedNodeKeys}
                multiSelectMode={multiSelectMode}
                onToggleNodeKey={toggleNodeKey}
                projectId={projectId}
              />
            )}
            {leftTab === "outline" && (
              <DagOutlineView
                nodes={dagNodes}
                edges={dagEdges}
                selectedNodeKey={selectedNodeKey}
                onNodeSelect={setSelectedNodeKey}
                selectedNodeKeys={selectedNodeKeys}
                onToggleNodeKey={toggleNodeKey}
                multiSelectMode={multiSelectMode}
              />
            )}
            {leftTab === "summary" && (
              <div className="p-4">
                <EditableText
                  value={outline?.story_summary ?? ""}
                  placeholder="尚未生成故事总结"
                  onSave={async (content) => {
                    await apiPost("update-story-summary", { project_id: projectId, content });
                    fetchOutline();
                  }}
                />
              </div>
            )}
            {leftTab === "world" && (
              <div className="p-4">
                <WorldSettingsEditor
                  projectId={projectId}
                  data={outline?.world_settings as Record<string, unknown> | null}
                  onUpdate={fetchOutline}
                />
              </div>
            )}
            {leftTab === "characters" && (
              <div className="p-4">
                <CharacterEditor
                  projectId={projectId}
                  characters={(outline?.characters ?? []) as { id: string; name: string; profile_data: Record<string, unknown> }[]}
                  onUpdate={fetchOutline}
                />
              </div>
            )}
            {leftTab === "comments" && (
              <Comments projectId={projectId} nodeKey={selectedNodeKey ?? undefined} />
            )}
          </div>
        </div>

        {/* Right Panel: Script (2/3) */}
        <div className="flex-1 bg-white flex flex-col min-w-0">
          {selectedNodeKey ? (
            <SceneEditor
              projectId={projectId}
              nodeKey={selectedNodeKey}
              node={dagNodes.find((n) => n.node_key === selectedNodeKey)}
              edges={dagEdges}
              onNodeUpdate={fetchOutline}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              选择一个节点查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, { label: string; color: string }> = {
    draft: { label: "草稿", color: "bg-gray-100 text-gray-600" },
    uploading: { label: "上传中", color: "bg-blue-100 text-blue-600" },
    pipeline_running: { label: "生成中", color: "bg-yellow-100 text-yellow-700" },
    phase1_running: { label: "Phase 1", color: "bg-yellow-100 text-yellow-700" },
    phase1_ready: { label: "Phase 1 ✓", color: "bg-green-100 text-green-700" },
    phase2_running: { label: "Phase 2", color: "bg-yellow-100 text-yellow-700" },
    phase2_ready: { label: "Phase 2 ✓", color: "bg-green-100 text-green-700" },
    done: { label: "完成", color: "bg-emerald-100 text-emerald-700" },
  };
  const s = labels[status] ?? labels.draft;
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${s.color}`}>{s.label}</span>;
}

// Phase 1 weighted progress: each stage contributes a portion of 0-100%
// Weights: summarize_chunk 30%, summarize_merge 20%, world+chars 25%, dag_skeleton 25%
function Phase1Progress({ status }: { status: Phase1Status }) {
  const p = status.pipeline;

  const stageProgress = (stage: { queued: number; running: number; done: number; failed: number }) => {
    const total = stage.queued + stage.running + stage.done + stage.failed;
    if (total === 0) return 0;
    // Running jobs count as ~30% done for smoother progress
    return (stage.done + stage.running * 0.3) / total;
  };

  // World + characters run in parallel, so take the min progress as the gate
  const wsProgress = stageProgress(p.world_settings);
  const chProgress = stageProgress(p.characters);
  const wcCombined = Math.min(wsProgress, chProgress);

  const overallPct =
    stageProgress(p.summarize_chunk) * 30 +
    stageProgress(p.summarize_merge) * 20 +
    wcCombined * 25 +
    stageProgress(p.dag_skeleton) * 25;

  // Determine current active stage label
  const activeStage =
    stageProgress(p.dag_skeleton) > 0 && stageProgress(p.dag_skeleton) < 1 ? "生成DAG骨架" :
    (wsProgress > 0 || chProgress > 0) && wcCombined < 1 ? "生成世界观与角色" :
    stageProgress(p.summarize_merge) > 0 && stageProgress(p.summarize_merge) < 1 ? "合并故事总结" :
    stageProgress(p.summarize_chunk) < 1 ? "分析故事内容" :
    "处理中";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-600 font-medium">Phase 1: {activeStage}</span>
        <span className="text-gray-400 tabular-nums">{Math.round(overallPct)}%</span>
      </div>
      <ProgressBar percent={overallPct} size="md" />
      <div className="flex gap-3 text-[10px] text-gray-400">
        <StepDot label="分块总结" progress={stageProgress(p.summarize_chunk)} />
        <StepDot label="合并总结" progress={stageProgress(p.summarize_merge)} />
        <StepDot label="世界观" progress={wsProgress} />
        <StepDot label="角色" progress={chProgress} />
        <StepDot label="DAG骨架" progress={stageProgress(p.dag_skeleton)} />
      </div>
    </div>
  );
}

function StepDot({ label, progress }: { label: string; progress: number }) {
  const color =
    progress >= 1 ? "bg-green-400" :
    progress > 0 ? "bg-yellow-400 animate-pulse" :
    "bg-gray-200";
  return (
    <div className="flex items-center gap-1">
      <div className={`w-1.5 h-1.5 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  );
}

function Phase2Progress({ status }: { status: ScriptGenStatus }) {
  const s = status.scene_scripts;
  const total = s.queued + s.running + s.done + s.failed;
  // Use per-node progress for smoother bar
  const runningFraction = status.per_node
    .filter((n) => n.status === "running")
    .reduce((acc, n) => acc + (n.progress ?? 0.3), 0);
  const pct = total > 0 ? ((s.done + runningFraction * 0.3) / total) * 100 : 0;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-600 font-medium">
          Phase 2: 生成场景剧本 ({s.done}/{total})
        </span>
        <div className="flex items-center gap-2">
          {s.failed > 0 && <span className="text-red-500 text-[10px]">{s.failed} 失败</span>}
          <span className="text-gray-400 tabular-nums">{Math.round(pct)}%</span>
        </div>
      </div>
      <ProgressBar percent={pct} size="md" />
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  summarize_chunk: "分块总结",
  summarize_merge: "合并总结",
  world_settings: "世界观",
  characters: "角色",
  dag_skeleton: "DAG骨架",
  scene_script: "场景剧本",
};

function UnifiedPipelineProgress({ status }: { status: PipelineStatus }) {
  const stageOrder: (keyof PipelineStatus["stages"])[] = [
    "summarize_chunk", "summarize_merge", "world_settings",
    "characters", "dag_skeleton", "scene_script",
  ];

  let totalDone = 0;
  let totalAll = 0;
  for (const key of stageOrder) {
    const s = status.stages[key];
    totalDone += s.done;
    totalAll += s.total;
  }
  const overallPct = totalAll > 0 ? Math.round((totalDone / totalAll) * 100) : 0;

  const elapsed = status.elapsed_seconds;
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const elapsedStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-600 font-medium">Pipeline 进度</span>
        <span className="text-gray-400 tabular-nums">{overallPct}% · {elapsedStr}</span>
      </div>
      <ProgressBar percent={overallPct} size="md" />
      <div className="flex gap-3 text-[10px] text-gray-400">
        {stageOrder.map((key) => {
          const s = status.stages[key];
          const icon = s.total === 0 ? "⏳" : s.done === s.total ? "✅" : s.running > 0 ? "🔄" : "⏳";
          return (
            <div key={key} className="flex items-center gap-1">
              <span>{icon}</span>
              <span>{STAGE_LABELS[key]}</span>
              {s.total > 0 && <span className="tabular-nums">{s.done}/{s.total}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
