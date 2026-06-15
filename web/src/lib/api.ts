const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = localStorage.getItem("auth_token");
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}/${path}`, {
    headers: getAuthHeaders(),
    ...options,
  });
  if (res.status === 401) {
    // Clear stale token and redirect to login
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error((err as { message?: string }).message ?? "API error");
  }
  return res.json() as Promise<T>;
}

export function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

// Max text size for single POST upload (4MB of text ~ safe for JSON encoding overhead)
const SINGLE_UPLOAD_MAX = 4 * 1024 * 1024;
// Chunk size for client-side chunked upload (30K chars to match server chunker)
const CLIENT_CHUNK_SIZE = 30_000;

async function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file, "UTF-8");
  });
}

async function fetchWithRetry(
  url: string,
  options: RequestInit,
  retries = 2
): Promise<Response> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || res.status === 401 || res.status === 400) return res;
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      return res;
    } catch (err) {
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      throw err;
    }
  }
  throw new Error("Upload failed after retries");
}

function getUploadHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = localStorage.getItem("auth_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

function handleAuthError(res: Response) {
  if (res.status === 401) {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    if (window.location.pathname !== "/login") window.location.href = "/login";
    throw new Error("Authentication required");
  }
}

export async function apiUploadText(
  projectId: string,
  file: File,
  onProgress?: (message: string) => void
): Promise<{ project_id: string; total_chunks: number }> {
  onProgress?.("读取文件...");
  const text = await readFileAsText(file);

  if (!text.trim()) {
    throw new Error("文件内容为空");
  }

  const headers = getUploadHeaders();

  if (text.length <= SINGLE_UPLOAD_MAX) {
    // Small file: single POST with server-side smart chunking
    onProgress?.("上传故事文件...");
    const res = await fetchWithRetry(
      `${API_BASE}/upload-story?project_id=${projectId}`,
      { method: "POST", headers, body: JSON.stringify({ text }) }
    );
    handleAuthError(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error((err as { message?: string }).message ?? "Upload failed");
    }
    const result = await res.json() as { project_id: string; total_chunks: number };
    onProgress?.(`上传完成，共 ${result.total_chunks} 个分块`);
    return result;
  }

  // Large file: client-side chunked upload
  onProgress?.("准备分块上传...");

  // Step 1: Begin chunked upload
  const beginRes = await fetchWithRetry(
    `${API_BASE}/begin-chunked-upload`,
    { method: "POST", headers, body: JSON.stringify({ project_id: projectId }) }
  );
  handleAuthError(beginRes);
  if (!beginRes.ok) {
    const err = await beginRes.json().catch(() => ({ message: beginRes.statusText }));
    throw new Error((err as { message?: string }).message ?? "Failed to begin upload");
  }

  // Step 2: Split and upload chunks
  const totalChunks = Math.ceil(text.length / CLIENT_CHUNK_SIZE);
  let totalChars = 0;
  for (let i = 0; i < totalChunks; i++) {
    const chunkContent = text.slice(i * CLIENT_CHUNK_SIZE, (i + 1) * CLIENT_CHUNK_SIZE);
    totalChars += chunkContent.length;
    onProgress?.(`上传分块 ${i + 1}/${totalChunks}...`);

    const chunkRes = await fetchWithRetry(
      `${API_BASE}/upload-story-chunk`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          project_id: projectId,
          chunk_index: i,
          content: chunkContent,
        }),
      }
    );
    handleAuthError(chunkRes);
    if (!chunkRes.ok) {
      const err = await chunkRes.json().catch(() => ({ message: chunkRes.statusText }));
      throw new Error((err as { message?: string }).message ?? `Failed to upload chunk ${i + 1}`);
    }
  }

  // Step 3: Finalize
  onProgress?.("完成上传...");
  const finalRes = await fetchWithRetry(
    `${API_BASE}/finalize-chunked-upload`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        project_id: projectId,
        total_chunks: totalChunks,
        total_chars: totalChars,
      }),
    }
  );
  handleAuthError(finalRes);
  if (!finalRes.ok) {
    const err = await finalRes.json().catch(() => ({ message: finalRes.statusText }));
    throw new Error((err as { message?: string }).message ?? "Failed to finalize upload");
  }

  onProgress?.(`上传完成，共 ${totalChunks} 个分块`);
  return { project_id: projectId, total_chunks: totalChunks };
}
