# Concept A: la domanda è l'interfaccia

Stato: proposta di design, nessun codice. Data: 2026-10-02.
Base: router in `backend/app/routers/`, eventi SSE di `chat.py`, `services/retrieval/scope.py` (nel branch `feat/multi-legislatura-senato`), design system di Stenografo e `docs/design/ecosistema.md`.

## 1. Il concept in una frase

ParliamentRAG diventa un solo campo: scrivi un tema, una frase che hai letto, un nome o un numero di atto, e ottieni un dossier che si compone sotto i tuoi occhi con le posizioni dei gruppi, le voci, i voti che sono seguiti e il ritmo del dibattito.

**Principio guida.** Gli strumenti non sono più luoghi in cui andare, sono blocchi che il sistema sceglie e che l'utente può aprire, filtrare, fissare. Ogni blocco porta con sé la sua prova: una citazione verbatim o un voto, a un tocco da camera.it o senato.it.

## 2. Modello di interazione

### Stati

| Stato | Cosa succede | Tempo |
|---|---|---|
| S0 Vuoto | Campo al centro, tre esempi per tipo di input, scope visibile (`Camera · XIX`), dossier recenti dal dispositivo | 0 |
| S1 Interpretazione | Il router classifica l'input e mostra la riga "Ho letto: tema *autonomia differenziata* · Camera XIX". La riga è modificabile | < 0,5 s |
| S2 Scheletro | Compaiono gli slot dei blocchi previsti, già riempiti con ciò che il grafo dà senza LLM: commissioni competenti, atti e votazioni sul tema, ritmo per date | < 3 s |
| S3 Voci | Arrivano gli eventi `experts` e `citations`: per ogni gruppo le voci scelte e le citazioni grezze. È già una risposta utile | 5-12 s |
| S4 Mappa | Evento `compass`: la mappa delle posizioni si posa sulle voci | + pochi s |
| S5 Sintesi | La sintesi scrive in testa al dossier (`chunk`), le citazioni nel testo si agganciano alle voci già visibili | fino a ~30 s |
| S6 Verificata | `citation_details`: ogni citazione riceve la spunta di verifica offset; la ricevuta di copertura si chiude | fine |
| S7 Raffinamento | Follow-up nel campo agganciato in basso, oppure chip: "solo opposizione", "e nel 2019?", "+ Senato" | |
| S8 Entità in place | Un nome, un gruppo, un atto o un voto si aprono in un pannello laterale (desktop) o in un foglio dal basso (mobile), senza lasciare il dossier | |
| S9 Ritorno | Palette comandi (`⌘K` o `/`) con dossier fissati, cronologia locale, entità e azioni | |

La lista di otto passi della pipeline sparisce: la sostituiscono gli slot stessi, ciascuno con la sua etichetta mono ("VOCI · in arrivo"). Sotto la domanda resta una ricevuta piegata, come in Stenografo: "Verificata · 412 interventi letti · 11 gruppi · 38 citazioni ⌄", che apre la traccia completa (evento `trace`).

### Transizioni chiave

- **Dalla domanda al dossier.** Il campo si sposta in alto e diventa titolo serif del dossier (View Transition `composer`, come Stenografo). Il campo di inserimento resta agganciato in basso.
- **Follow-up.** Non è una bolla di chat. Ogni domanda successiva aggiunge una sezione al dossier con la sua intestazione e una riga "rispetto a sopra" (cosa cambia di scope o di filtro). Le sezioni precedenti si piegano a una riga.
- **Filtri senza rilancio.** "Solo opposizione", "solo FdI", "dal 2024" filtrano lato client voci, citazioni e mappa già ricevute. Il rilancio della pipeline serve solo se cambia il tema o lo scope; in quel caso il chip lo dice: "Serve una nuova ricerca, circa 30 secondi".
- **Scope dal linguaggio.** "E nel 2019?" diventa un cambio di scope (XVIII) proposto come chip da confermare, mai applicato in silenzio.
- **Entità.** Click su un nome apre il pannello; dal pannello "Apri scheda" porta al permalink. Esc chiude e riporta il fuoco dove era.

