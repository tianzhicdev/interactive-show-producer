import { useEffect, useState, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

interface ExportArtifact {
  id: string;
  artifact_type: string;
  file_name: string;
  created_at: string;
}

const ARTIFACT_LABELS: Record<string, string> = {
  standardization: "互动剧本标准化表",
  world_characters: "世界/角色设定文档",
  plot_interaction: "剧情/交互设定文档",
  full_script: "完整剧本正文",
};

function getArtifactLabel(type: string): string {
  if (ARTIFACT_LABELS[type]) return ARTIFACT_LABELS[type];
  // Handle per-episode types like "episode_script_EP01"
  const match = type.match(/^episode_script_(EP\d+)$/);
  if (match) return `剧本 ${match[1]}`;
  return type;
}

async function downloadArtifact(artifactId: string, fileName: string) {
  const token = localStorage.getItem("auth_token");
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}/download-export?artifact_id=${artifactId}`, { headers });
  if (!res.ok) throw new Error("Download failed");

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ExportPanel({ projectId }: { projectId: string }) {
  const [artifacts, setArtifacts] = useState<ExportArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const fetchArtifacts = useCallback(async () => {
    const data = await apiGet<{ artifacts: ExportArtifact[] }>(`download-export?project_id=${projectId}`);
    setArtifacts(data.artifacts);
    return data.artifacts;
  }, [projectId]);

  useEffect(() => {
    fetchArtifacts().finally(() => setLoading(false));
  }, [fetchArtifacts]);

  async function handleExport() {
    setExporting(true);
    try {
      await apiPost("export-deliverables", { project_id: projectId });
      // Poll for artifacts to appear
      const poll = setInterval(async () => {
        try {
          const arts = await fetchArtifacts();
          if (arts.length > 0) {
            clearInterval(poll);
            setExporting(false);
          }
        } catch {
          // keep polling
        }
      }, 3000);
      // Safety timeout: stop after 2 minutes
      setTimeout(() => {
        clearInterval(poll);
        setExporting(false);
      }, 120000);
    } catch {
      setExporting(false);
    }
  }

  async function handleDownload(artifact: ExportArtifact) {
    setDownloading(artifact.id);
    try {
      await downloadArtifact(artifact.id, artifact.file_name);
    } catch (e) {
      alert(`下载失败: ${e instanceof Error ? e.message : "Unknown error"}`);
    } finally {
      setDownloading(null);
    }
  }

  if (loading) {
    return <div className="text-gray-400">加载中...</div>;
  }

  if (artifacts.length === 0) {
    return (
      <div className="space-y-3">
        <div className="text-gray-400">
          {exporting
            ? "正在生成导出文件..."
            : "尚未导出。点击下方按钮生成 DOCX 文件。"}
        </div>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="px-4 py-2 bg-emerald-500 text-white rounded text-sm hover:bg-emerald-600 disabled:opacity-50 flex items-center gap-2"
        >
          {exporting && (
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          )}
          {exporting ? "导出中..." : "导出交付物"}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {artifacts.map((artifact) => (
        <div key={artifact.id} className="flex items-center justify-between border rounded p-3">
          <div>
            <p className="font-medium text-sm">
              {getArtifactLabel(artifact.artifact_type)}
            </p>
            <p className="text-xs text-gray-400">
              {new Date(artifact.created_at).toLocaleString("zh-CN")}
            </p>
          </div>
          <button
            onClick={() => handleDownload(artifact)}
            disabled={downloading === artifact.id}
            className="px-3 py-1 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:opacity-50"
          >
            {downloading === artifact.id ? "下载中..." : "下载"}
          </button>
        </div>
      ))}
      <button
        onClick={handleExport}
        disabled={exporting}
        className="px-3 py-1.5 border border-emerald-300 text-emerald-600 rounded text-sm hover:bg-emerald-50 disabled:opacity-50 flex items-center gap-2"
      >
        {exporting && (
          <span className="w-3 h-3 border-2 border-emerald-300 border-t-emerald-600 rounded-full animate-spin" />
        )}
        {exporting ? "重新导出中..." : "重新导出"}
      </button>
    </div>
  );
}
