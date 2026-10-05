# Concept B: il dossier di tema

Stato: proposta di design, nessuna implementazione. Data: 2 ottobre 2026.

## 1. Il concept in una frase

ParliamentRAG smette di essere una chat con otto strumenti intorno e diventa una
raccolta di dossier: una pagina stabile per ogni tema (salario minimo, autonomia
differenziata, PNRR), che il sistema tiene aggiornata a ogni nuova seduta e che
dice cosa pensa ogni gruppo, con le sue parole, e cosa ha votato.

**Principio guida: la risposta esiste prima della domanda.** Le domande sui temi
politici sono poche centinaia e si ripetono. Invece di far aspettare
quaranta secondi a ogni visitatore per ricostruire la stessa risposta, la
calcoliamo una volta, la datiamo, la rendiamo citabile e la aggiorniamo quando
cambiano i dati. La domanda libera resta, ma serve a trovare un dossier o a
farne nascere uno.

## 2. Modello di interazione

**Come si arriva.** Quattro porte, una sola destinazione:

- da un motore di ricerca ("salario minimo posizione partiti") direttamente su
  `/tema/salario-minimo`, pagina renderizzata lato server, leggibile senza
  JavaScript;
- da un link condiviso, spesso a una singola citazione
  (`/tema/salario-minimo/c/8f3a2`), che apre il dossier con quella citazione in
  evidenza;
- dall'indice dei temi in home, ordinato per attività recente in Aula;
- dal campo domanda. La domanda viene confrontata con le definizioni dei dossier
  esistenti. Sopra soglia si atterra sul dossier, all'altezza giusta. Sotto
  soglia parte la pipeline attuale e nasce un **dossier provvisorio** che si
  riempie sezione per sezione mentre arrivano gli eventi SSE.

**Come si legge.** Dall'alto in basso, in tre profondità.
Il cittadino si ferma alla prima: una frase per gruppo e la citazione più forte.
Il giornalista scende alla seconda: andamento nel tempo, voti, voci
autorevoli, disaccordi interni. Il ricercatore apre la terza: tutte le fonti,
i parametri, l'export.

**Come si approfondisce.** Ogni elemento è un link a una pagina entità
(deputato, gruppo, seduta, voto, atto), che però si apre come pannello laterale
(desktop) o foglio dal basso (mobile) sopra il dossier. Il contesto non si perde;
l'URL cambia, quindi anche il pannello è condivisibile.

**Come si torna.** Il dossier è l'unico livello. Chiudere il pannello riporta al
punto esatto. Le pagine entità aperte a tutta pagina mostrano "Compare in 6
dossier" come via di ritorno ai temi.

**Come si condivide.** Tre granularità: il dossier (`/tema/slug`), la sezione
(`#voti`), la citazione (`/c/id`, con anteprima Open Graph che riporta il testo
verbatim, oratore, gruppo, data e link camera.it). Ogni citazione e ogni riga di
posizione hanno "Cita" (formato APA e testo semplice con data di consultazione) e
"Incorpora" (card iframe con altezza fissa, stessa resa del sito).

## 3. Architettura dell'informazione

**Cosa sparisce.** La sidebar. La chat come prodotto a sé. Le pagine Ranking e
Bussola come strumenti separati: erano viste parziali di un tema, diventano
sezioni del dossier. La timeline delle sedute come lista: diventa l'asse del
tempo del dossier e la pagina seduta. L'explorer del grafo esce dal percorso
pubblico e va in `/dati`.

**Cosa si fonde.** Ricerca negli atti + chat + ranking + bussola = dossier. Lo
storico delle chat diventa "Dossier che segui". Deputati e gruppi restano pagine,
ma organizzate per tema invece che per elenco.

**Pagine.**

