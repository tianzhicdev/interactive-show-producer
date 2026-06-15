import { useMemo } from "react";

interface DagNode {
  node_key: string;
  title: string;
  summary: string | null;
  scene_type: string;
  is_ending: boolean;
  is_hidden_ending: boolean;
  episode_number: number | null;
  episode_title: string | null;
}

interface DagEdge {
  source_node_key: string;
  target_node_key: string;
  choice_label: string | null;
  resolution: string[] | null;
}

interface Episode {
  number: number;
  title: string;
  nodes: DagNode[];
}

const TYPE_LABEL: Record<string, string> = {
  normal: "",
  choice: "[互动]",
  ending: "[结局]",
  hidden_ending: "[隐藏结局]",
};

const TYPE_COLORS: Record<string, string> = {
  ending: "text-green-600",
  hidden_ending: "text-purple-600",
};

export function DagOutlineView({
  nodes,
  edges,
  selectedNodeKey,
  onNodeSelect,
  selectedNodeKeys,
  onToggleNodeKey,
  multiSelectMode,
}: {
  nodes: DagNode[];
  edges: DagEdge[];
  selectedNodeKey: string | null;
  onNodeSelect: (key: string) => void;
  selectedNodeKeys?: Set<string>;
  onToggleNodeKey?: (key: string) => void;
  multiSelectMode?: boolean;
}) {
  // Classify nodes: regular episodes vs dead ends vs endings
  const { regularEpisodes, deadEnds, endings } = useMemo(() => {
    const episodeMap = new Map<number, Episode>();
    const deadEndNodes: DagNode[] = [];
    const endingNodes: DagNode[] = [];

    for (const node of nodes) {
      // Dead ends and endings get their own sections regardless of episode_number
      if (node.is_hidden_ending || node.node_key.startsWith("DE")) {
        deadEndNodes.push(node);
      } else if (node.is_ending || node.node_key.startsWith("END")) {
        endingNodes.push(node);
      } else if (node.episode_number != null) {
        if (!episodeMap.has(node.episode_number)) {
          episodeMap.set(node.episode_number, {
            number: node.episode_number,
            title: node.episode_title ?? `EP${String(node.episode_number).padStart(2, "0")}`,
            nodes: [],
          });
        }
        episodeMap.get(node.episode_number)!.nodes.push(node);
      } else {
        // Ungrouped regular node — treat as separate
        deadEndNodes.push(node);
      }
    }

    const sorted = [...episodeMap.values()].sort((a, b) => a.number - b.number);
    for (const ep of sorted) {
      ep.nodes.sort((a, b) => a.node_key.localeCompare(b.node_key));
    }
    deadEndNodes.sort((a, b) => a.node_key.localeCompare(b.node_key));
    endingNodes.sort((a, b) => a.node_key.localeCompare(b.node_key));

    return { regularEpisodes: sorted, deadEnds: deadEndNodes, endings: endingNodes };
  }, [nodes]);

  // Build child map for edge display
  const childMap = useMemo(() => {
    const map = new Map<string, { nodeKey: string; label: string | null }[]>();
    for (const edge of edges) {
      const children = map.get(edge.source_node_key) ?? [];
      children.push({ nodeKey: edge.target_node_key, label: edge.choice_label });
      map.set(edge.source_node_key, children);
    }
    return map;
  }, [edges]);

  if (nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        尚未生成 DAG 结构
      </div>
    );
  }

  function isEpisodeFullySelected(ep: Episode): boolean {
    if (!selectedNodeKeys) return false;
    return ep.nodes.every((n) => selectedNodeKeys.has(n.node_key));
  }

  function isEpisodePartiallySelected(ep: Episode): boolean {
    if (!selectedNodeKeys) return false;
    return ep.nodes.some((n) => selectedNodeKeys.has(n.node_key)) && !isEpisodeFullySelected(ep);
  }

  function handleToggleEpisode(ep: Episode) {
    if (!onToggleNodeKey) return;
    const allSelected = isEpisodeFullySelected(ep);
    for (const node of ep.nodes) {
      const isSelected = selectedNodeKeys?.has(node.node_key);
      if (allSelected && isSelected) {
        onToggleNodeKey(node.node_key);
      } else if (!allSelected && !isSelected) {
        onToggleNodeKey(node.node_key);
      }
    }
  }

  function renderNodeRow(node: DagNode) {
    const typeLabel = TYPE_LABEL[node.scene_type] ?? "";
    const typeColor = TYPE_COLORS[node.scene_type] ?? "text-red-500";
    const isChecked = selectedNodeKeys?.has(node.node_key) ?? false;
    const children = childMap.get(node.node_key);

    return (
      <div key={node.node_key}>
        <div
          onClick={() => onNodeSelect(node.node_key)}
          className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-50 rounded ${
            selectedNodeKey === node.node_key ? "bg-red-50" : ""
          }`}
        >
          {multiSelectMode && (
            <input
              type="checkbox"
              checked={isChecked}
              onChange={(e) => {
                e.stopPropagation();
                onToggleNodeKey?.(node.node_key);
              }}
              onClick={(e) => e.stopPropagation()}
              className="shrink-0 accent-red-500"
            />
          )}
          <span className="text-xs text-gray-400 font-mono shrink-0">{node.node_key}</span>
          <span className="text-sm truncate">{node.title}</span>
          {typeLabel && (
            <span className={`text-[10px] font-medium shrink-0 ${typeColor}`}>{typeLabel}</span>
          )}
        </div>
        {/* Show edge labels (choice options) */}
        {children && children.length > 0 && (
          <div className="pl-10 pb-1">
            {children.map((child) => (
              <div key={child.nodeKey} className="text-[10px] text-gray-400 flex items-center gap-1">
                <span className="text-gray-300">→</span>
                {child.label && <span className="text-red-400">{child.label}</span>}
                <span className="text-gray-300">{child.nodeKey}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto py-2">
      {/* Regular episodes */}
      {regularEpisodes.map((ep) => {
        const epLabel = `EP${String(ep.number).padStart(2, "0")}`;
        const fullySelected = isEpisodeFullySelected(ep);
        const partiallySelected = isEpisodePartiallySelected(ep);

        return (
          <div key={ep.number} className="mb-1">
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-100 sticky top-0">
              {multiSelectMode && (
                <input
                  type="checkbox"
                  checked={fullySelected}
                  ref={(el) => {
                    if (el) el.indeterminate = partiallySelected;
                  }}
                  onChange={() => handleToggleEpisode(ep)}
                  className="shrink-0 accent-red-500"
                />
              )}
              <span className="text-xs font-bold text-red-600">{epLabel}</span>
              <span className="text-sm font-medium">{ep.title}</span>
              <span className="text-[10px] text-gray-400 ml-auto">{ep.nodes.length} 场景</span>
            </div>
            <div className="pl-4">
              {ep.nodes.map(renderNodeRow)}
            </div>
          </div>
        );
      })}

      {/* Dead Ends section */}
      {deadEnds.length > 0 && (
        <div className="mb-1">
          <div className="flex items-center gap-2 px-3 py-2 bg-purple-50 border-b border-purple-100 sticky top-0">
            <span className="text-xs font-bold text-purple-600">死胡同</span>
            <span className="text-[10px] text-purple-400 ml-auto">{deadEnds.length} 个</span>
          </div>
          <div className="pl-4">
            {deadEnds.map(renderNodeRow)}
          </div>
        </div>
      )}

      {/* Endings section */}
      {endings.length > 0 && (
        <div className="mb-1">
          <div className="flex items-center gap-2 px-3 py-2 bg-green-50 border-b border-green-100 sticky top-0">
            <span className="text-xs font-bold text-green-600">结局</span>
            <span className="text-[10px] text-green-400 ml-auto">{endings.length} 个</span>
          </div>
          <div className="pl-4">
            {endings.map(renderNodeRow)}
          </div>
        </div>
      )}
    </div>
  );
}
