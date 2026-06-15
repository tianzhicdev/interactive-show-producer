import type { Env } from "./env.ts";
import { createSQL } from "./db.ts";
import {
  optionsResponse,
  jsonResp,
  withErrorHandling,
  toEdgeResponse,
  jsonResponse,
} from "./edge.ts";
import type { QueueBatch, BackgroundJob } from "./backgroundJobsQueue.ts";
import { processBackgroundJobsBatch } from "./queueConsumer.ts";
import { getAvailableProfiles } from "./modelProfiles.ts";
import { authenticateRequest } from "./auth.ts";

// Handlers
import { handleCreateProject } from "./handlers/createProject.ts";
import { handleListProjects } from "./handlers/listProjects.ts";
import {
  handleBeginChunkedUpload,
  handleFinalizeChunkedUpload,
  handleUploadStory,
  handleUploadStoryChunk,
} from "./handlers/uploadStory.ts";
import { handleStartPhase1 } from "./handlers/startPhase1.ts";
import { handleStartPipeline } from "./handlers/startPipeline.ts";
import { handleGetPhase1Status } from "./handlers/getPhase1Status.ts";
import { handleGetPipelineStatus } from "./handlers/getPipelineStatus.ts";
import { handleGetOutline } from "./handlers/getOutline.ts";
import { handleUpdateOutline } from "./handlers/updateOutline.ts";
import { handleApprovePhase1 } from "./handlers/approvePhase1.ts";
import { handleStartScriptGen } from "./handlers/startScriptGen.ts";
import { handleGetScriptGenStatus } from "./handlers/getScriptGenStatus.ts";
import { handleGetScene } from "./handlers/getScene.ts";
import { handleRegenerateScene } from "./handlers/regenerateScene.ts";
import { handleRegenerateBranch } from "./handlers/regenerateBranch.ts";
import { handleRegenerateNodes } from "./handlers/regenerateNodes.ts";
import { handleGetDag } from "./handlers/getDag.ts";
import { handleExportDeliverables } from "./handlers/exportDeliverables.ts";
import { handleDownloadExport } from "./handlers/downloadExport.ts";
import { handleRegister, handleLogin, handleMe } from "./handlers/auth.ts";
import { handleUpdateSceneScript } from "./handlers/updateSceneScript.ts";
import { handleUpdateWorldSettings } from "./handlers/updateWorldSettings.ts";
import { handleUpdateCharacter } from "./handlers/updateCharacter.ts";
import { handleUpdateDagNode, handleDeleteDagNode } from "./handlers/updateDagNode.ts";
import { handleUpdateNodePositions } from "./handlers/updateNodePositions.ts";
import { handleUpdateStorySummary } from "./handlers/updateStorySummary.ts";
import { handleRecoverStaleJobs } from "./handlers/recoverStaleJobs.ts";
import { handleRevertSceneScript } from "./handlers/revertSceneScript.ts";
import { handleGetComments, handleCreateComment, handleDeleteComment } from "./handlers/comments.ts";

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/+|\/+$/g, "");

    if (request.method === "OPTIONS") {
      return optionsResponse();
    }

    const sql = createSQL(env.DATABASE_URL);

    // --- Public routes (no auth required) ---
    if (request.method === "GET" && path === "ping") {
      return toEdgeResponse(jsonResponse(200, { status: "ok", service: "interactive-show-api" }));
    }
    if (request.method === "POST" && path === "register") {
      return withErrorHandling(request, (payload) => handleRegister(sql, env, payload));
    }
    if (request.method === "POST" && path === "login") {
      return withErrorHandling(request, (payload) => handleLogin(sql, env, payload));
    }

    // --- Public comment routes (no auth required) ---
    if (request.method === "GET" && path === "comments") {
      return withErrorHandling(request, (_payload, req) => handleGetComments(sql, req));
    }
    if (request.method === "POST" && path === "comments") {
      return withErrorHandling(request, (payload) => handleCreateComment(sql, payload));
    }

    // --- Auth check for all other routes ---
    const session = await authenticateRequest(request, env.AUTH_SECRET);
    if (!session) {
      return jsonResp(401, { code: 401, message: "Authentication required" });
    }

    // PUT endpoints (authenticated)
    if (request.method === "PUT") {
      switch (path) {
        case "upload-story":
          return withErrorHandling(request, (payload, req) =>
            handleUploadStory(sql, env, payload, req)
          );
      }
    }

    // GET endpoints (authenticated)
    if (request.method === "GET") {
      switch (path) {
        case "me":
          return withErrorHandling(request, (payload, req) =>
            handleMe(sql, env, payload, req)
          );

        case "model-profiles":
          return toEdgeResponse(jsonResponse(200, { profiles: getAvailableProfiles() }));

        case "get-phase1-status":
          return withErrorHandling(request, (payload, req) =>
            handleGetPhase1Status(sql, env, payload, req)
          );

        case "get-pipeline-status":
          return withErrorHandling(request, (payload, req) =>
            handleGetPipelineStatus(sql, env, payload, req)
          );

        case "get-outline":
          return withErrorHandling(request, (payload, req) =>
            handleGetOutline(sql, env, payload, req)
          );

        case "get-script-gen-status":
          return withErrorHandling(request, (payload, req) =>
            handleGetScriptGenStatus(sql, env, payload, req)
          );

        case "get-scene":
          return withErrorHandling(request, (payload, req) =>
            handleGetScene(sql, env, payload, req)
          );

        case "get-dag":
          return withErrorHandling(request, (payload, req) =>
            handleGetDag(sql, env, payload, req)
          );

        case "list-projects":
          return withErrorHandling(request, () => handleListProjects(sql, env));

        case "download-export":
          try {
            return await handleDownloadExport(sql, env, null, request);
          } catch (error) {
            const message = error instanceof Error ? error.message : "Internal Server Error";
            return jsonResp(500, { code: 500, message });
          }
      }
    }

    // POST endpoints (authenticated)
    if (request.method === "POST") {
      switch (path) {
        case "create-project":
          return withErrorHandling(request, (payload) =>
            handleCreateProject(sql, env, payload)
          );

        case "upload-story":
          return withErrorHandling(request, (payload, req) =>
            handleUploadStory(sql, env, payload, req)
          );

        case "begin-chunked-upload":
          return withErrorHandling(request, (payload) =>
            handleBeginChunkedUpload(sql, env, payload)
          );

        case "upload-story-chunk":
          return withErrorHandling(request, (payload) =>
            handleUploadStoryChunk(sql, env, payload)
          );

        case "finalize-chunked-upload":
          return withErrorHandling(request, (payload) =>
            handleFinalizeChunkedUpload(sql, env, payload)
          );

        case "start-phase1":
          return withErrorHandling(request, (payload) =>
            handleStartPhase1(sql, env, payload)
          );

        case "start-pipeline":
          return withErrorHandling(request, (payload) =>
            handleStartPipeline(sql, env, payload)
          );

        case "update-outline":
          return withErrorHandling(request, (payload) =>
            handleUpdateOutline(sql, env, payload)
          );

        case "approve-phase1":
          return withErrorHandling(request, (payload) =>
            handleApprovePhase1(sql, env, payload)
          );

        case "start-script-gen":
          return withErrorHandling(request, (payload) =>
            handleStartScriptGen(sql, env, payload)
          );

        case "regenerate-scene":
          return withErrorHandling(request, (payload) =>
            handleRegenerateScene(sql, env, payload)
          );

        case "regenerate-branch":
          return withErrorHandling(request, (payload) =>
            handleRegenerateBranch(sql, env, payload)
          );

        case "regenerate-nodes":
          return withErrorHandling(request, (payload) =>
            handleRegenerateNodes(sql, env, payload)
          );

        case "export-deliverables":
          return withErrorHandling(request, (payload) =>
            handleExportDeliverables(sql, env, payload)
          );

        case "update-scene-script":
          return withErrorHandling(request, (payload) =>
            handleUpdateSceneScript(sql, env, payload)
          );

        case "update-world-settings":
          return withErrorHandling(request, (payload) =>
            handleUpdateWorldSettings(sql, env, payload)
          );

        case "update-character":
          return withErrorHandling(request, (payload) =>
            handleUpdateCharacter(sql, env, payload)
          );

        case "update-dag-node":
          return withErrorHandling(request, (payload) =>
            handleUpdateDagNode(sql, env, payload)
          );

        case "delete-dag-node":
          return withErrorHandling(request, (payload) =>
            handleDeleteDagNode(sql, env, payload)
          );

        case "update-node-positions":
          return withErrorHandling(request, (payload) =>
            handleUpdateNodePositions(sql, env, payload)
          );

        case "update-story-summary":
          return withErrorHandling(request, (payload) =>
            handleUpdateStorySummary(sql, env, payload)
          );

        case "delete-comment":
          return withErrorHandling(request, (payload) =>
            handleDeleteComment(sql, payload)
          );

        case "revert-scene-script":
          return withErrorHandling(request, (payload) =>
            handleRevertSceneScript(sql, env, payload)
          );

        case "recover-stale-jobs":
          return withErrorHandling(request, (payload) =>
            handleRecoverStaleJobs(sql, env, payload)
          );
      }
    }

    return jsonResp(404, { code: 404, message: "Not found" });
  },

  async queue(batch: QueueBatch<BackgroundJob>, env: Env): Promise<void> {
    const sql = createSQL(env.DATABASE_URL);
    await processBackgroundJobsBatch(sql, env, batch);
  },
};
