import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";

interface SceneNodeData {
  title: string;
  summary: string | null;
  sceneType: string;
  isEnding: boolean;
  isHiddenEnding: boolean;
  selected: boolean;
  nodeKey?: string;
  episodeNumber?: number;
  episodeColor?: string;
  checked?: boolean;
  [key: string]: unknown;
}

const TYPE_COLORS: Record<string, string> = {
  normal: "border-gray-300 bg-white",
  choice: "border-red-400 bg-red-50",
  ending: "border-emerald-400 bg-emerald-50",
  hidden_ending: "border-purple-400 bg-purple-50",
};

const TYPE_ICONS: Record<string, string> = {
  normal: "",
  choice: "⑂",
  ending: "★",
  hidden_ending: "✕",
};

export function SceneNode({ data }: NodeProps) {
  const d = data as SceneNodeData;
  const color = TYPE_COLORS[d.sceneType] ?? TYPE_COLORS.normal;

  return (
    <div
      className={cn(
        "border-2 rounded-lg px-3 py-2 min-w-[160px] max-w-[200px] shadow-sm cursor-pointer",
        color,
        d.selected && "ring-2 ring-red-500 ring-offset-1"
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="flex items-center gap-1.5">
        {d.nodeKey && (
          <span
            className="text-[9px] px-1 py-0.5 rounded font-bold text-white shrink-0"
            style={{ backgroundColor: d.episodeColor ?? "#6b7280" }}
          >
            {d.nodeKey}
          </span>
        )}
        {TYPE_ICONS[d.sceneType] && (
          <span className="w-5 h-5 rounded-full bg-gray-200 text-[10px] flex items-center justify-center font-bold">
            {TYPE_ICONS[d.sceneType]}
          </span>
        )}
        <span className="text-xs font-semibold truncate">{d.title}</span>
      </div>
      {d.summary && (
        <p className="text-[10px] text-gray-500 mt-1 line-clamp-2">{d.summary}</p>
      )}
      {d.checked !== undefined && (
        <div className="absolute -top-1 -right-1 w-4 h-4 flex items-center justify-center">
          <div className={cn(
            "w-3.5 h-3.5 rounded border-2",
            d.checked ? "bg-red-500 border-red-500" : "bg-white border-gray-300"
          )}>
            {d.checked && (
              <svg className="w-full h-full text-white" viewBox="0 0 12 12">
                <path d="M3 6l2 2 4-4" stroke="currentColor" strokeWidth="2" fill="none" />
              </svg>
            )}
          </div>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
}
