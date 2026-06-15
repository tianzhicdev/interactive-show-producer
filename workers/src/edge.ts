import { ZodError } from "zod";

export interface JsonResponse<T> {
  status: number;
  body: T;
}

export function jsonResponse<T>(status: number, body: T): JsonResponse<T> {
  return { status, body };
}

const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type, authorization",
  "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
};

export function jsonResp(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

export function toEdgeResponse<T>(response: JsonResponse<T>): Response {
  return jsonResp(response.status, response.body);
}

export function optionsResponse(): Response {
  return new Response("ok", { headers: corsHeaders });
}

export function binaryResponse(data: Uint8Array, fileName: string, contentType: string): Response {
  return new Response(data as unknown as BodyInit, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Disposition": `attachment; filename="${fileName}"`,
      ...corsHeaders,
    },
  });
}

export async function withErrorHandling(
  request: Request,
  handler: (payload: unknown, request: Request) => Promise<JsonResponse<unknown>> | JsonResponse<unknown>
): Promise<Response> {
  if (request.method === "OPTIONS") {
    return optionsResponse();
  }

  try {
    const payload = (request.method === "GET" || request.method === "PUT") ? {} : await request.json().catch(() => ({}));
    const response = await handler(payload, request);
    return toEdgeResponse(response);
  } catch (error) {
    if (error instanceof ZodError) {
      return jsonResp(400, {
        code: 400,
        message: "Invalid request payload",
        issues: error.issues,
      });
    }

    const message = error instanceof Error ? error.message : "Internal Server Error";
    console.error("Handler error:", error);
    return jsonResp(500, { code: 500, message });
  }
}
