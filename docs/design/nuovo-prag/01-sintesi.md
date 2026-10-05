# Il nuovo ParliamentRAG: sintesi e direzione

Fonti: `00-audit-ux.md`, `concept-A-domanda.md`, `concept-B-dossier.md`,
`concept-C-atlante.md`, `D-rappresentazione.md` (2 ottobre 2026).

## Cosa dicono i numeri

- La risposta arriva in 67 secondi di mediana. Esperti, citazioni e bussola sono
  pronti a 30, ma restano dietro uno stepper a pagina intera.
- Il testo non è in streaming: si genera tutto, poi si spedisce a pezzi.
- La risposta mediana è lunga 1.338 parole e non ha una sintesi in testa.
- Quattro pagine aprono con lo stesso campo "tema". L'utente sceglie lo strumento
  prima di sapere cosa gli serve, e ranking e bussola rifanno da soli (66 e 47
  secondi) un passo che la risposta contiene già.
- Da una citazione non si arriva al deputato, al gruppo, alla seduta o al voto.
  Schede deputato e gruppo non mostrano voti.
- I colori di partito falliscono ogni controllo di leggibilità e di distinzione.

## Su cosa convergono i tre concept

Tre direzioni diverse, cinque conclusioni uguali:

1. Niente sidebar, niente strumenti come destinazioni.
2. Ogni entità (persona, gruppo, tema, seduta, voto, citazione) ha un indirizzo
   permanente.
3. La risposta si compone per gradi con dati veri, non con uno spinner.
4. Bussola su un asse alla volta, autorevolezza spiegata, bilanciamento come
   elenco di chi c'è e chi manca.
5. Accanto a quello che un gruppo ha detto, quello che ha votato.

Si separano sul punto d'ingresso: la domanda (A), il tema (B), l'Aula (C).

## Direzione raccomandata: il tema come unità, la domanda come porta

Prendo l'ossatura di B, l'ingresso di A e la rete di C.

**Il tema è l'unità del prodotto.** Una pagina stabile per tema, datata,
citabile, aggiornata dopo ogni rinnovo dei dati: in breve, posizioni dei gruppi,
voci, detto e votato, ritmo nel tempo, bussola. I temi più chiesti sono
precalcolati, quindi si aprono in un secondo invece che in un minuto. È anche
la risposta all'audit: l'80% del traffico entra dalle chip e dai temi della
settimana.

**La domanda resta la porta principale.** Un solo campo in alto (e `⌘K`
ovunque) accetta un tema, una frase letta da qualche parte, un nome, un numero
di atto. Il sistema dichiara come ha capito e lo fa correggere: se c'è un tema
pronto lo apre; se no compone la pagina dal vivo, riempiendola man mano che la
pipeline produce copertura, voci, citazioni, posizioni, testo. Il risultato
diventa a sua volta una pagina con indirizzo. Le domande fattuali (come ha
votato X) passano a Stenografo con la domanda già scritta.

**Le entità sono una rete.** Ogni nome, sigla, seduta e voto è un link. Si apre
in un pannello laterale sopra il tema (foglio dal basso su mobile) senza perdere
il punto di lettura; il pannello ha il suo indirizzo e i suoi passaggi ("come ha
votato dopo", "stesso tema nella XVIII o al Senato"). L'emiciclo resta come
vista dell'Aula e del singolo voto, non come home.

**Cosa sparisce.** Sidebar e barra in basso; le pagine Ranking, Bussola e Cerca
come strumenti separati (diventano sezioni del tema e risultati del campo);
Explorer Cypher esce dalla navigazione e va nell'area dati per sviluppatori.

**Cosa resta come pagina.** Home (campo + indice dei temi + settimana in Aula),
tema, persona, gruppo, seduta, voto, citazione, dati, metodo.

## Linguaggio dei risultati

Si adotta `D-rappresentazione.md` per intero:

- **Quadro dei gruppi**: una riga per gruppo con frase di sintesi, citazione più
  forte e base; i gruppi senza interventi restano con la loro riga vuota.
- **Striscia di copertura** al posto del "78%": chi è citato, chi trovato e non
  citato, chi assente.
- **Bussola** come dot plot per asse con incertezza; il piano 2D solo se gli assi
  non dicono la stessa cosa.
- **Autorevolezza** come matrice deputato per criterio, con il perché leggibile.
- **Voti** come griglia per gruppo che fa vedere i dissidenti; matrice voti per
  gruppo sul tema; "detto, votato, lettura" senza punteggio aggregato.
- **Traccia del tema** nel tempo con attenzione, momenti di voto e bande di
  governo; legislature in pannelli affiancati.
- **Citazione** come oggetto unico ovunque, con stato di verifica dall'endpoint
  `/evidence/{id}/verify`, oggi mai chiamato.
- **Attesa** come passi reali con i risultati parziali in vista.

**Colori di partito: via ovunque.** L'identità di un gruppo è la sigla scritta e
la riga che occupa; il colore porta solo esiti di voto, elemento a fuoco e
intensità. Chiude anche la decisione aperta in `../ecosistema.md`.

## Cosa serve dal backend

1. Streaming vero del testo (oggi simulato) e consegna immediata degli eventi
   intermedi già calcolati.
2. Modello `Tema` e `Snapshot`: job che esegue la pipeline sui temi scelti e
   salva l'output; `GET /api/topics`, `GET /api/topics/{slug}`, `match?q=`.
3. API dei nodi (persona, gruppo, seduta, voto, citazione) lato server: oggi
   alcune schede interrogano il grafo dal frontend.
4. Voti per tema e per gruppo (`ON_ACT` verso gli atti del tema) per "detto e
   votato".
5. Cronologia per dispositivo invece che globale.
6. Maggioranza e opposizione calcolate per governo alla data (serve alla XVIII).

## Piano

1. **Prototipo navigabile** su questo branch, con dati veri ma senza nuovo
   backend: shell senza sidebar con campo e `⌘K`; pagina tema costruita da una
   risposta salvata nello storico, con quadro dei gruppi, striscia di copertura,
   bussola a dot plot, matrice di autorevolezza, citazione atomica con verifica;
   pannello persona. Serve a decidere sull'esperienza vera, non sui wireframe.
2. **Backend minimo**: streaming reale, eventi intermedi, temi precalcolati per
   20 temi scelti a mano, API dei nodi.
3. **Rete e voti**: detto e votato, griglia dei voti, pagine nodo complete,
   traccia del tema, scope Camera/Senato e legislature dal branch dei dati.
4. **Valutazione**: rieseguire l'eval prima di sostituire l'interfaccia in
   produzione; i numeri del paper restano legati alla pipeline, non alla UI.
