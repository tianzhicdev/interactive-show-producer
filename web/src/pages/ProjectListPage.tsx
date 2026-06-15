import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "@/lib/api";
import type { Project } from "@/hooks/useProject";
import { Tutorial } from "@/components/Tutorial";
import { ProgressBar } from "@/components/ProgressBar";

interface ProjectWithProgress extends Project {
  progress?: { total: number; done: number; running: number; failed: number; percent: number };
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-gray-100 text-gray-600" },
  uploading: { label: "上传中", color: "bg-blue-100 text-blue-600" },
  phase1_running: { label: "Phase 1 运行中", color: "bg-yellow-100 text-yellow-700" },
  phase1_ready: { label: "Phase 1 完成", color: "bg-green-100 text-green-700" },
  phase2_running: { label: "Phase 2 运行中", color: "bg-yellow-100 text-yellow-700" },
  phase2_ready: { label: "Phase 2 完成", color: "bg-green-100 text-green-700" },
  done: { label: "已完成", color: "bg-emerald-100 text-emerald-700" },
};

export function ProjectListPage() {
  const [projects, setProjects] = useState<ProjectWithProgress[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchProjects = useCallback(() => {
    apiGet<{ projects: ProjectWithProgress[] }>("list-projects")
      .then((data) => setProjects(data.projects))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // Auto-refresh when any project is running
  const hasRunning = projects.some(
    (p) => p.status === "phase1_running" || p.status === "phase2_running"
  );
  useEffect(() => {
    if (!hasRunning) return;
    const timer = setInterval(fetchProjects, 5000);
    return () => clearInterval(timer);
  }, [hasRunning, fetchProjects]);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-red-600">互动剧本生成器</h1>
        <Link
          to="/new"
          className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
        >
          新建项目
        </Link>
      </header>

      <main className="max-w-5xl mx-auto p-6">
        <Tutorial
          id="project-list"
          title="欢迎使用互动剧本生成器"
          steps={[
            "点击「新建项目」上传小说原文 TXT 文件",
            "系统会自动分析故事内容，生成世界观、角色和互动剧情结构",
            "在 Phase 1 完成后审核并编辑大纲，然后启动 Phase 2 生成完整剧本",
            "最后导出符合平台标准的 4 份交付文档",
          ]}
        />
        {loading ? (
          <div className="text-center py-20 text-gray-400">加载中...</div>
        ) : projects.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-gray-400 mb-4">还没有项目</p>
            <Link
              to="/new"
              className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
            >
              创建第一个项目
            </Link>
          </div>
        ) : (
          <div className="grid gap-4">
            {projects.map((project) => {
              const status = STATUS_LABELS[project.status] ?? STATUS_LABELS.draft;
              const isRunning = project.status === "phase1_running" || project.status === "phase2_running";
              const prog = project.progress;
              return (
                <Link
                  key={project.id}
                  to={`/project/${project.id}`}
                  className="bg-white rounded-lg border p-5 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-lg font-semibold">{project.name}</h2>
                      <p className="text-sm text-gray-400 mt-1">
                        {new Date(project.created_at).toLocaleDateString("zh-CN")}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      {isRunning && prog && (
                        <span className="text-xs text-gray-400 tabular-nums">
                          {prog.done}/{prog.total} ({prog.percent}%)
                        </span>
                      )}
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                  </div>
                  {isRunning && prog && (
                    <div className="mt-3">
                      <ProgressBar percent={prog.percent} size="sm" />
                      {prog.failed > 0 && (
                        <p className="text-xs text-red-500 mt-1">{prog.failed} 个任务失败</p>
                      )}
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