### Instradamento dell'intento

| Input | Riconoscimento | Esito |
|---|---|---|
| Tema o domanda di posizione | default | Dossier completo |
| Domanda fattuale puntuale ("come ha votato Conte sul MES") | classificatore leggero dopo le regole | Blocco di passaggio a Stenografo con la domanda precompilata; se il tema è anche posizionale, il dossier parte lo stesso |
| Nome di deputato o gruppo | match esatto su `/api/search/deputies` e `/groups` | Pannello entità più "Di cosa parla" (temi frequenti) |
| Numero di atto, "AC 1660", "C. 1660" | regex | Atto: testo, firmatari, voti, dibattito |
| Citazione incollata (> 120 caratteri o tra virgolette) | regola | Ricerca semantica dello spezzone, verifica offset, chi l'ha detta, quando, e poi la traiettoria (vedi `statement-trajectory.md`) |
| Fuori dominio | `check_domain` esistente | Avviso e tre riformulazioni |
| Ambiguo | | Opzioni da scegliere, come `ClarifyOptions` di Stenografo |

Le regole deterministiche vengono prima dell'LLM: costano zero e coprono nomi e numeri. L'interpretazione è sempre visibile e correggibile in S1.

## 3. Architettura dell'informazione

**Spariscono come destinazioni**: sidebar, barra mobile in basso, `/home` come pagina separata, `/chat`, `/search`, `/ranking`, `/compass`, `/timeline`. Restano raggiungibili come blocchi o come comandi della palette ("cerca negli atti: …", "classifica autorevolezza su …").

**Si fondono**: chat, bussola, ranking e statistiche del tema diventano un solo dossier. Ricerca negli atti diventa il blocco "Negli atti" e il comando di palette. Timeline e sedute diventano il blocco "Ritmo" più il pannello seduta.

**Restano pagine con permalink** (SEO, condivisione, citabilità):
- `/d/{id}` dossier condiviso (oggi `/chat/[id]`);
- `/deputato/{id}`, `/gruppo/{slug}`, `/atto/{id}`, `/voto/{id}`, `/seduta/{id}`;
- `/dati` (RDF, schema, esploratore Cypher per ricercatori), `/metodo`, `/privacy`.

Ogni pagina entità ha in testa lo stesso campo, già scritto: "Chiedi su Elly Schlein…".

## 4. Schermate chiave

### 4.1 Desktop, vuoto (S0)

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ◖ ParliamentRAG                                   ⌘K  Dossier   ◐        │
│                                                                          │
│            Cosa pensano i gruppi parlamentari di…                        │  serif display
│   ┌────────────────────────────────────────────────────────────────┐     │
│   │ un tema, una frase letta sui giornali, un deputato, un atto    │ ↵   │  pillola
│   └────────────────────────────────────────────────────────────────┘     │
│   [Camera · XIX ▾]  [+ XVIII]  [+ Senato]                                │  chip di scope
│                                                                          │
│   PROVA CON                                                              │  label mono
│   salario minimo   ·   "il premierato rafforza la stabilità…"  ·  AC 1660│
│                                                                          │
│   I TUOI DOSSIER                        IN AULA QUESTA SETTIMANA         │
│   ▪ Autonomia differenziata  2 g fa     ▪ Seduta 512, 1 ott              │
│   ▪ Fine vita (fissato)                 ▪ Voto finale ddl …              │
└──────────────────────────────────────────────────────────────────────────┘
```
Note: i dossier vengono dal dispositivo, non dal server. "In aula" usa `/api/timeline` e `/api/config/recent-topics`.

### 4.2 Desktop, dossier in composizione (S2-S3, t ≈ 6 s)

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ◖ ParliamentRAG   Autonomia differenziata                     ⌘K   ◐     │
├──────────────────────────────────────────────────────────────────────────┤
│ Ho letto: tema autonomia differenziata · Camera XIX  [modifica]          │
│ ◌ In corso · 412 interventi letti · voci pronte · sintesi in scrittura   │
│                                                                          │
│ SINTESI ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ (in scrittura)               │
│                                                                          │
│ CHI NE PARLA  Commissione I Affari costituzionali · 63 sedute, 2023-2025 │
│ ▁▂▂▅█▃▁▁▂▇█▂▁  ▲ voto finale 19 giu 2024                                 │  ritmo, già pronto
│                                                                          │
│ VOCI                                                    [solo opposiz.]  │
│ FdI    Rossi A. · relatore      "Il testo garantisce i LEP prima…"  ✓    │
│ PD     Bianchi C.               "Si spacca il Paese in venti…"      ✓    │
│ M5S    ░░░░░░░░░░░                                                       │
│ …                                                                        │
│ NEGLI ATTI  AC 1665 · 14 votazioni collegate                             │
├──────────────────────────────────────────────────────────────────────────┤
│ ( Chiedi ancora: "e il Senato?", "solo Lega"… )                     ↵    │  campo agganciato
└──────────────────────────────────────────────────────────────────────────┘
```
Le voci arrivano prima della sintesi: oggi l'evento `citations` precede `chunk`, il redesign lo rende visibile invece di nasconderlo dietro una barra di avanzamento.

