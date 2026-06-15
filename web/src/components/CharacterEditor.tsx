import { useState } from "react";
import { apiPost } from "@/lib/api";

interface CharacterData {
  id: string;
  name: string;
  profile_data: Record<string, unknown>;
}

const FIELD_LABELS: Record<string, string> = {
  role: "角色定位",
  description: "角色简介",
  personality: "性格特征",
  abilities: "能力特长",
  relationships: "人物关系",
  first_appearance: "首次登场",
  appearance: "外貌特征",
  background: "背景故事",
  motivation: "核心动机",
  arc: "角色弧线",
};

function getDisplayField(data: Record<string, unknown>): string {
  // Try common description fields in priority order
  for (const key of ["description", "personality", "role", "background"]) {
    const val = data[key];
    if (typeof val === "string" && val.length > 0) return val;
  }
  // Fallback: first string value
  for (const val of Object.values(data)) {
    if (typeof val === "string" && val.length > 0) return val;
  }
  return "";
}

function renderFieldValue(value: unknown): React.ReactNode {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return (
      <ul className="list-disc list-inside space-y-0.5">
        {value.map((item, i) => (
          <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
        ))}
      </ul>
    );
  }
  return JSON.stringify(value, null, 2);
}

export function CharacterEditor({
  projectId,
  characters,
  onUpdate,
}: {
  projectId: string;
  characters: CharacterData[];
  onUpdate: () => void;
}) {
  const [editingName, setEditingName] = useState<string | null>(null);
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit(char: CharacterData) {
    setEditingName(char.name);
    setDraft(JSON.stringify(char.profile_data, null, 2));
    setError(null);
  }

  async function handleSave() {
    if (!editingName) return;
    try {
      const parsed = JSON.parse(draft);
      setSaving(true);
      setError(null);
      await apiPost("update-character", {
        project_id: projectId,
        name: editingName,
        profile_data: parsed,
      });
      setEditingName(null);
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

  if (characters.length === 0) {
    return <p className="text-gray-400">尚未生成</p>;
  }

  return (
    <div className="space-y-2">
      {characters.map((c) => {
        const isEditing = editingName === c.name;
        const isExpanded = expandedName === c.name;
        const role = typeof c.profile_data.role === "string" ? c.profile_data.role : "";
        const desc = getDisplayField(c.profile_data);

        return (
          <div key={c.id} className="border rounded-lg overflow-hidden">
            {isEditing ? (
              <div className="p-3">
                <h3 className="font-medium mb-2">{c.name}</h3>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="w-full border rounded px-2 py-1 text-xs font-mono min-h-[160px] resize-y"
                  disabled={saving}
                />
                {error && <p className="text-[10px] text-red-500 mt-1">{error}</p>}
                <div className="flex gap-1 mt-1.5">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-2 py-0.5 bg-red-500 text-white rounded text-[10px] hover:bg-red-600 disabled:opacity-50"
                  >
                    {saving ? "..." : "保存"}
                  </button>
                  <button
                    onClick={() => setEditingName(null)}
                    className="px-2 py-0.5 border rounded text-[10px] hover:bg-gray-50"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <div
                className="p-3 cursor-pointer hover:bg-gray-50 group"
                onClick={() => setExpandedName(isExpanded ? null : c.name)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-sm">{c.name}</h3>
                    {role && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
                        {role}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        startEdit(c);
                      }}
                      className="opacity-0 group-hover:opacity-100 text-[10px] px-1.5 py-0.5 bg-gray-100 rounded text-gray-500 hover:bg-gray-200 transition-opacity"
                    >
                      编辑
                    </button>
                    <span className="text-gray-300 text-xs">{isExpanded ? "▲" : "▼"}</span>
                  </div>
                </div>
                {!isExpanded && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{desc}</p>
                )}
                {isExpanded && (
                  <div className="mt-2 space-y-2">
                    {Object.entries(c.profile_data).map(([k, v]) => {
                      if (v == null || (typeof v === "string" && v.length === 0)) return null;
                      return (
                        <div key={k}>
                          <div className="text-[10px] font-medium text-gray-400 mb-0.5">
                            {FIELD_LABELS[k] ?? k}
                          </div>
                          <div className="text-xs text-gray-700">
                            {renderFieldValue(v)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
