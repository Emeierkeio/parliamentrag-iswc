import { redirect } from "next/navigation";

/* Old shared-answer links: the answer now lives inside its dossier, opened
   on the full-text reader. */
export default async function SharedChatRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/tema/${encodeURIComponent(id)}?leggi=1`);
}