### 4.3 Desktop, dossier completo con entità aperta (S6 + S8)

```text
┌───────────────────────────────────────────────┬──────────────────────────┐
│ SINTESI                                        │ DEPUTATO           ✕     │
│ La maggioranza difende il ddl come attuazione  │ Carla Bianchi · PD       │
│ del titolo V [1]; le opposizioni lo legano     │ XIX · dal 2022           │
│ alla tenuta dei LEP [2][3]…                    │                          │
│                                                │ SUL TEMA                 │
│ POSIZIONI                                      │ 7 interventi · 2 atti    │
│ (mappa a strisce, vedi §5.2)                   │ "Si spacca il Paese…" ✓  │
│                                                │                          │
│ PAROLE E VOTI                                  │ COME HA VOTATO           │
│ (matrice gruppi × voti, vedi §5.4)             │ ■ Contrario 19 giu 2024  │
│                                                │                          │
│ [Fissa] [Confronta due gruppi] [Copia fonti]   │ [Apri scheda] [Chiedi su │
│ Può sbagliare: prima di citarla, apri la fonte.│  di lei]                 │
└───────────────────────────────────────────────┴──────────────────────────┘
```
Il pannello è un `aside` non modale (420 px), come il pannello fonti di Stenografo: il testo resta leggibile e gli altri link restano cliccabili.

### 4.4 Desktop, palette di ritorno (S9)

```text
            ┌────────────────────────────────────────────────┐
            │ ⌕ fine vi                                       │
            ├────────────────────────────────────────────────┤
            │ DOSSIER     ★ Fine vita · fissato · 3 sezioni   │
            │ CRONOLOGIA    Fine vita e XVIII · 12 set        │
            │ ENTITÀ        Atto C. 104 "Disposizioni fine vita"│
            │ AZIONI        Cerca "fine vi" negli atti         │
            │               Classifica autorevolezza sul tema │
            │               Scarica i dati (RDF)               │
            └────────────────────────────────────────────────┘
```

### 4.5 Mobile, dossier progressivo (390 px)

```text
┌──────────────────────────────┐
│ ◖  Salario minimo        ⋯   │
│ Camera · XIX ▾  ◌ in corso   │
│──────────────────────────────│
│ SINTESI ░░░░░░░░░░░░░░░░░░░  │
│                              │
│ VOCI      [Tutti ▾]          │
│ FdI  Rossi A.                │
│ "La contrattazione resta…" ✓ │
│ PD   Bianchi C.              │
│ "Nove euro non sono…"     ✓  │
│ ‹ scorri i gruppi ›          │
│                              │
│ RITMO ▁▂█▃▁▅▂                │
│──────────────────────────────│
│ ( Chiedi ancora…        ) ↵  │  composer agganciato
│ [solo opposizione][e nel 2019]│  chip sopra la tastiera
└──────────────────────────────┘
```

