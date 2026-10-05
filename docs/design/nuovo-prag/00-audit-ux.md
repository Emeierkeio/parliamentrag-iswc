# Audit UX di ParliamentRAG prima del redesign

Data: 2 ottobre 2026. Base: branch `feat/redesign-ecosistema`, dev server su
`localhost:3100` con dati di produzione (Camera, XIX legislatura, aggiornati al
30/09/2026). Le schermate citate (`d_*` desktop 1440x900, `m_*` mobile 390x844,
`q1_*` domanda dal vivo, `hd_*`/`wd_*`/`wm_*` risposta salvata) sono nella
scratchpad della sessione, cartella `audit/`. I numeri di latenza vengono da una
domanda eseguita dal vivo e dalle tracce server delle ultime 40 risposte nello
storico (`/api/history/{id}` → `trace.total_ms`).

## 1. Chi lo usa e per cosa

| Chi | Lavoro da svolgere | Domanda tipica |
|---|---|---|
| Giornalista politico | Trovare in 10 minuti una frase citabile per ogni schieramento e verificarla sul resoconto prima di pubblicare | "Cosa hanno detto FdI e PD sul salario minimo, con data e seduta?" |
| Cittadino curioso | Capire chi è a favore e chi contro, senza leggere un saggio | "I partiti sono d'accordo sull'autonomia differenziata?" |
| Ricercatore / dottorando | Estrarre un corpus di posizioni attribuite e riproducibili, con metodo dichiarato | "Come si posizionano i gruppi sul PNRR tra 2023 e 2026?" (poi export, RDF, MCP) |
| Staff parlamentare / policy analyst | Sapere chi presidia un tema in ogni gruppo e cosa ha votato il gruppo, per preparare un incontro o un emendamento | "Chi è il riferimento della Lega sul lavoro e come ha votato la Lega sulle mozioni sul salario?" |
| Docente di educazione civica | Mostrare in classe il confronto tra maggioranza e opposizione su un tema, con fonti primarie | "Fammi vedere il dibattito sulla riforma della giustizia, in breve" |

Quattro su cinque vogliono prima una sintesi breve e solo dopo il dettaglio. Due
su cinque (giornalista, analista) hanno bisogno di passare da una frase al voto
dello stesso gruppo, cosa che oggi l'interfaccia non permette.

## 2. Mappa dell'esistente

