/*
 * Factual questions (who, how many, when, how did X vote) have one answer
 * and a source: Stenografo answers them. ParliamentRAG compares the groups'
 * positions on a topic. The check runs before the pipeline is started, so
 * it is a cheap pattern match; cues for positions win over factual ones.
 */
const POSITION_CUES =
  /\b(posizion\w*|cosa pens\w+|che ne pens\w+|opinion\w*|confront\w*|dibattit\w*|schieramento|ragione|maggioranza [eo] opposizione|favorevol\w+ o contrar\w+|positions?|think about|stance)\b/i;

const FACTUAL_CUES = [
  /\bcome ha(nno)? votato\b/i,
  /\b(ha|hanno) votato (a favore|contro|per|sul|sulla)\b/i,
  /\b(esito|risultato) (del|della|dei|delle) vot\w+\b/i,
  /^\s*(chi|quant[ieoa]|quando|dove)\b/i,
  /^\s*in (che|quale) (data|giorno|anno|seduta)\b/i,
  /^\s*(qual|quale) (è|e'|era) (il|la|lo) (numero|nome|data|esito|risultato|presidente|relatore)\b/i,
  /^\s*(a|di|in) (che|quale) (gruppo|partito|commissione)\b/i,
  /^\s*(cosa|che cosa) (è successo|si è deciso|è stato approvato)\b/i,
  /^\s*(who|how many|when|how did .+ vote)\b/i,
];

export function isFactualQuestion(text: string): boolean {
  const q = text.trim();
  if (q.split(/\s+/).length < 3 || POSITION_CUES.test(q)) return false;
  return FACTUAL_CUES.some((re) => re.test(q));
}

export function stenografoUrl(q: string): string {
  return `https://stenografo.it/?q=${encodeURIComponent(q)}`;
}
