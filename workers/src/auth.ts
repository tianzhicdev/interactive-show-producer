/**
 * Auth utilities for Cloudflare Workers using Web Crypto API.
 *
 * Password hashing uses PBKDF2 with SHA-256.
 * Session tokens are HMAC-signed JWTs (HS256) using env.AUTH_SECRET.
 */

// --- Password hashing (PBKDF2) ---

const PBKDF2_ITERATIONS = 100_000;
const SALT_LENGTH = 16;

function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function hexToBuffer(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

function exactArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

export async function hashPassword(password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const derivedBits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt,
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    256
  );
  const hash = bufferToHex(derivedBits);
  const saltHex = bufferToHex(exactArrayBuffer(salt));
  // Store as: iterations$salt$hash
  return `${PBKDF2_ITERATIONS}$${saltHex}$${hash}`;
}

export async function verifyPassword(
  password: string,
  storedHash: string
): Promise<boolean> {
  const [iterStr, saltHex, expectedHash] = storedHash.split("$");
  const iterations = parseInt(iterStr, 10);
  const salt = hexToBuffer(saltHex);

  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const derivedBits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: exactArrayBuffer(salt),
      iterations,
      hash: "SHA-256",
    },
    keyMaterial,
    256
  );
  const hash = bufferToHex(derivedBits);
  return hash === expectedHash;
}

// --- JWT-like signed tokens (HMAC-SHA256) ---

function base64UrlEncode(data: Uint8Array | string): string {
  const str =
    typeof data === "string"
      ? btoa(data)
      : btoa(String.fromCharCode(...data));
  return str.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlDecode(str: string): string {
  let s = str.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4 !== 0) s += "=";
  return atob(s);
}

async function getHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

async function signToken(
  payload: Record<string, unknown>,
  secret: string
): Promise<string> {
  const header = base64UrlEncode(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = base64UrlEncode(JSON.stringify(payload));
  const data = `${header}.${body}`;

  const key = await getHmacKey(secret);
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(data)
  );
  const sig = base64UrlEncode(new Uint8Array(signature));
  return `${data}.${sig}`;
}

async function verifyToken(
  token: string,
  secret: string
): Promise<Record<string, unknown> | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  const [header, body, sig] = parts;
  const data = `${header}.${body}`;

  const key = await getHmacKey(secret);

  // Decode the signature
  let sigStr = sig.replace(/-/g, "+").replace(/_/g, "/");
  while (sigStr.length % 4 !== 0) sigStr += "=";
  const sigBytes = Uint8Array.from(atob(sigStr), (c) => c.charCodeAt(0));

  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    sigBytes,
    new TextEncoder().encode(data)
  );
  if (!valid) return null;

  try {
    const payload = JSON.parse(base64UrlDecode(body));
    // Check expiration
    if (payload.exp && Date.now() / 1000 > payload.exp) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

// --- Session management ---

const TOKEN_EXPIRY_SECONDS = 7 * 24 * 60 * 60; // 7 days

export async function createSession(
  userId: string,
  username: string,
  secret: string
): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return signToken(
    {
      sub: userId,
      username,
      iat: now,
      exp: now + TOKEN_EXPIRY_SECONDS,
    },
    secret
  );
}

export interface SessionPayload {
  userId: string;
  username: string;
}

export async function validateSession(
  token: string,
  secret: string
): Promise<SessionPayload | null> {
  const payload = await verifyToken(token, secret);
  if (!payload || !payload.sub) return null;
  return {
    userId: payload.sub as string,
    username: (payload.username as string) ?? "",
  };
}

// --- Request authentication middleware ---

export async function authenticateRequest(
  request: Request,
  secret: string
): Promise<SessionPayload | null> {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return null;
  }
  const token = authHeader.slice(7);
  return validateSession(token, secret);
}
