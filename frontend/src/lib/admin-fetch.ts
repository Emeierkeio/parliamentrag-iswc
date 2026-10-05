/**
 * fetch() for the admin-only backend endpoints (evaluation dashboard, survey
 * listings, live config changes). The backend wants an admin X-API-Key; the
 * key is asked once, kept in this browser's localStorage and forwarded by the
 * /api proxy. Nothing is ever baked into the bundle.
 */

const STORAGE_KEY = "parliamentrag-admin-key";

function readKey(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeKey(key: string) {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: the key lasts for this call only
  }
}

function withKey(init: RequestInit, key: string): RequestInit {
  const headers = new Headers(init.headers);
  if (key) headers.set("X-API-Key", key);
  return { ...init, headers };
}

export async function adminFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const used = readKey();
  const response = await fetch(input, withKey(init, used));
  if ((response.status !== 401 && response.status !== 403) || typeof window === "undefined") {
    return response;
  }
  // A parallel call may have stored a new key while this one was in flight
  let key = readKey();
  if (!key || key === used) {
    key = window.prompt("Chiave admin / Admin key")?.trim() || "";
    if (!key) return response;
    writeKey(key);
  }
  const retry = await fetch(input, withKey(init, key));
  if (retry.status === 401 || retry.status === 403) writeKey("");
  return retry;
}
