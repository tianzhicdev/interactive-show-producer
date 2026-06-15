import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getExportArtifact, getExportArtifacts } from "../db.ts";
import { jsonResp, binaryResponse } from "../edge.ts";

export async function handleDownloadExport(
  sql: NeonSQL,
  _env: Env,
  _payload: unknown,
  request: Request
): Promise<Response> {
  const url = new URL(request.url);
  const artifactId = url.searchParams.get("artifact_id");
  const projectId = url.searchParams.get("project_id");

  if (artifactId) {
    const artifact = await getExportArtifact(sql, artifactId);
    if (!artifact) {
      return jsonResp(404, { code: 404, message: "Artifact not found" });
    }

    const fileData: unknown = artifact.file_data;
    console.log(`[download] file_data type=${typeof fileData}, constructor=${(fileData as any)?.constructor?.name}, length=${(fileData as any)?.length ?? (fileData as any)?.byteLength ?? "unknown"}`);

    // Neon serverless driver may return bytea in different formats
    let data: Uint8Array;
    if (fileData instanceof Uint8Array) {
      data = fileData;
    } else if (ArrayBuffer.isView(fileData)) {
      data = new Uint8Array((fileData as ArrayBufferView).buffer);
    } else if (fileData instanceof ArrayBuffer) {
      data = new Uint8Array(fileData);
    } else if (typeof fileData === "string") {
      // Hex-encoded bytea (Neon returns "\\x..." format)
      const hex = (fileData as string).replace(/^\\x/, "");
      const bytes = new Uint8Array(hex.length / 2);
      for (let i = 0; i < hex.length; i += 2) {
        bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
      }
      data = bytes;
    } else {
      // Try converting as-is
      console.log(`[download] Unknown data format, trying to serialize:`, JSON.stringify(fileData)?.slice(0, 200));
      return jsonResp(500, { code: 500, message: `Unknown file_data type: ${typeof fileData}` });
    }

    return binaryResponse(
      data,
      artifact.file_name,
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    );
  }

  if (projectId) {
    const artifacts = await getExportArtifacts(sql, projectId);
    return jsonResp(200, { artifacts });
  }

  return jsonResp(400, { code: 400, message: "Missing artifact_id or project_id" });
}