IA attuale: landing `/` (marketing), poi un'app con sidebar a tre blocchi
(`Interroga l'Aula`; Esplora: Cerca nei resoconti, Parlamentari, Gruppi, Lavori
d'Aula; Analizza: Analisi Autorità, Compasso Ideologico) e voci di servizio.
Su mobile la barra in basso ha Chat, Atti, Autorità, Compasso, Aula, Altro;
Parlamentari e Gruppi finiscono sotto "Altro" (`MobileBottomNav.tsx`, `m_home.png`).

| Strumento | Scopo dichiarato | Input | Output | Tempo misurato | Sovrapposizioni |
|---|---|---|---|---|---|
| `/home` → `/chat/[id]` | Posizioni dei gruppi su un tema | Domanda libera | Saggio per gruppo con citazioni, esperti, bussola, traccia | Mediana 67 s (53-102 s, 40 risposte) | Contiene già esperti e bussola |
| `/search` | Cercare atti e interventi | Parola chiave, autore, tipo, date | Lista risultati, dialog con testo | 9,7 s per "salario minimo" | Stessa intenzione "tema" della chat |
| `/ranking` | Deputati più autorevoli su un tema | Tema, coalizione, gruppo, commissione | Classifica con punteggio in 6 componenti | 66 s | Duplica il passo 3 della chat |
| `/compass` | Bussola ideologica | Tema | Mappa a due assi dei gruppi | 47 s | Duplica il passo 6 della chat |
| `/timeline` | Lavori d'Aula | Periodo, ricerca | Sedute, dibattiti, sintesi IA, voti, emiciclo | 3 s | Unico accesso ai voti |
| `/parlamentari`, `/[id]` | Anagrafica | Nome | Gruppi, commissioni, interventi recenti | 4 s | Nessun legame con temi o voti |
| `/gruppi`, `/[slug]` | Gruppi | nessuno | Elenco componenti | 3-6 s | Solo membri |
| `/explorer` | Query Cypher | Cypher | Tabella, grafo, JSON | 17 s al primo caricamento | Strumento da sviluppatore nella nav principale |
| `/data`, `/method`, `/iswc` | Dati aperti, metodo, paper | nessuno | Pagine statiche | 2-6 s | nessuno |

Quattro pagine aprono con un campo "tema" e le stesse chip (PNRR, Riforma
sanitaria, Salario minimo...): `d_home.png`, `d_ranking.png`, `d_compass.png`,
e con chip diverse `d_search.png`. L'utente deve scegliere lo strumento prima di
sapere cosa gli serve.

## 3. Capacità nascoste o sottoutilizzate

- **Risultati intermedi già pronti.** La pipeline emette `experts` (passo 3),
  `citations` (passo 4), `balance` (5) e `compass` (6) molto prima del testo
  (`backend/app/routers/chat.py`, righe 238-370). Nelle 40 tracce gli esperti
  sono pronti in mediana a 30 s su 67. L'interfaccia li nasconde: finché non
  arriva il risultato del passo 7 mostra solo lo stepper a pagina intera
  (`ChatArea.tsx`, ramo `ProgressFullPage`).
- **Streaming simulato.** Il testo viene generato per intero e poi spedito a
  pezzi da 50 caratteri ogni 20 ms (`chat.py` intorno alla riga 561). Il primo
  carattere arriva quando la risposta è già finita.
- **Verifica della citazione su richiesta.** `/api/evidence/{id}` e
  `/api/evidence/{id}/verify` esistono e nessun file del frontend li chiama.
- **Voti per gruppo e per deputato.** 17,5k votazioni e 7M voti individuali,
  con emiciclo e testo dell'emendamento (`/timeline/votes/{id}`, `act-text`),
  sono raggiungibili solo navigando seduta per seduta. Né la risposta, né la
  scheda deputato, né la scheda gruppo mostrano un voto.
- **Sintesi di posizione per oratore e dibattito** (`/timeline/speakers/...`):
  esiste per la timeline, non viene mai riusata nella risposta o nel profilo.
- **Statistiche del tema** (`topic_stats`: interventi, deputati, periodo) sono
  sotto i link "78 interventi · 54 deputati" e in un modal, non come filtro.
- **Modalità `high_quality`** e `hq_variants`, endpoint sincrono `/api/query`,
  baseline A/B nello storico: nessun uso in UI.
- **Server MCP** (`mcp/server.py`, 7 strumenti, emiciclo PNG/SVG con URL
  stabile): citato solo nel footer della landing. È già il canale "Parlamento
  dentro il tuo assistente" per ricercatori e redazioni.
- **ScopePicker** ("Camera · XIX legislatura") è un segnaposto non interattivo
  (`ScopePicker.tsx`), mentre Senato e XVIII sono in arrivo.

## 4. Attriti misurati

**Attesa.** Domanda dal vivo "Cosa pensano i partiti del salario minimo?": per
15 s lo schermo resta su "Analisi query"; il passo 1 è "in corso" mentre sotto
compare già il risultato della commissione (`q1_t008.png`); gli esperti
compaiono come riga di testo a 82 s (`q1_t090.png`); a 118 s la pipeline era
ancora al passo 6 di 8 (server di sviluppo, quindi più lento della mediana).
Durante l'attesa la domanda dell'utente non è visibile: il campo in alto torna
a "Cerca un tema...". Il pannello spiega il metodo ("Calcoliamo le percentuali
di rappresentanza...") ma non dà nulla da leggere sul tema. Nella traccia PNRR
(`wd_quinte.png`): 72 s, 30 chiamate LLM, 97,7k token, circa 0,12 $; autorità
21,8 s, bussola 42 s in parallelo alla generazione (27 s).

**Lunghezza.** Risposta mediana 1.338 parole (9.850 caratteri), cioè 6-7 minuti
di lettura; 11 citazioni. Su mobile è oltre 7 schermate prima di arrivare a
esperti e citazioni. Non c'è una sintesi in testa: si apre con "Introduzione"
generica (`hd_view.png`). Ogni paragrafo di gruppo inizia con lo stesso schema
e un difetto di maiuscola: "Per Fratelli d'Italia, All'interno del gruppo..."
(`hd.txt`). Alcune citazioni scelte sono deboli rispetto al tema (D'Alessio,
"vota contro le questioni pregiudiziali", `wd_03.png`).

**Scelta dello strumento.** Quattro campi "tema", nomi diversi per la stessa
cosa: Bussola ideologica (landing, risposta) e Compasso Ideologico (nav);
"Cerca nei resoconti" in nav e "Ricerca Atti" nel titolo. Il placeholder della
chat dice "Cerca un tema...", che suggerisce una ricerca per parola chiave
mentre la landing promette "una domanda". Explorer Cypher sta nella stessa nav
del cittadino.

**Navigazione tra entità.** Nessun componente in `components/chat`,
`components/timeline` o `components/search` porta a `/parlamentari/...` o
`/gruppi/...`. Dalla citazione si esce solo verso camera.it. Il nome
dell'esperto apre un dettaglio di punteggio, non il profilo. La scheda deputato
(`d_parlamentari_detail.png`) non ha posizioni, voti né autorevolezza per tema;
la scheda gruppo (`d_gruppi_detail.png`) è solo un elenco di nomi. Il percorso
citazione → deputato → gruppo → seduta → voto non esiste.

**Verificabilità percepita.** Il cuore c'è: virgolettato in serif evidenziato,
avviso onesto sotto la risposta. Ma cliccare una citazione fa saltare la pagina
alla scheda in fondo, perdendo il punto di lettura (`wd_citeclick.png`). Le
schede mostrano date ISO ("2025-10-01"), orari duplicati ("(ore 9,35) (ore
9,35) (ore 9,35)"), nessun numero di seduta per il Governo. Gli esperti hanno
punteggi compressi tra 53 e 66 (`wd_tab_BUSSOLA.png`): differenze che non si
leggono.

**Mobile.** Le righe esperto escono dal bordo destro a 390 px; la bussola è un
insieme di punti colorati senza etichette (`wm_tab_BUSSOLA.png`); la timeline
è leggibile ma le sintesi di seduta iniziano tutte con "Nella sessione
parlamentare del ... sono stati trattati i seguenti argomenti: missioni"
(`m_timeline.png`), quindi poco informative.

**Onboarding e confini.** La home spiega cosa fa ma non cosa non fa. Nello
storico c'è "Verrà rinnovato il bonus per ristrutturazione edilizia al 50% nel
2027?": domanda fattuale o previsionale che ha ricevuto un saggio di 1.000+
parole invece di un rinvio a Stenografo. Il gate attuale blocca solo le domande
fuori dominio. La Cronologia mostra le ultime 50 domande di tutti gli utenti,
non le proprie (`HistoryModal.tsx` legge `/api/history` senza filtro).

## 5. Cosa preservare assolutamente

1. Citazioni verbatim verificate parola per parola, con regola "se non è stato
   detto in aula non entra": è il valore che nessun LLM generalista offre.
2. Copertura garantita di tutti i gruppi e simmetria maggioranza/opposizione,
   Governo separato e Gruppo Misto scomposto per componente.
3. Autorevolezza per tema con criteri dichiarati e scomponibili: dice perché
   parla quella persona.
4. "Dietro le quinte": tempi, modelli, token e costo di ogni risposta
   (`wd_quinte.png`). Trasparenza rara, da tenere vicino alla risposta.
5. Neutralità e linguaggio del design system condiviso con Stenografo; esiti di
   voto mai verde/rosso come giudizio.
6. Lavori d'Aula con sintesi, voti, emiciclo e testo votato.
7. Dati aperti (RDF, Zenodo, Hugging Face) e MCP come seconda interfaccia.

## 6. Le 10 opportunità più grandi

1. **Risposta progressiva reale.** Mostrare subito la domanda, a ~30 s gli
   esperti per gruppo e le citazioni candidate, poi la mappa delle posizioni,
   infine il testo in streaming vero. L'attesa diventa lettura; il tempo
   percepito si dimezza senza toccare la pipeline.
2. **Sintesi in testa, dettaglio a richiesta.** Cinque righe (chi è a favore,
   chi contro, su cosa si divide la maggioranza) più una griglia "gruppo →
   posizione in una frase → citazione". Le sezioni lunghe si aprono per gruppo.
   Obiettivo: utile in 30 secondi, completo in 3 minuti.
3. **Detto e votato.** Accanto alla posizione di ogni gruppo, i voti dello
   stesso gruppo sugli atti del tema (dati già nel grafo). È la domanda che
   giornalisti e analisti fanno subito dopo, e rende ParliamentRAG
   complementare a Stenografo invece che concorrente.
4. **Grafo navigabile.** Ogni nome, gruppo, seduta e votazione diventa un link
   interno coerente. Schede deputato e gruppo con temi presidiati, citazioni
   recenti, voti e autorevolezza; dalla timeline "chiedi su questo dibattito".
5. **Un solo ingresso, instradato.** Un campo che riconosce il tipo di domanda:
   posizioni → risposta; fatto o voto puntuale → Stenografo con la domanda già
   compilata; nome → profilo; parola chiave → ricerca. Classifica autorità e
   bussola diventano viste della pagina tema, non strumenti da scegliere prima.
6. **Citazione verificabile sul posto.** Pannello laterale (foglio su mobile)
   con paragrafo prima e dopo, seduta numerata, data in italiano, esito della
   verifica via `/evidence/{id}/verify` e link al punto del resoconto. Nessun
   salto in fondo pagina.
7. **Ambito esplicito e funzionante.** Camera/Senato e legislatura come filtro
   reale, visibile nell'URL, nel titolo della risposta e in ogni citazione;
   confronto tra legislature come uso naturale ("cosa diceva la Lega nella
   XVIII?").
8. **Pagine tema pronte.** Le chip di tendenza e i temi della settimana
   precalcolati e cachati come pagine stabili, condivisibili e indicizzabili,
   con data di aggiornamento: risposta istantanea per l'80% del traffico
   d'ingresso e niente 66 s per una classifica.
9. **Mobile pensato per il confronto.** Schede per gruppo scorrevoli, bussola
   con etichette e lista alternativa, righe che non escono dallo schermo,
   Parlamentari e Gruppi fuori da "Altro".
10. **Vocabolario e confini chiari.** Un nome per cosa (Bussola, Autorevolezza,
    Lavori d'Aula), esempi di domande buone e cattive, una riga su cosa
    ParliamentRAG non fa, cronologia personale invece che globale, Explorer
    spostato nell'area dati per sviluppatori.
