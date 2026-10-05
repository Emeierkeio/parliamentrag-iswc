"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CopyLink() {
  const t = useTranslations("Dossier");
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => {
        navigator.clipboard?.writeText(window.location.href).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      {copied ? <Check aria-hidden /> : <Link2 aria-hidden />}
      <span aria-live="polite">{copied ? t("copied") : t("copyLink")}</span>
    </Button>
  );
}
