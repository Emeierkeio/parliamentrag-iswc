/*
 * Hand-off from other services (Stenografo links to /?q=<question>): the
 * question is prefilled in the question box and never sent on its own.
 * It is read once, as plain text, capped, and removed from the URL so a
 * reload or a shared link does not carry it again.
 */
export const HANDOFF_MAX_CHARS = 500;

export function takeHandoffQuery(): string | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const raw = url.searchParams.get("q");
  if (raw === null) return null;
  url.searchParams.delete("q");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  const text = raw
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, HANDOFF_MAX_CHARS);
  return text || null;
}