| Pagina | URL | Ruolo |
|---|---|---|
| Indice | `/` e `/temi` | campo domanda, temi attivi, tutti i temi per area EuroVoc |
| Dossier | `/tema/{slug}` | unità del prodotto |
| Citazione | `/tema/{slug}/c/{id}` | permalink, contesto prima e dopo |
| Confronto | `/tema/{slug}/confronta?a=PD&b=FDI` o `?leg=18,19` | due colonne |
| Deputato | `/deputato/{id}` | temi su cui interviene, voti, incarichi |
| Gruppo | `/gruppo/{slug}` | posizioni del gruppo su tutti i dossier |
| Seduta | `/seduta/{camera}/{leg}/{n}` | ordine del giorno, temi toccati |
| Voto | `/voto/{id}` | esito, voti individuali, testo votato |
| Atto | `/atto/{uri}` | iter, firmatari, EuroVoc, dossier collegati |
| Dati | `/dati` | RDF, statistiche, grafo, metodo |

**Ramo e legislatura.** Un dossier è un tema, non un tema in una Camera.
L'ambito è un filtro esplicito nella testata ("Camera, XIX legislatura" come
default, poi XVIII e Senato quando ci sono), scritto nell'URL (`?ambito=camera-19,camera-18`)
e riflesso nell'asse del tempo, dove le legislature sono fasce con etichetta. I
gruppi che cambiano nome tra legislature vengono collegati dal crosswalk delle
persone, mai fusi in silenzio: la riga mostra "M5S (XVIII) e M5S (XIX)".
Quando un tema ha dati in una sola Camera lo dice, invece di mostrare l'altra vuota.

## 4. Schermate chiave

### 4.1 Indice (desktop)

```
+--------------------------------------------------------------------------+
| (emiciclo) ParliamentRAG       Temi   Metodo   Dati     [Stenografo ->]  |
+--------------------------------------------------------------------------+
|                                                                          |
|   Cosa pensano i gruppi parlamentari su...                               |
|   [ salario minimo________________________________________ ] (Cerca)     |
|   Camera, XIX legislatura  v                                             |
|                                                                          |
|   IN AULA QUESTA SETTIMANA                       aggiornato al 30 set    |
|   Legge di bilancio 2027   Autonomia differenziata   Separazione carriere|
|   12 nuove citazioni       3 voti                    1 nuovo intervento  |
|                                                                          |
|   TUTTI I TEMI                                                           |
|   Lavoro          Salario minimo · Sicurezza sul lavoro · Smart working  |
|   Istituzioni     Premierato · Autonomia differenziata · Legge elettorale|
|   Economia        PNRR · Superbonus · Legge di bilancio                  |
+--------------------------------------------------------------------------+
```

La home non ha più strumenti da scegliere: un campo e un indice. I temi attivi
vengono da `/api/config/recent-topics`, già calcolato a ogni aggiornamento dati.

### 4.2 Dossier, primo livello (desktop)

```
+--------------------------------------------------------------------------+
| ParliamentRAG  [ chiedi o cerca un tema ______________ ]          Temi   |
+--------------------------------------------------------------------------+
| Salario minimo                                    Segui  Cita  Condividi |
| Camera XIX · 214 interventi di 61 deputati · 9 voti · aggiornato al 30/9 |
|--------------------------------------------------------------------------|
| In breve: la maggioranza preferisce la contrattazione collettiva; le     |
| opposizioni chiedono una soglia di legge a 9 euro. [1][2]                |
|                                                                          |
| MAGGIORANZA                      | OPPOSIZIONE                           |
| FdI  Contrattazione, no soglia   | PD   Soglia legale a 9 euro           |
|  "Il salario giusto lo fanno i   |  "Sotto i nove euro non e' lavoro,    |
|   contratti, non..."  [cit 1]    |   e' sfruttamento..."  [cit 2]        |
|   Rossi M. · 12 dic 2023  +14    |   Bianchi L. · 6 dic 2023  +22        |
| Lega ...                         | M5S ...                               |
| FI   ...                         | AVS ...                               |
| NM   nessun intervento sul tema  | Az, IV ...                            |
|--------------------------------------------------------------------------|
| [Nel tempo] [Detto e votato] [Voci] [Bussola] [Disaccordi] [Fonti]       |
+--------------------------------------------------------------------------+
```

Annotazioni: la testata porta sempre i numeri e la data di aggiornamento. Le
assenze sono dichiarate. Le sezioni sotto sono ancore, non tab: la pagina è una
sola e scorre.

### 4.3 Dossier, ramo "Detto e votato" (desktop)

