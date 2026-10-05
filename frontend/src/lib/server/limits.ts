import { createHash } from "node:crypto";

/**
 * In-memory sliding windows: enough for a single instance of the site.
 * Keys that identify a person (email addresses) are stored only as hashes.
 */
const hits = new Map<string, number[]>();

export function overLimit(key: string, max: number, windowSeconds: number): boolean {
  const now = Date.now();
  const recent = (hits.get(key) ?? []).filter((t) => now - t < windowSeconds * 1000);
  if (recent.length >= max) {
    hits.set(key, recent);
    return true;
  }
  recent.push(now);
  hits.set(key, recent);
  return false;
}

export function hashKey(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

/**
 * Client address as seen by the Railway edge. The last X-Forwarded-For entry
 * is the one the edge appends; earlier entries come from the client and can
 * be forged.
 */
export function clientIp(request: Request): string {
  const fwd = request.headers.get("x-forwarded-for");
  return fwd?.split(",").at(-1)?.trim() || "unknown";
}
