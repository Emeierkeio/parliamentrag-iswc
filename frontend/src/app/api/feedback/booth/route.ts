import { db } from "@/lib/server/db";
import { clientIp, overLimit } from "@/lib/server/limits";

/** Answers to the ISWC 2026 booth questionnaire (/iswc): four 1-5 scales, role, comment. */
export async function POST(request: Request) {
  if (overLimit(`booth:${clientIp(request)}`, 10, 3600)) {
    return Response.json({ detail: "too many requests" }, { status: 429 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") return Response.json({ detail: "invalid request" }, { status: 400 });

  const scale = (v: unknown) => (Number.isInteger(v) && (v as number) >= 1 && (v as number) <= 5 ? (v as number) : null);
  const text = (v: unknown, max: number) => (typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null);
  const row = {
    q1: scale(body.q1), q2: scale(body.q2), q3: scale(body.q3), q4: scale(body.q4),
    role: text(body.role, 30),
    comment: text(body.comment, 1000),
    locale: text(body.locale, 5),
  };
  if (row.q1 === null && row.q2 === null && row.q3 === null && row.q4 === null) {
    return Response.json({ detail: "invalid request" }, { status: 400 });
  }
  try {
    const sql = await db();
    const [saved] = await sql`INSERT INTO booth_survey ${sql(row)} RETURNING id`;
    return Response.json({ id: saved.id });
  } catch (err) {
    console.error("[booth] save failed", err);
    return Response.json({ detail: "storage unavailable" }, { status: 503 });
  }
}