```
| DETTO E VOTATO                                                           |
| Voto finale AC 1275, 6 dic 2023 · Approvato · emendamento soppressivo    |
|                                                                          |
|          ha detto                         ha votato                      |
| FdI      contrattazione  [cit]            ●●●●●●●●●●●●●●●●●○  favorevole |
| PD       soglia legale   [cit]            ■■■■■■■■■■■■■■■■■■  contrario  |
| Az       soglia, ma...   [cit]            ◆◆◆◆■■■○             diviso    |
|                                            ^ 2 contrari, apri elenco    |
| Altri 8 voti sul tema  v                                                 |
```

### 4.4 Domanda che non trova un dossier (desktop)

```
| Dossier provvisorio: "tassazione delle criptovalute"                     |
| Stiamo leggendo 1.240 interventi. Di solito servono 30-40 secondi.       |
| [x] Trovati 38 interventi pertinenti                                     |
| [x] Voci autorevoli per gruppo                                           |
| [ ] Posizioni dei gruppi   ......                                        |
| [ ] Bussola                                                              |
| Esiste gia' un tema vicino: "Fisco e criptoattivita'" ->                 |
```

Gli eventi SSE esistenti (`gate`, `experts`, `compass`, `citations`, `complete`)
riempiono le sezioni nell'ordine in cui arrivano. Se il gate dice che il tema
non è parlamentare, rimanda a Stenografo o propone riformulazioni.

### 4.5 Dossier su mobile

```
+------------------------------+
| <  Salario minimo      ...   |
| Camera XIX · agg. 30/9       |
|------------------------------|
| In breve: la maggioranza...  |
|                              |
| FdI  Contrattazione          |
| "Il salario giusto lo fanno  |
|  i contratti..."             |
| Rossi M. · 12/12/23   +14 >  |
|------------------------------|
| PD   Soglia legale a 9 euro  |
| "Sotto i nove euro..."       |
|------------------------------|
| [ Chiedi in questo tema   ]  |
+------------------------------+
```

Su mobile maggioranza e opposizione alternano riga per riga, nell'ordine fisso
del Regolamento, non per colonne. Il composer resta in basso.

### 4.6 Citazione aperta, foglio mobile

```
+------------------------------+
| ---                          |
| Bianchi L. (PD)              |
| Seduta 214 · 6 dic 2023      |
|                              |
| ...contesto precedente...    |
| "Sotto i nove euro non e'    |
|  lavoro, e' sfruttamento."   |
| ...contesto successivo...    |
|                              |
| Verificata sul resoconto     |
| [camera.it] [Cita] [Copia    |
|  link] [Altre 22 del PD]     |
+------------------------------+
```

## 5. Rappresentazione dei risultati

Ogni forma risponde a una domanda precisa del dossier. La regola: prima la frase,
poi il segno, poi il numero. Nessun colore di partito; i gruppi si riconoscono
dalla sigla, sempre scritta.

**Posizioni dei gruppi: righe di posizione, non card.** La domanda è "cosa
pensa ciascuno". La risposta è un elenco: sigla, una frase di sintesi ancorata
alle citazioni, la citazione più forte in serif, il conteggio delle altre. Le
card in griglia mettevano tutto sullo stesso piano e costringevano a cercare;
la riga si legge come un sommario di giornale (wireframe 4.2).

**Bilanciamento: una proprietà dell'impaginazione, non un grafico.** Le barre
maggioranza/opposizione misuravano il sistema, non il tema. Nel dossier il
bilanciamento è visibile perché le due metà hanno lo stesso numero di posti e
ogni assenza è scritta. In fondo una sola riga: "18 citazioni di maggioranza,
19 di opposizione, Misto separato".

**Bussola: strisce a un asse, non scatter 2D.** Lo scatter fondeva due assi
derivati e suggeriva una precisione che non c'è. Qui ogni asse del tema è una
striscia con i due poli scritti in parole; ogni gruppo è un segno con
l'intervallo delle sue citazioni. Un intervallo largo è un'informazione: il
gruppo non ha una linea unica. Toccare un segno apre le citazioni che lo
determinano.