### 4.6 Mobile, verifica e passaggio a Stenografo

```text
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ ▔▔▔  foglio dal basso        │   │ Ho letto: domanda fattuale   │
│ FONTE 03 · 3 di 38   ‹ ›     │   │                              │
│ Camera · Seduta 309          │   │ Per "come ha votato Conte    │
│ 18 giugno 2024               │   │ sul MES" ti serve Stenografo:│
│ …contesto prima…             │   │ una frase e la fonte.        │
│ ┃"Si spacca il Paese in      │   │ [Apri in Stenografo ↗]       │
│ ┃ venti sistemi sanitari"    │   │                              │
│ …contesto dopo…              │   │ Vuoi invece le posizioni dei │
│ ✓ Testo identico al resoconto│   │ gruppi sul MES?              │
│ [Apri su camera.it ↗]        │   │ [Sì, componi il dossier]     │
└──────────────────────────────┘   └──────────────────────────────┘
```

## 5. Rappresentazione dei risultati

Ogni forma deve rispondere alla domanda del dossier ("chi pensa cosa, e lo ha fatto?"), non mostrare l'output del modulo che l'ha calcolata. Le forme vivono negli slot del dossier, accettano i filtri del campo e portano sempre alla prova.

### 5.1 Citazioni: la sintesi è fatta di citazioni

Oggi: card separate sotto il testo. Nel concept la citazione sta dentro la riga del suo gruppo, in serif, con filetto a sinistra e attribuzione mono. Toccarla espande il contesto del resoconto (prima e dopo, da `/api/search/speech/{chunk_id}`) con lo spezzone evidenziato e lo stato di `/api/evidence/{id}/verify`. Perché: la verifica è la cosa che distingue il prodotto, e qui costa un tocco senza perdere il punto.

```text
PD  ┃ "Si spacca il Paese in venti sistemi sanitari"
    ┃ C. Bianchi · Seduta 309 · 18 giu 2024 · ✓ verificata   [contesto ⌄]
```

### 5.2 Bussola: strisce di posizione invece dello scatter 2D

Uno scatter su due assi astratti invita a leggere distanze precise che il modello non garantisce. Ogni asse diventa una striscia orizzontale con i poli scritti con le parole del tema. Ogni gruppo è un segno con sigla accanto e una fascia che mostra la dispersione dei suoi interventi. Toccare un segno mostra le due citazioni che lo tirano di più verso ciascun polo. Il colore non distingue i gruppi: la sigla sì (regola di neutralità).

```text
LEP prima del trasferimento ◂────────────────────▸ trasferimento subito
                 AVS  M5S  PD      Az   FI  NM   Lega FdI
                 ├─●─┤├●┤ ├─●─┤   ├●─┤ ├●┤      ├●┤ ├─●┤
Ruolo dello Stato ◂──────────────────────────────▸ ruolo delle Regioni
                 …
```

### 5.3 Autorevolezza: un perché, non un punteggio

La classifica con barre risponde a una domanda che l'utente non fa. Al suo posto, accanto a ogni voce, una ragione in parole costruita dalle componenti del modello: "relatrice del ddl · 14 interventi in Commissione XII · firmataria di 3 atti". Il punteggio resta dietro "Perché questa voce ⌄". La classifica completa esiste come comando di palette.

```text
FdI  Rossi A.  relatore del ddl · 11 interventi in I Commissione   [perché ⌄]
```

### 5.4 Voti: matrice parole e voti invece dell'emiciclo per ogni voto

La domanda implicita è "hanno votato come hanno parlato?". Righe: gruppi. Colonne: le votazioni collegate al tema in ordine di data. Celle: forma ed etichetta di esito prevalente del gruppo (cerchio favorevole, quadrato contrario, rombo astenuto, anello non ha votato), con un segno quando il gruppo si è diviso. Una colonna iniziale riprende la posizione dalle strisce. L'emiciclo resta nel pannello del singolo voto, dove serve.

