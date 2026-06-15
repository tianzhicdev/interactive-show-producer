import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost, apiGet, apiUploadText } from "@/lib/api";
import { Tutorial } from "@/components/Tutorial";

interface ModelProfile {
  id: string;
  label: string;
}

export function NewProjectPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [steeringNotes, setSteeringNotes] = useState("");
  const [modelProfileId, setModelProfileId] = useState("default");
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [step, setStep] = useState<"form" | "uploading" | "done">("form");
  const [progress, setProgress] = useState("");
  const [targetDuration, setTargetDuration] = useState<string>("30");
  const [targetChoices, setTargetChoices] = useState<string>("8");

  useEffect(() => {
    apiGet<{ profiles: ModelProfile[] }>("model-profiles").then((data) =>
      setProfiles(data.profiles)
    );
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !file) return;

    try {
      setUploading(true);
      setStep("uploading");
      setProgress("创建项目...");

      const { project } = await apiPost<{ project: { id: string } }>("create-project", {
        name,
        model_profile_id: modelProfileId,
        steering_notes: steeringNotes || undefined,
        target_duration_minutes: targetDuration ? parseInt(targetDuration) : undefined,
        target_choice_count: targetChoices ? parseInt(targetChoices) : undefined,
      });

      setProgress("上传故事文件...");
      const result = await apiUploadText(project.id, file, setProgress);
      setProgress(`上传完成，共 ${result.total_chunks} 个分块`);

      setStep("done");
      setTimeout(() => navigate(`/project/${project.id}`), 1000);
    } catch (err) {
      alert(err instanceof Error ? err.message : "创建失败");
      setStep("form");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-6 py-4">
        <h1 className="text-xl font-bold text-red-600">新建项目</h1>
      </header>

      <main className="max-w-2xl mx-auto p-6">
        <Tutorial
          id="new-project"
          title="创建新互动剧项目"
          steps={[
            "上传小说原文 TXT 文件（支持最大 38MB）",
            "设定目标时长和互动选择点数量来控制剧本规模",
            "选择 AI 模型配置，并按所选配置完成后续生成",
            "可选填写导演备注来引导 AI 生成方向",
          ]}
        />
        {step === "uploading" || step === "done" ? (
          <div className="bg-white rounded-lg border p-8 text-center">
            <div className="animate-pulse text-lg">{progress}</div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="bg-white rounded-lg border p-6 space-y-5">
            <div>
              <label className="block text-sm font-medium mb-1">项目名称</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-300"
                placeholder="例：全民公路求生"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">故事文件 (.txt)</label>
              <input
                type="file"
                accept=".txt"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full border rounded-lg px-3 py-2"
                required
              />
              {file && (
                <p className="text-sm text-gray-400 mt-1">
                  {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">目标总时长（分钟）</label>
                <input
                  type="number"
                  value={targetDuration}
                  onChange={(e) => setTargetDuration(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="30"
                  min={5}
                  max={600}
                />
                <p className="text-xs text-gray-400 mt-1">每个场景约1-2分钟</p>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">互动选择点数量</label>
                <input
                  type="number"
                  value={targetChoices}
                  onChange={(e) => setTargetChoices(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="8"
                  min={1}
                  max={100}
                />
                <p className="text-xs text-gray-400 mt-1">观众做选择的节点数</p>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">模型配置</label>
              <select
                value={modelProfileId}
                onChange={(e) => setModelProfileId(e.target.value)}
                className="w-full border rounded-lg px-3 py-2"
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">导演备注（可选）</label>
              <textarea
                value={steeringNotes}
                onChange={(e) => setSteeringNotes(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 h-24 resize-none"
                placeholder="例：希望增加感情线分支，减少战斗场景..."
              />
            </div>

            <button
              type="submit"
              disabled={uploading || !name || !file}
              className="w-full py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              创建并上传
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
