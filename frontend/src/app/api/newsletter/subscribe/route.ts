import { BREVO_DOI_URL, brevoConfigured } from "../brevo";
import { clientIp, hashKey, overLimit } from "@/lib/server/limits";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const SITE_URL = process.env.PUBLIC_SITE_URL || "https://www.parliamentrag.it";

/**
 * Double opt-in through Brevo. The address goes straight to Brevo and is never
 * stored here; Brevo records the confirmation date and IP as proof of consent.
 */
export async function POST(request: Request) {
  if (!brevoConfigured()) return Response.json({ detail: "newsletter disabled" }, { status: 503 });

  const body = await request.json().catch(() => null);
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  if (body?.consent !== true || email.length < 5 || email.length > 254 || !EMAIL_RE.test(email)) {
    return Response.json({ detail: "invalid request" }, { status: 400 });
  }
  // Every accepted request makes Brevo send an email: without limits the form
  // could flood a third party's inbox.
  if (overLimit(`ip:${clientIp(request)}`, 5, 3600)) {
    return Response.json({ detail: "too many requests" }, { status: 429 });
  }
  if (overLimit(`email:${hashKey(email)}`, 2, 86400)) {
    // Same answer as a fresh request: the endpoint must not reveal who asked
    // recently, and the first confirmation email is still valid.
    return Response.json({ ok: true });
  }

  const res = await fetch(BREVO_DOI_URL, {
    method: "POST",
    headers: { "api-key": process.env.BREVO_API_KEY!, accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      email,
      includeListIds: [Number(process.env.BREVO_LIST_ID)],
      templateId: Number(process.env.BREVO_DOI_TEMPLATE_ID),
      redirectionUrl: `${SITE_URL}/newsletter/confirmed`,
    }),
  });
  // An address already on the list gets the same answer as a new one: the
  // endpoint must not reveal who is subscribed.
  if (!res.ok) {
    const text = await res.text();
    if (!text.toLowerCase().includes("duplicate")) {
      console.warn(`[newsletter] brevo ${res.status}: ${text.slice(0, 200)}`);
      return Response.json({ detail: "subscription failed" }, { status: 502 });
    }
  }
  console.info(`[newsletter] confirmation requested source=${typeof body.source === "string" ? body.source.slice(0, 20) : "unknown"}`);
  return Response.json({ ok: true });
}