```text
                posizione   12 mar  4 giu  19 giu(fin.)
FdI             ▸ subito      ●      ●       ●
PD              ◂ LEP         ■      ■       ■
Az              ·  centro     ◆      ■½      ■      ½ = gruppo diviso
```

### 5.5 Bilanciamento: ricevuta di copertura e assenze dichiarate

Le barre maggioranza/opposizione mostrano un equilibrio che il sistema impone per costruzione, quindi dicono poco. Al loro posto una riga: "11 gruppi su 12 hanno almeno una voce · maggioranza 17 citazioni, opposizione 21". L'assenza diventa contenuto: "Noi Moderati: nessun intervento sul tema nello scope". In scope XVIII la maggioranza cambia con i governi Conte I, Conte II e Draghi: la ricevuta lo dice e le righe portano il governo in carica alla data della citazione.

### 5.6 Timeline: ritmo del tema invece della lista di sedute

Una striscia di densità degli interventi nel tempo (da `topic_stats.interventions_detail`), con triangoli per i voti finali e i confini di legislatura e di governo. Trascinare sulla striscia è un filtro di date, lo stesso che si ottiene scrivendo "dal 2024". La lista delle sedute compare solo nel pannello, per l'intervallo selezionato.

```text
2022 │▁▁▂▃▅█▅▂▁▁▂▃▇█▃▂▁│ 2025      ▲ voto finale   ┊ cambio governo
          [=========]  selezione: mar-giu 2024 → 9 sedute
```

### 5.7 Avanzamento: gli slot sono la barra

Nessuna lista di passi. Gli slot vuoti hanno la superficie incassata e l'etichetta di ciò che arriva. Con `prefers-reduced-motion` nessuna pulsazione, solo il cambio di testo. `aria-live` annuncia solo "Voci pronte", "Sintesi pronta", "Verifica completata".

## 6. Capacità esistenti e dove finiscono

| Capacità (endpoint) | Nel concept |
|---|---|
| `POST /api/chat` + SSE (`commissioni`, `experts`, `citations`, `balance`, `compass`, `chunk`, `citation_details`, `trace`) | Motore del dossier; ogni evento riempie uno slot |
| Cache risposte e registro in volo (`build_cache_key`) | Dossier già noti si aprono istantanei |
| `GET/DELETE /api/chat/task/{id}` | Riconnessione e Stop del campo |
| `POST /api/compass` | Strisce di posizione; anche standalone da palette |
| `POST /api/authority-ranking` | Ragioni accanto alle voci; classifica da palette |
| `GET /api/search/results` | Blocco "Negli atti" e comando "cerca negli atti" |
| `GET /api/search/deputies`, `/groups` | Router entità, pannelli, permalink |
| `GET /api/search/speech/{id}`, `/act/{uri}` | Contesto citazione, pannello atto |
| `GET /api/evidence/{id}`, `/verify` | Spunta di verifica e foglio fonte |
| `GET /api/timeline`, `/debates`, `/sessions/{id}/votes`, `/votes/{id}`, `/act-text` | Ritmo, pannello seduta e voto, matrice parole e voti |
| `GET /api/timeline/speakers/{debate}/{speaker}` | "Cosa ha sostenuto in questo dibattito" nel pannello deputato |
| `GET /api/config/recent-topics`, `/last-update`, `/parties`, `/coalitions` | Stato vuoto, data dei dati, ricevuta di copertura |
| `GET /api/data/*`, `/api/graph/*` | Pagina `/dati` ed esploratore per ricercatori |
| `GET/POST /api/history` | Sostituito da cronologia locale più permalink `/d/{id}` |
| `feedback`, `newsletter`, `surveys`, `evaluation` | Barra di feedback sotto il dossier; "Segui il tema" usa l'infrastruttura newsletter; valutazione resta pagina interna |

## 7. Ecosistema con Stenografo

