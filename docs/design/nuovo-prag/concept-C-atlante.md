# Concept C: Atlante

Stato: proposta di design, nessuna implementazione. Data: 2026-10-02.

## 1. Il concept in una frase

ParliamentRAG diventa un atlante del discorso parlamentare: l'Aula è la home e la
mappa, ogni persona, gruppo, tema, seduta, votazione, atto e citazione è un luogo
con un indirizzo permanente, e la domanda in linguaggio naturale è una delle porte
d'ingresso, non l'unica.

**Principio guida: ogni risposta è un luogo, ogni luogo porta altrove.** Niente
che l'utente vede è un vicolo cieco o un risultato effimero. Una risposta RAG
diventa un nodo "Domanda" con URL; una citazione è una pagina da cui si parte per
"chi altro l'ha detto" o "come ha votato dopo". L'IA non è una finestra di chat:
è una nota a margine che sintetizza la pagina in cui ti trovi, usando solo le fonti
che quella pagina già mostra.

## 2. Modello di interazione

**Ingresso.** Quattro porte, tutte sulla stessa home:
- l'emiciclo (clic su un gruppo o su un seggio);
- la palette (Cmd/Ctrl+K su desktop, barra di ricerca fissa in basso su mobile)
  che accetta nomi, temi, numeri di atto, date ("settimana del 12 marzo") e
  domande libere;
- il nastro del tempo sotto l'emiciclo (una settimana, una seduta);
- i temi della settimana (da `/api/config/recent-topics`).

**Pivot.** Ogni nodo espone un riquadro "Da qui" con collegamenti tipizzati e
contati, scritti come verbi: "ha detto (34)", "ha votato (1.212)", "ha firmato
(12)", "siede in (2 commissioni)". Le citazioni aggiungono tre pivot fissi:
"Chi altro l'ha detto", "Come ha votato il gruppo dopo", "Stesso tema in Senato /
nella XVIII". Un pivot non apre un pannello: naviga a un nodo, e il passaggio
finisce nel filo.

**Il filo (sostituisce navbar e breadcrumb gerarchici).** In alto c'è il percorso
reale, non la gerarchia: `Aula › Lega › Molinari › ha detto · 12/03 › votazione
246`. Ogni anello ha l'etichetta del pivot che l'ha generato. Clic su un anello =
torni lì; il filo si può copiare come link ("percorso condiviso"). Sopra le 6 tappe
gli anelli centrali si comprimono in "…".

**Sintesi contestuale.** Su ogni nodo c'è un'azione "Riassumi" o "Confronta" che
produce una nota a margine con marcatori numerati che puntano a citazioni già
presenti nella pagina. Sedute e dibattiti hanno la sintesi precalcolata (i
`SpeakerDebateSummary` esistono già); gruppo×tema è precalcolata per i temi
frequenti; tutto il resto è live, in streaming, e viene messo in cache come nodo.

**Confronto.** Ogni nodo ha "Fissa per confronto". Con due nodi fissati dello
stesso tipo (due gruppi, due persone, Camera XIX e Senato XIX, XVIII e XIX) la
pagina si divide in due colonne allineate per sezione, e la sintesi diventa
"Confronta". Dalla palette: `Lega vs PD su autonomia` apre direttamente il nodo
Confronto.

**Ritorno.** Il filo, il tasto Indietro del browser (ogni pivot è una navigazione
vera), e "Torna all'Aula" (tasto `g a`, o il simbolo dell'emiciclo in alto a
sinistra). Ultimi percorsi salvati in locale, offerti nella palette vuota.

**Ambito (camera e legislatura).** Un selettore unico nel filo, sempre visibile:
`Camera · XIX`. Cambiarlo non resetta la pagina: se sei sul nodo Tema
"autonomia differenziata", passi allo stesso tema nell'altro ambito. Le persone
sono nodi trasversali (il crosswalk delle persone tra legislature è già in
costruzione): la pagina di una persona mostra tutte le sue legislature e camere
come segmenti di una linea.

## 3. Architettura dell'informazione

