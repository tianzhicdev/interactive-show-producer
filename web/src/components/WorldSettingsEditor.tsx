import { useState } from "react";
import { apiPost } from "@/lib/api";

interface WorldSettings {
  [key: string]: unknown;
}

const SECTION_LABELS: Record<string, string> = {
  title: "作品名称",
  genre: "题材类型",
  themes: "核心主题",
  world_building: "世界观设定",
  time_period: "时代背景",
  locations: "主要场景",
  power_system: "能力体系",
  factions: "势力阵营",
  rules: "世界规则",
  tone: "风格基调",
};

function renderValue(value: unknown, depth = 0): React.ReactNode {
  if (value == null) return <span className="text-gray-400">—</span>;

  if (typeof value === "string") {
    return <span className="text-gray-700">{value}</span>;
  }

  if (Array.isArray(value)) {
    return (
      <ul className="list-disc list-inside space-y-0.5">
        {value.map((item, i) => (
          <li key={i} className="text-gray-700 text-sm">
            {typeof item === "string" ? item : renderValue(item, depth + 1)}
          </li>
        ))}
      </ul>
    );
  }

  if (typeof value === "object") {
    return (
      <div className={depth > 0 ? "pl-3 border-l-2 border-gray-100 space-y-2" : "space-y-3"}>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <div className="text-xs font-medium text-gray-500 mb-0.5">
              {SECTION_LABELS[k] ?? k}
            </div>
            <div className="text-sm">{renderValue(v, depth + 1)}</div>
          </div>
        ))}
      </div>
    );
  }

  return <span className="text-gray-700">{String(value)}</span>;
}

export function WorldSettingsEditor({
  projectId,
  data,
  onUpdate,
}: {
  projectId: string;
  data: WorldSettings | null;
  onUpdate: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setDraft(data ? JSON.stringify(data, null, 2) : "{}");
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    try {
      const parsed = JSON.parse(draft);
      setSaving(true);
      setError(null);
      await apiPost("update-world-settings", {
        project_id: projectId,
        setting_data: parsed,
      });
      setEditing(false);
      onUpdate();
    } catch (e) {
      if (e instanceof SyntaxError) {
        setError("JSON 格式错误");
      } else {
        setError(String(e));
      }
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="group relative">
        {data ? (
          <div className="space-y-4">
            {/* Title */}
            {"title" in data && data.title ? (
              <h2 className="text-lg font-bold text-gray-800">{String(data.title)}</h2>
            ) : null}
            {/* Genre badge */}
            {"genre" in data && data.genre ? (
              <span className="inline-block px-2 py-0.5 bg-red-50 text-red-600 text-xs rounded-full font-medium">
                {String(data.genre)}
              </span>
            ) : null}
            {/* Themes */}
            {"themes" in data && data.themes ? (
              <div>
                <h3 className="text-xs font-medium text-gray-500 mb-1">核心主题</h3>
                {renderValue(data.themes)}
              </div>
            ) : null}
            {/* World building */}
            {"world_building" in data && data.world_building ? (
              <div>
                <h3 className="text-xs font-medium text-gray-500 mb-1">世界观设定</h3>
                {renderValue(data.world_building)}
              </div>
            ) : null}
            {/* Other fields */}
            {Object.entries(data)
              .filter(([k]) => !["title", "genre", "themes", "world_building"].includes(k))
              .map(([k, v]) => (
                <div key={k}>
                  <h3 className="text-xs font-medium text-gray-500 mb-1">
                    {SECTION_LABELS[k] ?? k}
                  </h3>
                  <div className="text-sm">{renderValue(v)}</div>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-gray-400">尚未生成</p>
        )}
        {data && (
          <button
            onClick={startEdit}
            className="absolute top-0 right-0 opacity-0 group-hover:opacity-100 text-xs px-2 py-1 bg-gray-100 rounded text-gray-600 hover:bg-gray-200 transition-opacity"
          >
            编辑
          </button>
        )}
      </div>
    );
  }

  return (
    <div>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-full border rounded px-3 py-2 text-sm font-mono min-h-[200px] resize-y focus:ring-1 focus:ring-red-300"
        disabled={saving}
      />
      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
      <div className="flex gap-2 mt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-3 py-1.5 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:opacity-50"
        >
          {saving ? "保存中..." : "保存"}
        </button>
        <button
          onClick={() => setEditing(false)}
          disabled={saving}
          className="px-3 py-1.5 border rounded text-sm hover:bg-gray-50"
        >
          取消
        </button>
      </div>
    </div>
  );
}
