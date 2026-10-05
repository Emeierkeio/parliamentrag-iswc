# Ecosistema: ParliamentRAG e Stenografo

ParliamentRAG e Stenografo leggono lo stesso grafo della Camera e rispondono a
domande diverse. Stenografo dà fatti puntuali (come ha votato Conte, chi presiede
una commissione); ParliamentRAG mette a confronto le posizioni dei gruppi su un
tema, con citazioni verbatim. Il redesign porta ParliamentRAG sul design system
di Stenografo, così i due servizi si riconoscono come parte della stessa famiglia
e chi passa dall'uno all'altro non deve reimparare l'interfaccia.

Fonte dei token: `aulachiara/apps/web/src/tokens` e
`aulachiara/docs/DESIGN_SYSTEM.md`. In questo repo la copia sta in
`frontend/src/tokens/ecosystem.css`; quando i prodotti saranno tre conviene
estrarla in un pacchetto condiviso.

## Audit di Stenografo

Cosa funziona e va adottato così com'è:

- **Palette inchiostro e carta** con neutri leggermente verdi, un solo accento di
  prodotto e contrasti misurati (WCAG 2.2 AA, numeri nei token). Il dark mode è
  una palette propria, non un'inversione.
- **Tipografia a tre voci**: Geist per l'interfaccia, Geist Mono per le etichette
  funzionali (DOMANDA, FONTI, numeri di fonte), Source Serif 4 al taglio testo
  solo per titoli display e citazioni verbatim.
- **Forma**: i contenitori sono rettangoli (raggi 6, 10, 14), le azioni sono
  pillole. Due sole ombre, per gli elementi che galleggiano.
- **Neutralità**: gli esiti di voto non sono mai verde/rosso come bene/male, ogni
  esito ha colore, forma, icona ed etichetta; nessun colore di partito
  nell'interfaccia.
- **Movimento calmo**: comunica uno stato, non decora; `prefers-reduced-motion`
  rispettato ovunque.
- **Voce**: tu, frasi corte, verbi attivi, niente trattini lunghi, niente
  "Ottima domanda!".

Cosa migliorare in Stenografo (non toccato da questo branch):

- Le schermate in `docs/screenshots` mostrano ancora il nome "Aula Chiara": il
  README e il sito usano "Stenografo". Vanno rigenerate.
- La landing usa un'etichetta mono maiuscola sopra quasi ogni sezione (COSA
  CHIEDERE, ESEMPIO DI RISPOSTA, IL PERIMETRO, DOMANDE FREQUENTI…). Funziona come
  sistema, ma ripetuta su ogni sezione diventa un ritmo da template: ne basta una
  ogni due o tre sezioni.
- Il riquadro scuro "Per le posizioni dei partiti c'è ParliamentRAG" è l'unica
  sezione a tema invertito della pagina; con un ecosistema stabile può diventare
  un blocco "Rete" uguale nei due siti.

## Audit di ParliamentRAG prima del redesign

- **Due linguaggi in uno**: la home è un editoriale crema con Fraunces e blu
  istituzionale, l'app ha una sidebar blu notte. Nessuno dei due parla con
  Stenografo.
- **Fraunces** come serif display: è il serif di default dei generatori di UI e
  rende la pagina generica. Sostituito con Source Serif 4.
- **Home invisibile senza scroll**: le sezioni partono a `opacity-0` e compaiono
  con un IntersectionObserver. Una cattura a pagina intera, un crawler o un
  lettore senza JavaScript vedono quattro sezioni vuote.
- **Sezioni numerate** (I. Gli strumenti, II. Garanzie, III. L'iter, IV. Dati
  aperti): numerazione decorativa, da togliere.
- **Dark mode disattivato**: il layout forzava `className="light"` mentre 426
  classi `dark:` nei componenti non venivano mai usate.
- **Colori scritti a mano**: circa 1100 classi Tailwind con colori grezzi, quasi
  tutte nelle superfici interne (survey, valutazione, grafici dell'eval).
- **Colori di partito** nel compasso e nei grafici: ParliamentRAG confronta i
  gruppi e ha bisogno di distinguerli, ma i colori dei partiti segnalano
  appartenenza. Decisione aperta, vedi sotto.

## Decisioni

1. **Stessa base, accento diverso.** Neutri, tipografia, forma, movimento ed
   esiti di voto sono identici nei due prodotti. Ogni prodotto ha un accento:
   Stenografo verde, ParliamentRAG blu (la scala costruita sul blu
   `#4d78a8` che è già nella palette di Stenografo). Il verde in ParliamentRAG
   compare solo come esito "Favorevole".
2. **Marchio.** Il simbolo dell'emiciclo resta; il nome passa a Geist semibold
   come "Stenografo", con "RAG" nel colore di prodotto, e viaggia con un
   descrittore di una riga.
3. **Rete.** Ogni prodotto rimanda all'altro dove le domande cambiano natura:
   Stenografo manda a ParliamentRAG le domande di confronto, ParliamentRAG manda
   a Stenografo le domande fattuali (come ha votato X).
4. **Token, non riscrittura.** Le variabili shadcn sono collegate ai ruoli
   semantici, quindi le schermate esistenti cambiano pelle senza riscriverle.
   Il codice nuovo usa le utility semantiche (`bg-surface`, `text-fg-muted`,
   `border-line`, `text-brand-fg`, `label-mono`, `serif-display`).

## Decisioni aperte

- **Colori dei gruppi.** Opzioni: tenere i colori dei partiti nel compasso e nei
  grafici (riconoscibilità immediata), oppure una palette categoriale neutra con
  nome e sigla sempre accanto al segno (coerente con la regola di neutralità di
  Stenografo). In questo branch i colori dei partiti restano.
- **Pacchetto condiviso dei token** (`@civico/tokens` o simile) quando arriva il
  terzo prodotto.
