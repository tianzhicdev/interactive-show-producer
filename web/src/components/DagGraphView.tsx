import { useCallback, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type OnNodesChange,
  applyNodeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { SceneNode } from "./SceneNode";

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

interface DagNode {
  node_key: string;
  title: string;
  summary: string | null;
  scene_type: string;
  is_ending: boolean;
  is_hidden_ending: boolean;
  episode_number: number | null;
  episode_title: string | null;
  position_x: number;
  position_y: number;
  requires: Predicate[] | null;
  invariants: Predicate[] | null;
  computed_states: Record<string, unknown[]> | null;
}

interface DagEdge {
  source_node_key: string;
  target_node_key: string;
  choice_label: string | null;
  effects: StateEffect[] | null;
  resolution: string[] | null;
}

const nodeTypes = { scene: SceneNode };

const EPISODE_COLORS = [
  "#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4",
  "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f43f5e",
  "#a855f7", "#6366f1",
];

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = localStorage.getItem("auth_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function DagGraphView({
  nodes: dagNodes,
  edges: dagEdges,
  selectedNodeKey,
  onNodeSelect,
  selectedNodeKeys,
  multiSelectMode,
  onToggleNodeKey,
  projectId,
}: {
  nodes: DagNode[];
  edges: DagEdge[];
  selectedNodeKey: string | null;
  onNodeSelect: (key: string) => void;
  selectedNodeKeys?: Set<string>;
  multiSelectMode?: boolean;
  onToggleNodeKey?: (key: string) => void;
  projectId?: string;
}) {
  const initialNodes: Node[] = useMemo(
    () =>
      dagNodes.map((n) => ({
        id: n.node_key,
        type: "scene",
        position: { x: n.position_y, y: n.position_x },
        data: {
          title: n.title,
          summary: n.summary,
          sceneType: n.scene_type,
          isEnding: n.is_ending,
          isHiddenEnding: n.is_hidden_ending,
          selected: n.node_key === selectedNodeKey,
          nodeKey: n.node_key,
          episodeNumber: n.episode_number,
          episodeColor: n.is_hidden_ending
            ? "#7c3aed"
            : n.is_ending
            ? "#059669"
            : n.episode_number != null
            ? EPISODE_COLORS[(n.episode_number - 1) % EPISODE_COLORS.length]
            : "#6b7280",
          checked: multiSelectMode ? (selectedNodeKeys?.has(n.node_key) ?? false) : undefined,
        },
      })),
    [dagNodes, selectedNodeKey, selectedNodeKeys, multiSelectMode]
  );

  const [nodes, setNodes] = useState<Node[]>(initialNodes);
  // Sync when dagNodes/selection changes from parent
  useMemo(() => setNodes(initialNodes), [initialNodes]);

  const edges: Edge[] = useMemo(
    () =>
      dagEdges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source_node_key,
        target: e.target_node_key,
        label: e.choice_label ?? undefined,
        animated: true,
        style: { stroke: e.choice_label ? "#ef4444" : "#94a3b8" },
        labelStyle: { fontSize: 11, fill: "#ef4444" },
      })),
    [dagEdges]
  );

  // Debounced position save
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPositions = useRef<Map<string, { x: number; y: number }>>(new Map());

  const savePositions = useCallback(() => {
    if (!projectId || pendingPositions.current.size === 0) return;
    const positions = Array.from(pendingPositions.current.entries()).map(
      ([node_key, pos]) => ({
        node_key,
        // Swap back: XYFlow x → DB position_y, XYFlow y → DB position_x
        position_x: pos.y,
        position_y: pos.x,
      })
    );
    pendingPositions.current.clear();
    fetch(`${API_BASE}/update-node-positions`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ project_id: projectId, positions }),
    }).catch(() => {/* silent */});
  }, [projectId]);

  const onNodesChange: OnNodesChange = useCallback(
    (changes) => {
      setNodes((nds) => applyNodeChanges(changes, nds));
      // Track position changes for save
      for (const change of changes) {
        if (change.type === "position" && change.position) {
          pendingPositions.current.set(change.id, change.position);
        }
      }
      // Debounce save: 800ms after last drag
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(savePositions, 800);
    },
    [savePositions]
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (multiSelectMode && onToggleNodeKey) {
        onToggleNodeKey(node.id);
      } else {
        onNodeSelect(node.id);
      }
    },
    [onNodeSelect, multiSelectMode, onToggleNodeKey]
  );

  if (dagNodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        尚未生成 DAG 结构
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      onNodesChange={onNodesChange}
      fitView
      minZoom={0.1}
      maxZoom={2}
    >
      <Background />
      <Controls />
    </ReactFlow>
  );
}
