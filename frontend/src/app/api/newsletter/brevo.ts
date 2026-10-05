export const BREVO_DOI_URL = "https://api.brevo.com/v3/contacts/doubleOptinConfirmation";

export function brevoConfigured(): boolean {
  return Boolean(process.env.BREVO_API_KEY && process.env.BREVO_LIST_ID && process.env.BREVO_DOI_TEMPLATE_ID);
}
