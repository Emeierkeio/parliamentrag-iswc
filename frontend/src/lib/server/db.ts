import postgres from "postgres";

let sql: ReturnType<typeof postgres> | null = null;
let ready: Promise<unknown> | null = null;

/** Connection to the site's Postgres (DATABASE_URL), with the booth table created on first use. */
export async function db() {
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL not set");
  sql ??= postgres(process.env.DATABASE_URL, { max: 3, idle_timeout: 20 });
  ready ??= sql`
    CREATE TABLE IF NOT EXISTS booth_survey (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at timestamptz NOT NULL DEFAULT now(),
      q1 smallint, q2 smallint, q3 smallint, q4 smallint,
      role text, comment text, locale text, source text NOT NULL DEFAULT 'booth'
    )`;
  await ready;
  return sql;
}
