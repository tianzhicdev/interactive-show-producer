import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { jsonResponse, type JsonResponse } from "../edge.ts";
import {
  hashPassword,
  verifyPassword,
  createSession,
  authenticateRequest,
} from "../auth.ts";

// --- Register ---

interface RegisterPayload {
  username?: string;
  password?: string;
}

export async function handleRegister(
  sql: NeonSQL,
  env: Env,
  payload: unknown
): Promise<JsonResponse<unknown>> {
  const { username, password } = (payload ?? {}) as RegisterPayload;

  if (!username || !password) {
    return jsonResponse(400, { message: "username and password are required" });
  }
  if (username.length < 2 || username.length > 50) {
    return jsonResponse(400, { message: "username must be 2-50 characters" });
  }
  if (password.length < 6) {
    return jsonResponse(400, { message: "password must be at least 6 characters" });
  }

  // Check if username is taken
  const existing = await sql`SELECT id FROM users WHERE username = ${username} LIMIT 1`;
  if (existing.length > 0) {
    return jsonResponse(409, { message: "username already taken" });
  }

  const passwordHash = await hashPassword(password);
  const rows = await sql`
    INSERT INTO users (username, password_hash)
    VALUES (${username}, ${passwordHash})
    RETURNING id, username, created_at
  `;
  const user = rows[0] as unknown as { id: string; username: string; created_at: string };

  const token = await createSession(user.id, user.username, env.AUTH_SECRET);

  return jsonResponse(200, {
    token,
    user: { id: user.id, username: user.username, created_at: user.created_at },
  });
}

// --- Login ---

interface LoginPayload {
  username?: string;
  password?: string;
}

export async function handleLogin(
  sql: NeonSQL,
  env: Env,
  payload: unknown
): Promise<JsonResponse<unknown>> {
  const { username, password } = (payload ?? {}) as LoginPayload;

  if (!username || !password) {
    return jsonResponse(400, { message: "username and password are required" });
  }

  const rows = await sql`
    SELECT id, username, password_hash, created_at FROM users WHERE username = ${username} LIMIT 1
  `;
  if (rows.length === 0) {
    return jsonResponse(401, { message: "invalid username or password" });
  }
  const user = rows[0] as unknown as {
    id: string;
    username: string;
    password_hash: string;
    created_at: string;
  };

  const valid = await verifyPassword(password, user.password_hash);
  if (!valid) {
    return jsonResponse(401, { message: "invalid username or password" });
  }

  const token = await createSession(user.id, user.username, env.AUTH_SECRET);

  return jsonResponse(200, {
    token,
    user: { id: user.id, username: user.username, created_at: user.created_at },
  });
}

// --- Me (get current user) ---

export async function handleMe(
  sql: NeonSQL,
  env: Env,
  _payload: unknown,
  request: Request
): Promise<JsonResponse<unknown>> {
  const session = await authenticateRequest(request, env.AUTH_SECRET);
  if (!session) {
    return jsonResponse(401, { message: "not authenticated" });
  }

  const rows = await sql`
    SELECT id, username, created_at FROM users WHERE id = ${session.userId} LIMIT 1
  `;
  if (rows.length === 0) {
    return jsonResponse(401, { message: "user not found" });
  }
  const user = rows[0] as unknown as { id: string; username: string; created_at: string };

  return jsonResponse(200, { user });
}
