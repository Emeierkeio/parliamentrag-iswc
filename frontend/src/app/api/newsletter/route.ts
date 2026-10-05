import { brevoConfigured } from "./brevo";

export function GET() {
  return Response.json({ enabled: brevoConfigured() });
}