| Nodo | URL | Contenuto | Pivot principali |
|---|---|---|---|
| Aula | `/camera/19` | emiciclo alla data scelta, temi, nastro del tempo | gruppo, seggio, settimana |
| Gruppo | `/camera/19/gruppo/lega` | composizione nel tempo, portavoce per tema, temi, voti | persone, temi, votazioni |
| Persona | `/persona/riccardo-molinari` | carriera, cariche, commissioni, interventi, voti, atti | citazioni, votazioni, gruppi |
| Tema | `/tema/autonomia-differenziata` (EuroVoc o tema ricorrente) | partitura, righello, portavoce, atti | gruppi, citazioni, ambito |
| Seduta | `/camera/19/seduta/309` | scaletta: dibattiti, interventi, voti in ordine | dibattito, votazione, persona |
| Settimana | `/camera/19/settimana/2025-11` | sedute, temi, voti chiave | seduta, tema |
| Votazione | `/camera/19/votazione/309-12` | esito, seggi, gruppi, dissenso, testo votato | persona, gruppo, atto |
| Atto | `/atto/ac-1665` | testo, firmatari, EuroVoc, dibattiti, voti | firmatari, votazioni |
| Citazione | `/citazione/{chunk_id}` | estratto verbatim, contesto, fonte camera.it | chi altro, voto dopo, ambito |
| Commissione, Governo/carica | `/commissione/…`, `/governo/meloni` | membri e cariche con date | persone |
| Domanda | `/domanda/{id}` | risposta RAG completa e permanente | ogni citazione, tema dedotto |
| Confronto | `/confronto/{a}/{b}?tema=` | due nodi affiancati, sintesi comparativa | entrambi i nodi |

Tre livelli di dettaglio sullo stesso nodo, per cittadini e ricercatori:
1. **Lettura** (default): frase di sintesi, citazioni, rappresentazione principale.
2. **Da qui**: collegamenti tipizzati, confronto, ambito.
3. **Dati del nodo** (chiuso di default): URI RDF, triple, query Cypher che
   genera la pagina, download. Qui vive l'attuale esploratore Cypher.

**Cosa sparisce.** La sidebar e gli otto strumenti come destinazioni separate.
Chat diventa il nodo Domanda. Ricerca negli atti diventa la palette più la sezione
"ha detto" di ogni nodo. Parlamentari e Gruppi diventano nodi. Timeline diventa
nastro del tempo, Settimana e Seduta. Ranking di autorevolezza e bussola diventano
sezioni del nodo Tema e del nodo Gruppo. Esploratore e Dati diventano il livello 3
e una pagina `/dati` raggiungibile dal footer. Valutazione e survey escono
dall'atlante (restano su URL di servizio).

## 4. Schermate chiave

