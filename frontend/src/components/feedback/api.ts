import { config } from "@/config";

export type Vote = "up" | "down";

export const REASONS = ["citations", "missing_group", "incomplete", "off_topic", "slow"] as const;
export type Reason = (typeof REASONS)[number];

// Feedback never blocks the user: network errors are swallowed.

export async function postVote(
  tool: string,
  vote: Vote,
  context: string | undefined,
  locale: string,
): Promise<string | null> {
  try {
    const res = await fetch(`${config.api.baseUrl}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, vote, context, locale }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return typeof data.id === "string" ? data.id : null;
  } catch {
    return null;
  }
}

export async function postDetails(
  id: string,
  details: { vote?: Vote; reasons?: Reason[]; comment?: string },
): Promise<void> {
  try {
    await fetch(`${config.api.baseUrl}/feedback/${id}/details`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(details),
    });
  } catch {
    // see above
  }
}

// Separate request with no chat or feedback reference: the address must
// never be linkable to what the person asked.
export type NewsletterSource =
  | "home"
  | "dossier"
  | "menu"
  | "landing"
  | "footer"
  | "sidebar"
  | "mobile_menu"
  | "feedback"
  | "valutazione"
  | "survey_done";

export async function subscribeNewsletter(email: string, source?: NewsletterSource): Promise<boolean> {
  try {
    const res = await fetch(`${config.api.baseUrl}/newsletter/subscribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, consent: true, source }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

let newsletterEnabled: Promise<boolean> | null = null;

// The backend hides the opt-in until the Brevo list is configured.
export function fetchNewsletterEnabled(): Promise<boolean> {
  newsletterEnabled ??= fetch(`${config.api.baseUrl}/newsletter`)
    .then((res) => (res.ok ? res.json() : { enabled: false }))
    .then((data) => data.enabled === true)
    .catch(() => false);
  return newsletterEnabled;
}

const NEWSLETTER_KEY = "prag-newsletter";

export function isSubscribed(): boolean {
  try {
    return localStorage.getItem(NEWSLETTER_KEY) === "subscribed";
  } catch {
    return false;
  }
}

export function markSubscribed() {
  try {
    localStorage.setItem(NEWSLETTER_KEY, "subscribed");
  } catch {
    // storage blocked: the opt-in shows up again, harmless
  }
}
