/* Official Camera stenographic record, anchored on the speech: ids look like
   leg19_sed510_tit00040.sub00010.int00020 (chunk suffixes are dropped). */
export function officialSpeechUrl(id: string | null | undefined): string | null {
  const match = id?.replace(/_chunk_\d+$/, "").match(/^leg(\d+)_sed(\d+)_(.+)$/);
  if (!match) return null;
  const [, leg, sed, rest] = match;
  const seduta = sed.padStart(4, "0");
  return `https://www.camera.it/leg${leg}/410?idSeduta=${seduta}&tipo=stenografico#sed${seduta}.stenografico.${rest}`;
}