### 4.1 Home: l'Aula (desktop)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◠ ParliamentRAG   Camera · XIX ▾                    [⌘K Cerca o chiedi…] │
├──────────────────────────────────────────────────────────────────────────┤
│                 L'Aula al 2 ottobre 2025 · 400 seggi                      │
│                       . · ● ● ● ● ● ● ● ● · .                             │
│                  · ● ● ● ● ● ● ● ● ● ● ● ● ● ● ·                          │
│               ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ●                       │
│   FdI 116   PD 70   Lega 60   M5S 51   FI 44   AVS 12 … [Vedi come elenco]│
│                                                                          │
│ ├──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──◆──┤  nastro del tempo           │
│  ott 22                                 ott 25   ▂▃▅▂▇▃ sedute/settimana │
│                                                                          │
│ QUESTA SETTIMANA          TEMI IN AULA               PORTE               │
│ 3 sedute · 41 votazioni   autonomia · manovra ·      Chiedi qualcosa     │
│ Seduta 512, 1 ott ›       sanità · Ucraina ›         Scegli un deputato  │
└──────────────────────────────────────────────────────────────────────────┘
```
Note: i gruppi sono disposti per consistenza numerica, mai per collocazione
politica (regola di neutralità di Stenografo). Trascinare il cursore del nastro
ricompone l'emiciclo alla data (le appartenenze hanno date). Il seggio non
corrisponde al posto fisico: è una posizione stabile della persona dentro il
gruppo, e lo dice la legenda.

### 4.2 Nodo Persona (desktop)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Aula › Lega › Riccardo Molinari                  Camera · XIX ▾   [⌘K]   │
├───────────────────────────────────────────────┬──────────────────────────┤
│ Riccardo Molinari                (serif h1)   │ DA QUI                   │
│ Lega · capogruppo dal 2022                    │ ha detto            214  │
│ XVIII ▬▬▬▬▬▬ XIX ▬▬▬▬▬▬▬▬▬ (Camera)           │ ha votato         5.930  │
│ Commissione Affari costituzionali             │ ha firmato           38  │
│                                               │ siede in      2 comm.    │
│ [Riassumi la sua attività su un tema ▾]       │ temi principali     ›    │
│                                               │ [Fissa per confronto]    │
│ HA DETTO, PER TEMA                            ├──────────────────────────┤
│ autonomia   │·  ·· ·   ·    ·│ 2023-25        │ DATI DEL NODO  ▸         │
│ manovra     │  ·   ·· · ··  ·│                │                          │
│ «Il regionalismo differenziato è…» 12/03/24 ↗ │                          │
│ VOTI IN DISSENSO DAL GRUPPO   2 su 5.930 ›    │                          │
└───────────────────────────────────────────────┴──────────────────────────┘
```

### 4.3 Nodo Tema con sintesi (desktop)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Aula › Domanda › autonomia differenziata         Camera · XIX ▾   [⌘K]   │
├──────────────────────────────────────────────────────────────────────────┤
│ Autonomia differenziata          [Riassumi] [Confronta due gruppi]       │
│ ┌ NOTA A MARGINE ─────────────────────────────────────────────────────┐ │
│ │ La maggioranza la presenta come attuazione del Titolo V [1][3];      │ │
│ │ PD, M5S e AVS contestano i LEP [2][4]. Generata da 14 citazioni      │ │
│ │ di questa pagina, 7 di maggioranza e 7 di opposizione. ⌄ come        │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ PARTITURA            2023          2024             2025                 │
│ FdI   (Bignami)   ─────●──────●─────■ vot.246 ●──────                    │
│ PD    (Braga)     ──●────────●●─────● vot.246 ────●──                    │
│ Lega  (Molinari)  ───────●───●──────■ ─────────────                     │
│ …                                                                        │
│ Misto-+Europa     ─────────────────── nessun intervento trovato          │
│ RIGHELLO   centralizzazione ◂──[PD══]──[M5S═]────[FI═══]─[Lega═]──▸ aut. │
│ Stesso tema: Senato XIX (212 interventi) · XVIII (88) ›                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Nodo Citazione con pivot (desktop)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Aula › autonomia › Braga · 12/03/24                                      │
├──────────────────────────────────────────────────────────────────────────┤
│ CITAZIONE · Seduta 262 · 12 marzo 2024 · Chiara Braga (PD)               │
│   … il testo precedente, in grigio …                                     │
│ «Con questa riforma i livelli essenziali delle prestazioni diventano     │
│  una promessa senza copertura.»                     (serif, verbatim)    │
│   … il testo successivo …                    Verificata ✓  camera.it ↗   │
│                                                                          │
│ CHI ALTRO L'HA DETTO              COME HA VOTATO IL PD DOPO              │
│ Conte (M5S) 03/04/24  simile ›    vot. 246 · 18/06/24  ■ Contrario 68/70 │
│ Grimaldi (AVS) 15/05/24 ›         2 assenti ›                            │
│ Boccia (PD, Senato) 2023 ›                                               │
│ STESSO TEMA ALTROVE   Senato XIX ›   XVIII legislatura ›                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.5 Mobile: home e palette