```
Chi fissa il salario?
legge  |----[FdI==]--------------------[==PD==]---| contratti
       |-------[==Lega=======]------[M5S]--------|
Quanto subito?
gradual|--[FI]------[=====Az=====]-------[AVS]---| immediato
```

**Tempo: un rigo per gruppo, non una lista di sedute.** La domanda è "è cambiato
qualcosa?". Ogni gruppo ha una riga; ogni intervento è un tratto; i voti sono
linee verticali che attraversano tutte le righe; le legislature sono fasce. Un
cambio di posizione rilevato dallo stance score è marcato con una freccia e una
citazione prima/dopo.

```
            XVIII leg.        |         XIX leg.
FdI   . ..  .      .          |  ..||.   ..  ->.    .
PD       ...   ..   .         |  .|||.. ..  .  ..
M5S  ..... ...  ....          |   .||.   .     .
                              |    ^ voto 6/12/23
```

**Voci autorevoli: chi parla per il gruppo, con il perché.** Le barre di
punteggio chiedevano di fidarsi di un numero. Qui per ogni gruppo da una a tre
persone, ciascuna con il motivo in parole: "relatrice in Commissione Lavoro,
prima firmataria AC 1275, 14 interventi". Le sei componenti del punteggio restano
nel dettaglio, per chi le vuole verificare.

```
PD   Bianchi L.   relatrice Comm. XI · prima firmataria AC 1275 · 14 interventi
     Verdi A.     capogruppo in Commissione · 9 interventi
```

**Voti: file di segni per gruppo, non emiciclo.** L'emiciclo risponde a "com'è
andata in Aula"; il dossier chiede "ogni gruppo ha votato compatto, e come".
Una fila di segni per gruppo (forma e icona dell'esito, dal design system
comune), ordinata per esito, rende visibili i dissenzienti (wireframe 4.3).
L'emiciclo resta nella pagina voto.

**Detto e votato: due colonne allineate.** Una riga per gruppo: a sinistra la
posizione dichiarata, a destra l'esito sui voti chiave. Quando le due cose non
coincidono la riga porta "da leggere insieme", mai "incoerente": può esserci un
emendamento, un voto tecnico, un accordo di coalizione.

**Disaccordi nelle coalizioni: coppie di citazioni.** Due citazioni dello stesso
schieramento, affiancate, con date. È la forma più onesta per dire "non sono
d'accordo" senza commentarlo.

**Citazioni: testo in serif con numero di nota.** Nel corpo restano note
numerate; aperte, mostrano il contesto prima e dopo e lo stato di verifica
(endpoint `/api/evidence/{id}/verify`), wireframe 4.6.

## 6. Dove finisce ogni capacità del backend

| Capacità (endpoint) | Nel dossier | Precalcolo |
|---|---|---|
| Pipeline risposta `POST /api/chat`, `/api/query` (SSE) | "In breve" e righe di posizione; dossier provvisorio | sì, per dossier e ambito |
| `citation_details`, `/api/evidence/{id}`, `/verify` | note, permalink citazione | sì, citazioni congelate per snapshot |
| `experts`, `POST /api/authority-ranking` | sezione Voci | sì |
| `POST /api/compass` | sezione Bussola | sì, assi fissati per dossier |
| `topic_stats` | testata (interventi, deputati, date) | sì |
| `commissioni` | Voci, motivazioni | sì |
| `/api/timeline`, `/debates/{id}` | pagina seduta, rigo del tempo | indice tema-seduta |
| `/timeline/votes/{id}`, `/act-text`, sessions votes | Detto e votato, pagina voto | elenco voti collegati per tema |
| `/timeline/speakers/{debate}/{speaker}` | pannello deputato in contesto | su richiesta, cache |
| `/api/search/results` | sezione Fonti (filtrata sul tema) e ricerca globale | no |
| `/search/deputies`, `/groups` | pagine deputato e gruppo | no |
| `/search/act/{uri}`, EuroVoc | pagina atto; indice temi per area | mappa tema-EuroVoc |
| `/api/config/recent-topics` | home, "In Aula questa settimana" | già precalcolato |
| `/api/config/last-update` | "aggiornato al" | no |
| `/api/data/*`, `/api/graph/*` | `/dati` | no |
| `/history` | "Dossier che segui" | no |
| `feedback`, `survey`, `evaluation` | "Segnala un errore" su ogni citazione; valutazione interna | no |
| `newsletter` | "Segui questo tema" via mail | digest per tema |

