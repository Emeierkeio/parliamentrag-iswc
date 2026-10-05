import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

/** Title and description of a research-site page, from Centro.meta.<page>. */
export async function centroMetadata(page: string, path: string): Promise<Metadata> {
  const t = await getTranslations("Centro.meta");
  const title = t(`${page}Title`);
  const description = t(`${page}Desc`);
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { title, description, url: path, siteName: "ParliamentRAG", type: "website" },
  };
}