```
┌───────────────────────┐   ┌───────────────────────┐
│ ◠ PRAG   Camera·XIX ▾ │   │ ⌄ chiudi              │
│                       │   │ [autonomia          ] │
│     · ● ● ● ● ·       │   │ TEMI                  │
│   ● ● ● ● ● ● ● ●     │   │  Autonomia diff.  ›   │
│ FdI 116 · PD 70 ›     │   │ ATTI                  │
│ Lega 60 · M5S 51 ›    │   │  AC 1665 Calderoli ›  │
│ [Vedi tutti i gruppi] │   │ PERSONE               │
│ ◂ settimana 40 ▸      │   │  … nessuna            │
│ 3 sedute · 41 voti ›  │   │ CHIEDI                │
│ Temi: autonomia ›     │   │  «Cosa pensano i      │
│                       │   │   gruppi di autonomia │
├───────────────────────┤   │   differenziata?» ↵   │
│ [⌕ Cerca o chiedi   ] │   │ FATTO? → Stenografo   │
└───────────────────────┘   └───────────────────────┘
```
Note: la barra in basso è l'unica navigazione. L'emiciclo su mobile è compatto e
non interattivo per seggio (troppo piccolo per il tocco): si tocca il gruppo, e la
lista dei gruppi è sempre lì sotto.

### 4.6 Mobile: nodo Votazione con filo compresso

```
┌───────────────────────┐
│ ‹ Lega   ⋯ percorso   │
│ Votazione 246         │
│ 18 giu 2024 · finale  │
│ [Approvato]           │
│ ● 172  ■ 99  ◆ 1      │
│   · ● ● ■ ■ ·         │ ← stessi seggi della home
│ PER GRUPPO            │
│ Lega  ●●●●●●●●● 58/60 │
│ PD    ■■■■■■■■■ 68/70 │
│ IN DISSENSO  2 ›      │
│ TESTO VOTATO ›        │
│ CHI NE HA PARLATO  ›  │
├───────────────────────┤
│ [⌕ Cerca o chiedi   ] │
└───────────────────────┘
```

## 5. Rappresentazione dei risultati

Regola comune: una rappresentazione vive dentro un nodo e ogni segno è un link a
un altro nodo. Nessuna figura è un'immagine finale.

**Posizioni dei gruppi, citazioni e bilanciamento: la partitura.** Oggi sono tre
cose (testo per partito, card di citazione, barre maggioranza/opposizione). Nella
partitura ogni gruppo è una riga, il tempo scorre in orizzontale, ogni
dichiarazione è un punto e ogni voto finale è la forma del suo esito. Risponde
alla domanda vera ("cosa dicono, da quando, e votano coerentemente?") e rende il
bilanciamento visibile come completezza: tutte le righe ci sono, e una riga vuota
dice "nessun intervento trovato" invece di sparire. Il bilanciamento numerico resta
come ricevuta testuale ("7 di maggioranza, 7 di opposizione").

```
PD    (Braga)  ──●──────●●────■ 246 ──●──    ● dichiarazione  ■ Contrario
FdI (Bignami)  ─────●──────●──● 246 ─────    ● Favorevole (stessa forma esiti)
+Europa        ─────────────────────────     nessun intervento trovato
```

**Citazioni: l'estratto nel verbale.** Non card: il verbatim in serif, con una riga
di contesto prima e dopo in grigio, così si vede che non è tagliato ad arte. La
fonte camera.it e lo stato di verifica (`/api/evidence/{id}/verify`) stanno sulla
stessa riga. In elenco una citazione è una riga, non un blocco.