- **Passa la mano verso Stenografo** quando l'input chiede un fatto puntuale (voto di una persona, esito, chi presiede): blocco di passaggio con la domanda precompilata (`stenografo.it/chat?q=`), senza avviare la pipeline lunga.
- **Riceve da Stenografo** domande di confronto con lo stesso parametro `?q=`; il dossier parte da S1.
- **Dentro il dossier**, ogni cella della matrice voti ha "Chiedi a Stenografo i dettagli di questo voto".
- **Condividono**: token, tipografia a tre voci, `QuestionComposer`, `SourcesPanel`/`SourcesSheet`, `VoteCard`, `Hemicycle`, `OutcomeShape`, `ClarifyOptions`, `HandoffCard`, disclaimer, voce. Il dossier è la versione lunga dell'`Answer` di Stenografo: stessa grammatica DOMANDA, ricevuta, FONTI.
- **Differenza visibile**: accento blu, e la presenza di più gruppi a confronto in ogni blocco.

## 8. Rischi, costi, MVP

### Rischi

- **Router sbagliato**: mitigato da interpretazione visibile e correggibile, e dalle regole prima del modello.
- **Utenti esperti** che oggi usano ranking, bussola e ricerca come strumenti: la palette li conserva come comandi con URL propri (`/?cmd=ranking&q=…`).
- **Cronologia**: oggi `ChatHistory` è globale e senza utente, quindi una cronologia "tua" sul server mostrerebbe le domande di altri. Il concept la porta sul dispositivo.
- **Multi-legislatura**: maggioranza e opposizione dipendono dal governo alla data, non dalla legislatura. Senza questo, il bilanciamento in XVIII è falso.
- **Senato**: gruppi con nomi diversi dalla Camera; la mappa deve allineare per partito solo se il dato lo consente, altrimenti due strisce separate.
- **Costo LLM** del classificatore: piccolo, e solo sugli input non risolti dalle regole.

### Nuovi endpoint o modifiche

1. `POST /api/route`: intento, entità risolte, scope proposto. Regole più `check_domain` esteso.
2. `scope` in `ChatRequest`, `CompassRequest`, `RankingRequest`, timeline e search (il modulo `scope.py` esiste, i router non lo leggono ancora).
3. `GET /api/lens/preview?q=&scope=`: commissioni, atti, votazioni e date dal grafo senza LLM, per lo scheletro in meno di 3 s.
4. `GET /api/lens/votes?q=&scope=`: votazioni collegate al tema con esito per gruppo (atti per similarità di embedding, poi voti).
5. Endpoint tipizzati per deputato, gruppo, atto: le pagine oggi interrogano Cypher dal frontend via `/api/graph/query`.
6. Coalizione per governo e data (`download_governments_csv.py` è il punto di partenza).
7. Filtro per coalizione nella pipeline, solo se si vuole rigenerare la sintesi; il filtro client basta per l'MVP.

### MVP in 3 settimane

- **Settimana 1.** Pagina unica con campo, scope chip (Camera XIX attiva, le altre come "presto" finché il dato non c'è), router a regole (entità, atto, citazione, posizionale, passaggio a Stenografo). Dossier che rende gli eventi SSE esistenti nell'ordine in cui arrivano: voci prima della sintesi. Redirect dalle vecchie rotte.
- **Settimana 2.** Blocchi Voci (con verifica inline), Strisce di posizione, Ritmo da `topic_stats`, ricevuta di copertura. Pannello e foglio entità con endpoint esistenti. Cronologia locale e palette `⌘K` con i comandi ranking e ricerca.
- **Settimana 3.** `/api/lens/votes` in versione semplice e matrice parole e voti; filtri client ("solo opposizione", gruppo, date); mobile, tastiera, screen reader, `prefers-reduced-motion`; misura del tempo al primo contenuto.

Fuori dall'MVP: `/api/lens/preview` completo, confronto tra due gruppi, dossier fissati condivisi, "Segui il tema", Senato e XVIII nello scope attivo, follow-up con riscrittura della domanda (`query_rewriter` esiste ma non conserva il contesto).
