import { useEffect, useState, useCallback, useRef } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { Comments } from "@/components/Comments";

interface SceneScript {
  id: string;
  node_key: string;
  version: number;
  content: string;
  steering_notes: string | null;
  status: string;
  created_at: string;
}

interface SceneData {
  current: SceneScript | null;
  versions: { version: number; status: string; steering_notes: string | null; created_at: string }[];
  preview?: { version: number; content: string; status: string; created_at: string };
}

interface Predicate {
  key: string;
  cmp: string;
  value: unknown;
}

interface StateEffect {
  key: string;
  op: string;
  value: unknown;
}

interface DagEdge {
  source_node_key: string;
  target_node_key: string;
  choice_label: string | null;
  effects: StateEffect[] | null;
  resolution: string[] | null;
}

interface DagNode {
  node_key: string;
  title: string;
  summary: string | null;
  scene_type: string;
  requires: Predicate[] | null;
  invariants: Predicate[] | null;
  computed_states: Record<string, unknown[]> | null;
}

export function SceneEditor({
  projectId,
  nodeKey,
  node,
  edges,
  onNodeUpdate,
}: {
  projectId: string;
  nodeKey: string;
  node?: DagNode;
  edges?: DagEdge[];
  onNodeUpdate?: () => void;
}) {
  const [sceneData, setSceneData] = useState<SceneData | null>(null);
  const [steeringNotes, setSteeringNotes] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [regeneratingBranch, setRegeneratingBranch] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const nodeKeyRef = useRef(nodeKey);
  const preRegenVersionRef = useRef<number | null>(null);

  // Inline script editing
  const [editingScript, setEditingScript] = useState(false);
  const [scriptDraft, setScriptDraft] = useState("");
  const [savingScript, setSavingScript] = useState(false);

  // Version preview/revert
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);

  // State panel
  const [showState, setShowState] = useState(false);

  // Node editing
  const [showComments, setShowComments] = useState(false);
  const [editingNode, setEditingNode] = useState(false);
  const [nodeTitleDraft, setNodeTitleDraft] = useState("");
  const [nodeSummaryDraft, setNodeSummaryDraft] = useState("");
  const [savingNode, setSavingNode] = useState(false);

  const fetchScene = useCallback(async () => {
    const data = await apiGet<SceneData>(
      `get-scene?project_id=${projectId}&node_key=${nodeKey}`
    );
    setSceneData(data);
  }, [projectId, nodeKey]);

  useEffect(() => {
    nodeKeyRef.current = nodeKey;
    preRegenVersionRef.current = null;
    fetchScene();
    setEditingScript(false);
    setEditingNode(false);
    setPreviewVersion(null);
    setPreviewContent(null);
    setRegenerating(false);
    setRegeneratingBranch(false);
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchScene]);

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const currentNodeKey = nodeKeyRef.current;
        const data = await apiGet<SceneData>(
          `get-scene?project_id=${projectId}&node_key=${currentNodeKey}`
        );
        if (currentNodeKey !== nodeKeyRef.current) return;
        setSceneData(data);
        if (
          data.current?.status === "ready" &&
          (preRegenVersionRef.current === null ||
           data.current.version > preRegenVersionRef.current)
        ) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setRegenerating(false);
          setRegeneratingBranch(false);
          preRegenVersionRef.current = null;
        }
      } catch {
        // Keep polling on transient errors
      }
    }, 3000);
  }

  async function handleRegenerate() {
    preRegenVersionRef.current = sceneData?.current?.version ?? 0;
    setRegenerating(true);
    try {
      await apiPost("regenerate-scene", {
        project_id: projectId,
        node_key: nodeKey,
        steering_notes: steeringNotes || undefined,
      });
      startPolling();
    } catch {
      setRegenerating(false);
      preRegenVersionRef.current = null;
    }
  }

  async function handleRegenerateBranch() {
    if (!confirm(`确定要重新生成从 ${nodeKey} 开始的所有下游场景吗？`)) return;
    preRegenVersionRef.current = sceneData?.current?.version ?? 0;
    setRegeneratingBranch(true);
    setRegenerating(true);
    try {
      await apiPost("regenerate-branch", {
        project_id: projectId,
        root_node_key: nodeKey,
        steering_notes: steeringNotes || undefined,
      });
      startPolling();
    } catch {
      setRegeneratingBranch(false);
      setRegenerating(false);
      preRegenVersionRef.current = null;
    }
  }

  async function handlePreviewVersion(v: number) {
    if (previewVersion === v) {
      setPreviewVersion(null);
      setPreviewContent(null);
      return;
    }
    try {
      const data = await apiGet<SceneData>(
        `get-scene?project_id=${projectId}&node_key=${nodeKey}&version=${v}`
      );
      if (data.preview) {
        setPreviewVersion(v);
        setPreviewContent(data.preview.content);
      }
    } catch {
      // ignore
    }
  }

  async function handleRevertToVersion(v: number) {
    setReverting(true);
    try {
      await apiPost("revert-scene-script", {
        project_id: projectId,
        node_key: nodeKey,
        version: v,
      });
      setPreviewVersion(null);
      setPreviewContent(null);
      await fetchScene();
    } finally {
      setReverting(false);
    }
  }

  async function handleSaveScript() {
    setSavingScript(true);
    try {
      await apiPost("update-scene-script", {
        project_id: projectId,
        node_key: nodeKey,
        content: scriptDraft,
      });
      await fetchScene();
      setEditingScript(false);
    } finally {
      setSavingScript(false);
    }
  }

  async function handleSaveNode() {
    setSavingNode(true);
    try {
      await apiPost("update-dag-node", {
        project_id: projectId,
        node_key: nodeKey,
        title: nodeTitleDraft,
        summary: nodeSummaryDraft,
      });
      onNodeUpdate?.();
      setEditingNode(false);
    } finally {
      setSavingNode(false);
    }
  }

  async function handleDeleteNode() {
    if (!confirm(`确定要删除节点 ${nodeKey} "${node?.title}"吗？相关的边也会被删除。`)) return;
    await apiPost("delete-dag-node", {
      project_id: projectId,
      node_key: nodeKey,
    });
    onNodeUpdate?.();
  }

  return (
    <div className="flex flex-col h-full">
      {/* Node Header */}
      <div className="border-b px-4 py-3 shrink-0 group relative">
        {editingNode ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 font-mono">{nodeKey}</span>
              <input
                type="text"
                value={nodeTitleDraft}
                onChange={(e) => setNodeTitleDraft(e.target.value)}
                className="flex-1 border rounded px-2 py-1 text-sm font-medium"
                placeholder="标题"
              />
            </div>
            <textarea
              value={nodeSummaryDraft}
              onChange={(e) => setNodeSummaryDraft(e.target.value)}
              className="w-full border rounded px-2 py-1 text-xs resize-none h-12"
              placeholder="摘要"
            />
            <div className="flex gap-1.5">
              <button
                onClick={handleSaveNode}
                disabled={savingNode}
                className="px-2 py-0.5 bg-red-500 text-white rounded text-xs hover:bg-red-600 disabled:opacity-50"
              >
                {savingNode ? "..." : "保存"}
              </button>
              <button
                onClick={() => setEditingNode(false)}
                className="px-2 py-0.5 border rounded text-xs hover:bg-gray-50"
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 font-mono">{nodeKey}</span>
              <span className="font-medium">{node?.title ?? nodeKey}</span>
            </div>
            {node?.summary && (
              <p className="text-xs text-gray-500 mt-1">{node.summary}</p>
            )}
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 flex gap-1 transition-opacity">
              <button
                onClick={() => {
                  setNodeTitleDraft(node?.title ?? "");
                  setNodeSummaryDraft(node?.summary ?? "");
                  setEditingNode(true);
                }}
                className="text-[10px] px-1.5 py-0.5 bg-gray-100 rounded text-gray-500 hover:bg-gray-200"
              >
                编辑节点
              </button>
              <button
                onClick={handleDeleteNode}
                className="text-[10px] px-1.5 py-0.5 bg-red-50 rounded text-red-500 hover:bg-red-100"
              >
                删除
              </button>
            </div>
          </>
        )}
      </div>

      {/* State Transition Panel */}
      {(node?.requires?.length || node?.invariants?.length || node?.computed_states || edges?.some(e => e.source_node_key === nodeKey)) && (
        <div className="border-b shrink-0">
          <button
            onClick={() => setShowState(v => !v)}
            className="w-full px-4 py-1.5 flex items-center gap-1.5 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
          >
            <span className={`transition-transform ${showState ? "rotate-90" : ""}`}>▸</span>
            <span className="font-medium">状态变化</span>
            {node?.requires?.length ? <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">{node.requires.length} 条件</span> : null}
            {node?.invariants?.length ? <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">{node.invariants.length} 不变量</span> : null}
          </button>
          {showState && (
            <div className="px-4 pb-3 space-y-2">
              {/* Entry conditions (requires) */}
              {node?.requires && node.requires.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">入场条件</p>
                  <div className="flex flex-wrap gap-1">
                    {node.requires.map((r, i) => (
                      <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-amber-50 text-amber-800 border border-amber-200">
                        {r.key} {r.cmp} {String(r.value)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {/* Invariants (bottlenecks) */}
              {node?.invariants && node.invariants.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">瓶颈不变量</p>
                  <div className="flex flex-wrap gap-1">
                    {node.invariants.map((inv, i) => (
                      <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-blue-50 text-blue-800 border border-blue-200">
                        {inv.key} {inv.cmp} {String(inv.value)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {/* Entry state (computed_states) — show only non-default or multi-valued */}
              {node?.computed_states && (() => {
                const cs = node.computed_states!;
                const interesting = Object.entries(cs).filter(([, vals]) => {
                  const v = vals as unknown[];
                  if (v.length > 1) return true;
                  if (v.length === 1 && v[0] !== false && v[0] !== "unknown" && v[0] !== "none" && v[0] !== "wary") return true;
                  return false;
                });
                if (interesting.length === 0) return null;
                return (
                  <div>
                    <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">入场状态</p>
                    <div className="space-y-0.5">
                      {interesting.map(([key, vals]) => (
                        <div key={key} className="flex items-center gap-1.5 text-[10px]">
                          <span className="text-gray-500 font-mono min-w-[80px]">{key}</span>
                          <div className="flex gap-0.5 flex-wrap">
                            {(vals as unknown[]).map((v, i) => (
                              <span key={i} className={`px-1 py-0.5 rounded ${
                                (vals as unknown[]).length > 1
                                  ? "bg-amber-50 text-amber-800 border border-amber-200"
                                  : "bg-gray-100 text-gray-700"
                              }`}>
                                {String(v)}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
              {/* State transitions per outgoing edge */}
              {edges && (() => {
                const outEdges = edges.filter(e => e.source_node_key === nodeKey);
                if (outEdges.length === 0) return null;
                const cs = node?.computed_states ?? {};

                // Compute exit state per edge: entry_vals + effects = exit_vals
                const edgeExits = outEdges.map(e => {
                  const exitState: Record<string, unknown> = {};
                  // Start with entry state (take first possible value as representative)
                  for (const [k, vals] of Object.entries(cs)) {
                    const v = vals as unknown[];
                    exitState[k] = v.length > 0 ? v[0] : null;
                  }
                  // Apply effects
                  if (e.effects) {
                    for (const eff of e.effects) {
                      if (eff.op === "set") {
                        exitState[eff.key] = eff.value;
                      }
                    }
                  }
                  return { edge: e, exitState };
                });

                // Find variables that change on any edge
                const changedVars = new Set<string>();
                for (const { edge } of edgeExits) {
                  if (edge.effects) {
                    for (const eff of edge.effects) {
                      changedVars.add(eff.key);
                    }
                  }
                }
                if (changedVars.size === 0 && outEdges.every(e => !e.effects?.length)) return null;

                return (
                  <div>
                    <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">选择出口</p>
                    <div className="space-y-1.5">
                      {edgeExits.map(({ edge, exitState }, i) => {
                        const hasEffects = edge.effects && edge.effects.length > 0;
                        return (
                          <div key={i} className="pl-2 border-l-2 border-gray-200">
                            <div className="flex items-center gap-1.5 text-[10px]">
                              <span className="text-gray-500 font-medium">→{edge.target_node_key}</span>
                              {edge.choice_label && (
                                <span className="text-gray-400">"{edge.choice_label}"</span>
                              )}
                            </div>
                            {edge.resolution && edge.resolution.length > 0 && (
                              <div className="mt-0.5 pl-2 text-[10px] text-gray-400 italic">
                                {edge.resolution.map((beat, j) => (
                                  <div key={`res-${j}`}>▸ {beat}</div>
                                ))}
                              </div>
                            )}
                            {hasEffects ? (
                              <div className="mt-0.5 space-y-0.5">
                                {edge.effects!.map((eff, j) => {
                                  const entryVals = (cs[eff.key] as unknown[]) ?? [];
                                  const entryStr = entryVals.length > 1
                                    ? `[${entryVals.map(String).join(",")}]`
                                    : entryVals.length === 1 ? String(entryVals[0]) : "?";
                                  const exitStr = String(eff.value);
                                  const changed = !entryVals.every(v => String(v) === exitStr);
                                  return (
                                    <div key={j} className="flex items-center gap-1 text-[10px] pl-2">
                                      <span className="font-mono text-gray-500">{eff.key}:</span>
                                      {changed ? (
                                        <>
                                          <span className="text-gray-400">{entryStr}</span>
                                          <span className="text-gray-300">→</span>
                                          <span className="px-1 py-0.5 rounded bg-green-50 text-green-800 border border-green-200 font-medium">
                                            {exitStr}
                                          </span>
                                        </>
                                      ) : (
                                        <span className="text-gray-300">不变</span>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <p className="text-[10px] text-gray-300 pl-2 mt-0.5">无状态变化</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      )}

      {/* Script Content */}
      <div className="flex-1 overflow-auto p-4 min-h-0 group relative">
        {regenerating && (
          <div className="absolute inset-0 bg-white/70 z-10 flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 border-3 border-red-200 border-t-red-500 rounded-full animate-spin" />
            <span className="text-sm text-gray-500">
              {regeneratingBranch ? "重新生成分支中..." : "重新生成中..."}
            </span>
          </div>
        )}
        {previewVersion !== null && previewContent !== null && (
          <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs flex items-center justify-between">
            <span className="text-amber-700">
              预览 v{previewVersion} — 当前为 v{sceneData?.current?.version}
            </span>
            <div className="flex gap-1.5">
              <button
                onClick={() => handleRevertToVersion(previewVersion)}
                disabled={reverting}
                className="px-2 py-0.5 bg-amber-500 text-white rounded hover:bg-amber-600 disabled:opacity-50"
              >
                {reverting ? "回退中..." : "回退到此版本"}
              </button>
              <button
                onClick={() => { setPreviewVersion(null); setPreviewContent(null); }}
                className="px-2 py-0.5 border border-amber-300 rounded text-amber-600 hover:bg-amber-100"
              >
                关闭预览
              </button>
            </div>
          </div>
        )}
        {editingScript ? (
          <div className="h-full flex flex-col">
            <textarea
              value={scriptDraft}
              onChange={(e) => setScriptDraft(e.target.value)}
              className="flex-1 w-full border rounded px-3 py-2 text-sm font-serif resize-none focus:ring-1 focus:ring-red-300"
              disabled={savingScript}
            />
            <div className="flex gap-1.5 mt-2 shrink-0">
              <button
                onClick={handleSaveScript}
                disabled={savingScript}
                className="px-2.5 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600 disabled:opacity-50"
              >
                {savingScript ? "保存中..." : "保存剧本"}
              </button>
              <button
                onClick={() => setEditingScript(false)}
                disabled={savingScript}
                className="px-2.5 py-1 border rounded text-xs hover:bg-gray-50"
              >
                取消
              </button>
            </div>
          </div>
        ) : previewContent !== null ? (
          <div className="whitespace-pre-wrap text-sm leading-relaxed font-serif opacity-80">
            {previewContent}
          </div>
        ) : sceneData?.current ? (
          <>
            <div className={`whitespace-pre-wrap text-sm leading-relaxed font-serif ${regenerating ? "opacity-40" : ""}`}>
              {sceneData.current.content}
            </div>
            {!regenerating && (
              <button
                onClick={() => {
                  setScriptDraft(sceneData.current!.content);
                  setEditingScript(true);
                }}
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-[10px] px-1.5 py-0.5 bg-gray-100 rounded text-gray-500 hover:bg-gray-200 transition-opacity"
              >
                编辑剧本
              </button>
            )}
          </>
        ) : regenerating ? null : (
          <div className="text-gray-400 text-center py-8">
            尚未生成剧本
          </div>
        )}
      </div>

      {/* Version History */}
      {sceneData?.versions && sceneData.versions.length > 1 && (
        <div className="border-t px-4 py-2 shrink-0">
          <p className="text-xs text-gray-400 mb-1">版本历史（点击预览）</p>
          <div className="flex gap-1 overflow-x-auto">
            {sceneData.versions.map((v) => {
              const isCurrent = v.version === sceneData.current?.version;
              const isPreviewing = v.version === previewVersion;
              return (
                <button
                  key={v.version}
                  onClick={() => !isCurrent && handlePreviewVersion(v.version)}
                  disabled={isCurrent}
                  className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
                    isPreviewing
                      ? "bg-amber-200 text-amber-800 font-medium"
                      : isCurrent
                        ? "bg-red-100 text-red-600 font-medium cursor-default"
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200 cursor-pointer"
                  }`}
                >
                  v{v.version} {isCurrent ? "(当前)" : v.status === "ready" ? "✓" : "..."}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Comment / Regeneration Controls */}
      <div className="border-t px-4 py-3 shrink-0 space-y-2">
        <div className="flex gap-2">
          <button
            onClick={() => setShowComments((v) => !v)}
            className={`flex-1 py-1.5 rounded text-sm ${showComments ? "bg-red-500 text-white" : "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"}`}
          >
            {showComments ? "收起评论" : "评论"}
          </button>
          <button
            disabled
            className="py-1.5 px-3 bg-gray-100 text-gray-400 rounded text-sm cursor-not-allowed"
          >
            重新生成
          </button>
          <button
            disabled
            className="py-1.5 px-3 bg-gray-100 text-gray-400 rounded text-sm cursor-not-allowed"
          >
            重生分支
          </button>
        </div>
        {showComments && (
          <div className="border rounded-lg overflow-hidden h-64">
            <Comments projectId={projectId} nodeKey={nodeKey} />
          </div>
        )}
      </div>
    </div>
  );
}
