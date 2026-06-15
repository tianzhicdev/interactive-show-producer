import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Comment {
  id: string;
  project_id: string;
  node_key: string | null;
  content: string;
  author: string | null;
  created_at: string;
  deleted_at: string | null;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}

export function Comments({
  projectId,
  nodeKey,
}: {
  projectId: string;
  nodeKey?: string;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [content, setContent] = useState("");
  const [author, setAuthor] = useState(() => localStorage.getItem("comment_author") || "");
  const [submitting, setSubmitting] = useState(false);

  const fetchComments = useCallback(async () => {
    const params = nodeKey
      ? `project_id=${projectId}&node_key=${nodeKey}`
      : `project_id=${projectId}`;
    const data = await apiGet<{ comments: Comment[] }>(`comments?${params}`);
    setComments(data.comments);
  }, [projectId, nodeKey]);

  useEffect(() => {
    fetchComments();
  }, [fetchComments]);

  async function handleSubmit() {
    if (!content.trim()) return;
    if (author) localStorage.setItem("comment_author", author);

    // Optimistic update — show immediately
    const optimistic: Comment = {
      id: `temp-${Date.now()}`,
      project_id: projectId,
      node_key: nodeKey || null,
      content: content.trim(),
      author: author.trim() || null,
      created_at: new Date().toISOString(),
      deleted_at: null,
    };
    setSubmitting(true);
    setComments((prev) => [...prev, optimistic]);
    setContent("");

    try {
      await apiPost("comments", {
        project_id: projectId,
        node_key: nodeKey || null,
        content: optimistic.content,
        author: optimistic.author,
      });
      await fetchComments();
    } catch {
      setComments((prev) => prev.filter((c) => c.id !== optimistic.id));
      setContent(optimistic.content);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(commentId: string) {
    setComments((prev) =>
      prev.map((c) =>
        c.id === commentId ? { ...c, content: "", deleted_at: new Date().toISOString() } : c
      )
    );

    try {
      await apiPost("delete-comment", {
        project_id: projectId,
        comment_id: commentId,
      });
      await fetchComments();
    } catch {
      await fetchComments();
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto p-3 space-y-3">
        {comments.length === 0 && (
          <p className="text-gray-400 text-sm text-center py-4">暂无评论</p>
        )}
        {comments.map((c) => (
          <div key={c.id} className="bg-gray-50 rounded-lg p-3 text-sm">
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium text-gray-700">{c.author || "匿名"}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{timeAgo(c.created_at)}</span>
                {!c.deleted_at && !c.id.startsWith("temp-") && (
                  <button
                    onClick={() => handleDelete(c.id)}
                    className="text-xs text-gray-400 hover:text-red-500"
                  >
                    删除
                  </button>
                )}
              </div>
            </div>
            {c.node_key && (
              <span className="text-[10px] bg-gray-200 text-gray-500 px-1.5 py-0.5 rounded mb-1 inline-block">
                {c.node_key}
              </span>
            )}
            {c.deleted_at ? (
              <p className="text-gray-400 italic">评论已删除</p>
            ) : (
              <p className="text-gray-600 whitespace-pre-wrap">{c.content}</p>
            )}
          </div>
        ))}
      </div>
      <div className="border-t p-3 space-y-2">
        <input
          type="text"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          placeholder="你的名字（可选）"
          className="w-full px-2 py-1 border rounded text-sm focus:outline-none focus:ring-1 focus:ring-red-300"
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="写下评论..."
          rows={2}
          className="w-full px-2 py-1 border rounded text-sm resize-none focus:outline-none focus:ring-1 focus:ring-red-300"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !content.trim()}
          className="px-3 py-1 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:opacity-50 w-full"
        >
          {submitting ? "提交中..." : "提交评论"}
        </button>
      </div>
    </div>
  );
}
