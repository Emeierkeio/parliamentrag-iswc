import { useTranslations } from "next-intl";
import { ArrowUpRight, BadgeCheck } from "lucide-react";
import { officialSpeechUrl } from "@/lib/sources";

/* One icon per quote: the check when the text was found verbatim in the
   record, an arrow otherwise; either opens the official record. */
export function SourceLink({ id, verified }: { id: string; verified: boolean }) {
  const t = useTranslations("Dossier");
  const href = officialSpeechUrl(id);
  const label = verified ? `${t("verified")} · ${t("openRecord")}` : t("openRecord");
  const Icon = verified ? BadgeCheck : ArrowUpRight;
  const tone = verified ? "text-vote-favor" : "text-fg-muted";
  if (!href) return verified ? <Icon className={`size-3.5 ${tone}`} aria-label={t("verified")} /> : null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={label}
      aria-label={label}
      className={`inline-flex size-6 items-center justify-center rounded-full transition-colors hover:bg-surface-muted ${tone}`}
    >
      <Icon className="size-3.5" aria-hidden />
    </a>
  );
}
