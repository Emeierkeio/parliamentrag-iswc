import siteData from "@/data/site-data.json";

/** Date of the last graph update, from the snapshot in src/data/site-data.json. */
export function useLastUpdate(): string {
  return siteData.last_update;
}

/** DD/MM/YYYY, the compact format used by the sidebar/nav footers. */
export function formatLastUpdateShort(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