**Cosa precalcolare.** Un nodo `Topic` con slug, etichetta, domanda canonica,
ancore EuroVoc e atti collegati. Per ogni tema e ambito uno `Snapshot`
(versione dati, versione pipeline, data) con posizioni, citazioni, voci, assi
e posizioni della bussola. Per il tempo, stance per citazione aggregate per
trimestre. Dopo `make update-data` un job individua i temi toccati (atti in
`DISCUSSES`, nuovi chunk vicini al centroide del tema) e rigenera solo quelli.
Se uno snapshot cambia, una riga "Cosa è cambiato dal 15 settembre" sopra "In
breve" mostra le citazioni nuove.

## 7. Ecosistema con Stenografo

Stessi token, tipografia, forme degli esiti di voto, stesso header "Rete".
Stenografo risponde a una domanda puntuale con una frase; ParliamentRAG risponde
a "cosa pensano" con una pagina. Gli scambi:

- in Stenografo, una risposta su un voto mostra "Il tema di questo voto ha un
  dossier" quando l'atto è collegato a un `Topic`;
- in ParliamentRAG, ogni segno di voto individuale e ogni domanda fattuale
  ("come ha votato X?") portano a Stenografo con la domanda precompilata;
- le pagine deputato, voto e seduta sono candidate a una fonte unica condivisa,
  così non ne esistono due versioni.

## 8. Rischi, costi, MVP

**Rischi.**

- Un dossier statico invecchia male se il job fallisce: la data di
  aggiornamento deve essere visibile e un controllo deve segnalare snapshot
  più vecchi della versione dati.
- La "frase di sintesi" per gruppo è generata: va ancorata a citazioni numerate
  e passare lo stesso controllo di fedeltà del testo attuale, altrimenti è un
  giudizio editoriale.
- Scegliere i temi è una scelta politica. Criteri pubblici in `/metodo`:
  attività in Aula, atti con EuroVoc, domande ricevute.
- Abbinare una domanda al dossier sbagliato è peggio che non trovarlo: soglia
  alta, e "Non è questo? Chiedi comunque" sempre visibile.
- Il collegamento dei gruppi tra legislature e tra Camere può sembrare una
  equiparazione; va mostrato, non deciso.
- SEO duplicato tra dossier vicini: canonical e fusione dei temi.

**Costi.**

- Nuovi endpoint: `GET /api/topics`, `GET /api/topics/{slug}?ambito=`,
  `GET /api/topics/{slug}/quotes/{id}`, `GET /api/topics/match?q=`,
  `GET /api/topics/{slug}/votes`, `GET /api/topics/{slug}/trajectory`.
- Pipeline batch: circa 0,10 dollari per run completo (stima del design
  Traiettorie); 300 temi per due ambiti fanno circa 60 dollari a ricostruzione
  completa, molto meno con l'aggiornamento incrementale.
- Storage: snapshot JSON da 50-150 KB, versionati; qualche centinaio di MB
  all'anno in Neo4j o Postgres. Le pagine sono ISR in Next.js.

**MVP in tre settimane.**

1. Settimana 1: modello `Topic` e `Snapshot`, 20 temi scelti a mano, job che
   esegue la pipeline attuale e salva l'output della cache delle risposte come
   snapshot; endpoint di lettura.
2. Settimana 2: pagina dossier server-side con "In breve", righe di posizione,
   Voci e Detto e votato (solo voti con `ON_ACT` verso atti del tema);
   permalink e foglio citazione; anteprima Open Graph.
3. Settimana 3: home con indice, campo domanda con match verso i dossier e
   ripiego sulla chat attuale come dossier provvisorio non indicizzato; mobile;
   verifica WCAG 2.2 AA.

Restano fuori dall'MVP: rigo del tempo, strisce della bussola, confronto tra
legislature, incorporamento, Senato. Il resto dell'app attuale resta
raggiungibile da `/dati` fino alla migrazione.