**Bussola: il righello.** Gli assi sono derivati per tema e il punteggio di stance
è calcolato per frammento: uno scatter 2D suggerisce una geometria che i dati non
hanno. Il righello mostra un asse alla volta, con i poli scritti, e ogni gruppo
come intervallo (dal frammento più vicino a un polo a quello più vicino all'altro),
non come punto. Clic su un estremo dell'intervallo apre la citazione che lo
determina. Il secondo asse è un righello separato, non una dimensione.

```
centralizzazione ◂────[PD═══]──[M5S══]────────[FI════]─[Lega══]────▸ autonomia
                       └ «…i LEP restano una promessa» (clic: citazione)
```

**Autorevolezza: il banco dei portavoce.** Un punteggio composito non dice nulla
al cittadino. Per ogni gruppo il nodo Tema mostra i 1-3 portavoce con la ragione
in parole verificabili; i loro seggi si accendono nell'emiciclo. Le componenti e i
pesi sono al livello 3.

```
PD  Chiara Braga   commissione Ambiente dal 2022 · 11 interventi sul tema ·
                   prima firmataria di 1 atto collegato            come ›
```

**Votazioni: l'emiciclo che si ricolora.** L'emiciclo resta, ma è lo stesso oggetto
della home: i seggi non si spostano, cambiano forma e colore secondo l'esito. Chi
ha imparato dove siede un deputato lo ritrova. Sotto, per ogni gruppo, una riga di
forme e il dissenso come elenco di nomi, che è l'informazione più cercata.

**Tempo: nastro e scaletta.** La lista di sedute diventa un nastro a settimane con
la densità di attività, trascinabile. La seduta è una scaletta: dibattiti,
interventi e voti nell'ordine in cui sono accaduti, perché la domanda è "cosa è
successo quel giorno".

```
seduta 309 · 18 giu 2024
 09:30 Dibattito AC 1665 ── Braga ● Bignami ● Molinari ● (+12)
 12:10 Votazione 246  finale  [Approvato]  ● 172 ■ 99 ◆ 1
```

**Collegamenti: elenco tipizzato, non grafo a forze.** "Da qui" è una lista di verbi
con conteggi. Il grafo a forze appare solo al livello 3, limitato a un salto.

**Carriera di una persona: la linea dei segmenti.** Legislature, camere, gruppi e
cariche come segmenti su un'unica linea temporale, così i cambi di gruppo sono
visibili a colpo d'occhio.

## 6. Accessibilità e mobile

Ogni mappa ha un equivalente non visivo completo, presente nel DOM:
- emiciclo: navigazione da tastiera a due livelli (frecce tra gruppi, Invio per
  entrare, frecce tra persone), annunci del tipo "Lega, 60 seggi, 3 di 9"; "Vedi
  come elenco" mostra la stessa cosa come tabella;
- partitura: tabella gruppo × data con le citazioni come link;
- righello: elenco ordinato con gli intervalli in numeri e i poli scritti;
- esiti: sempre forma, colore, icona ed etichetta.

Palette con ruolo `combobox` e risultati raggruppati per tipo; il filo è un `nav`
con `aria-current`. Su mobile il filo diventa "‹ nodo precedente" più un foglio
"percorso"; il confronto passa da colonne a schede alternate.

## 7. Dove finisce ogni capacità esistente

| Capacità (endpoint) | Nell'atlante |
|---|---|
| Pipeline RAG `/api/query`, `/api/chat`, task | nodo Domanda; sintesi "Confronta" |
| Storico `/api/history` | nodi Domanda permanenti, ultimi percorsi |
| Evidence `/api/evidence/{id}`, `/verify` | nodo Citazione, spunta di verifica |
| Ricerca `/api/search/results` | palette, sezione "ha detto" di ogni nodo |
| `/api/search/deputies`, `/groups` | palette, nodi Persona e Gruppo |
| `/api/search/speech/{id}`, `/act/{uri}` | nodi Citazione e Atto |
| Bussola `/api/compass` | righello nel nodo Tema e Gruppo |
| Autorevolezza `/api/authority-ranking` | banco dei portavoce, seggi accesi |
| Timeline `/api/timeline` | nastro del tempo, nodi Settimana |
| `/timeline/debates/{id}` | scaletta del nodo Seduta |
| `/timeline/sessions/{id}/votes`, `/votes/{id}`, `/act-text` | nodo Votazione, testo votato |
| `/timeline/speakers/…` (sintesi precalcolate) | nota a margine della seduta |
| `/api/config/recent-topics`, `/parties`, `/coalitions` | temi della home, maggioranza/opposizione |
| `/api/graph/schema`, `/stats`, `/query` | livello 3 "Dati del nodo" |
| `/api/data/rdf`, `/graph-sample`, `/stats` | pagina `/dati`, download per nodo |
| Ambito camera/legislatura (`scope.py`) | selettore nel filo, pivot "stesso tema altrove" |
| Server MCP | stessi URL di nodo nelle risposte degli assistenti |
| Feedback, newsletter | sotto la nota a margine; footer |

## 8. Ecosistema con Stenografo

Stenografo risponde a un fatto in una frase; l'atlante è dove quel fatto abita.
Proposta: i nodi dell'atlante diventano le pagine permanenti dell'ecosistema.
Ogni fonte di Stenografo (votazione, seduta, deputato) porta "Apri nell'atlante",
e la palette dell'atlante riconosce le domande fattuali ("come ha votato X su Y")
e mostra in linea la risposta di Stenografo con la sua fonte, oppure ci manda.
Stesso design system: emiciclo, forme di esito, citazione in Source Serif, pillole
per le azioni, accento blu per ParliamentRAG. I due prodotti condividono
componenti civic (Hemicycle, OutcomeShape, VoteCard) e lo schema degli URL.

## 9. Rischi, costi, MVP

**Rischi.**
- Chi vuole solo una risposta si perde in una mappa. Mitigazione: la palette è il
  primo elemento a fuoco e accetta domande; la home mostra "Chiedi qualcosa".
- Disposizione dei gruppi nell'emiciclo: ordine per consistenza, non politico;
  va spiegato, e qualcuno lo leggerà comunque come schieramento.
- Il seggio non è il posto reale: rischio di fraintendimento se non dichiarato.
- "Chi altro l'ha detto" su similarità vettoriale può accostare frasi opposte nel
  senso: mostrare la similarità come "parla dello stesso punto", non "concorda".
- Costo LLM delle sintesi su ogni nodo: cache aggressiva e limiti per IP.
- Il Senato e la XVIII avranno copertura diversa (es. sintesi o stance mancanti):
  ogni nodo deve dire cosa manca nel suo ambito.
- Oggi le pagine Persona interrogano il grafo con Cypher dal frontend: per pagine
  permanenti e indicizzabili serve un'API di nodo.

**Costi tecnici.**
- Nuovi endpoint: `GET /api/node/{tipo}/{id}` (contenuto di livello 1),
  `GET /api/node/{tipo}/{id}/links` (pivot contati), `GET /api/palette?q=`
  (typeahead multi-tipo), `GET /api/aula?chamber&leg&date` (composizione alla
  data), `GET /api/citation/{id}/similar` (vicini vettoriali di altri oratori),
  `GET /api/topic/{id}/score` (partitura), `POST /api/synthesis` (sintesi
  contestuale con tipo e nodi, in cache).
- Indici: full-text Neo4j su nomi di persone, gruppi, atti e concetti EuroVoc;
  indici su date delle appartenenze e delle sedute; slug stabili per ogni nodo.
- Precalcoli a ogni `make update-data`: composizione dell'Aula per settimana,
  partitura e righello per i temi ricorrenti (circa 50), banco dei portavoce per
  gruppo×tema, conteggi dei pivot, sintesi di seduta (già esistenti).
- Live: solo Domanda, Confronto non precalcolato e righello di temi nuovi, con
  stato della pipeline mostrato a passi reali.

**MVP in 3 settimane (solo Camera XIX).**
1. Settimana 1: API di nodo e palette; nodi Persona, Gruppo, Seduta, Votazione,
   Citazione con URL permanenti, riusando le pagine e i servizi attuali; il filo.
   Via la sidebar.
2. Settimana 2: home con emiciclo alla data e versione elenco; nodo Tema per i
   temi recenti con partitura e banco dei portavoce (righello da bussola in
   cache); nodo Domanda che avvolge la pipeline attuale.
3. Settimana 3: nota a margine della seduta (sintesi esistenti), pivot "chi altro
   l'ha detto" e "come ha votato dopo", mobile con barra in basso, verifica di
   accessibilità.

Fuori dall'MVP: emicicli di Senato e XVIII (il selettore c'è ma rimanda a ricerca
con ambito), confronto tra ambiti, scrubbing animato, livello 3 per ogni nodo.
