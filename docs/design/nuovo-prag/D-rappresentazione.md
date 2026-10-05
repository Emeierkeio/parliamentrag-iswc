# D. Come rappresentare i risultati

Documento di design, non di implementazione. Riparte da zero su *come* ogni
strumento di ParliamentRAG mostra i suoi risultati. Base: il design system di
Stenografo (`aulachiara/docs/DESIGN_SYSTEM.md`), `docs/design/ecosistema.md`, i
componenti attuali e le risposte reali del backend (catture del 2 ottobre 2026
su `localhost:3100`, tema "salario minimo"). I numeri negli schizzi sono
illustrativi.

## Cosa emerge dallo stato attuale

- **Bussola**: centroidi coi colori di partito su un piano 2D con pan e zoom.
  Su "salario minimo" i nove gruppi stanno su una diagonale (i due assi dicono
  la stessa cosa), le etichette M5S, PD e AVS si sovrappongono e PD sparisce,
  i punti degli interventi si ammassano agli angoli. Su mobile l'attesa parla
  di "PCA" ma il metodo è `stance`. Attesa: 67 secondi.
- **Autorevolezza**: punteggio 0-100 e barretta; il perché sta in un modale.
  Sigla scritta nel colore del partito. Oltre 60 secondi di solo scheletro.
- **Risposta**: prosa per Governo, Maggioranza, Opposizione, Misto; esperti,
  citazioni, bilanciamento ("78%" e due barre) e bussola chiusi sotto il testo.
- **Voti**: emiciclo con esiti a colore, forma, icona ed etichetta. Già giusto.
- **Colori di partito**: li ho passati al validatore della skill dataviz (nove
  colori, confronto su tutte le coppie come serve a uno scatter). Falliscono
  tutti i controlli: separazione per daltonici ΔE 5,7 (Azione/AVS), visione
  normale ΔE 11,5 (Lega/AVS, soglia 15), contrasto sotto 3:1 per quattro
  gruppi, giallo M5S a 1,34:1.

## Principio guida

**La posizione porta il significato, il testo porta l'identità, il colore porta
solo lo stato.** Un gruppo si riconosce dalla sigla scritta accanto al segno e
dalla riga che occupa, mai da un colore. Il colore resta per tre cose: esito di
voto, elemento a fuoco, intensità su una scala.

Ogni vista dichiara il suo perimetro con un'etichetta fissa
(`CAMERA · XIX LEGISLATURA`). Camere e legislature diverse non si mescolano mai
in un unico grafico: si affiancano in piccoli multipli con lo stesso asse. Un
deputato appare con il gruppo che aveva *alla data* dell'intervento o del voto.

---

## 1. Posizioni dei gruppi su un tema

**Domanda**: chi dice cosa, e su cosa sono d'accordo o divisi?

**Forma**: un *quadro dei gruppi*. Una riga per gruppo, tre colonne: sintesi di
una frase, la citazione più forte, la base (quanti interventi). Le righe stanno
in blocchi Governo, Maggioranza, Opposizione, Misto; dentro ogni blocco per
numero di seggi. Sopra il quadro, una striscia di accordo (vedi 2) che mostra in
un colpo d'occhio chi sta con chi. La prosa completa resta disponibile sotto,
come lettura lunga, non come primo livello.

**Perché**: dieci gruppi in prosa sono un muro di testo. Il quadro si legge
per riga (un gruppo) e per colonna (confronto). Il backend ha già i pezzi: il writer produce una
sezione per partito (`evidence_first_writer`), `position_brief` stima la
direzione, la citazione ha già `group`, `coalition`, data, seduta.

**Codifica**: nessun grafico dentro la riga. Sigla in Geist semibold, nome
esteso e seggi in `fg-muted`. Citazione in Source Serif, al massimo due righe,
attribuzione sotto. Base come numero ("14 interventi, 6 deputati").

**Interazione**: la riga si espande (bottone con `aria-expanded`): altre due o
tre citazioni, la sintesi estesa, il link alla scheda gruppo. Il marcatore nel
testo lungo porta alla stessa citazione nel quadro, e viceversa.

**Mobile**: lista di schede piatte (livello 1, niente bordo), sigla e frase in
alto, prima riga della citazione, tocco per espandere.

**Equivalente non visivo**: su desktop è una `<table>` vera con intestazioni di
riga; la prosa lunga è già il riassunto testuale.

**Dati scarsi**: il gruppo senza interventi resta nel quadro con la riga
"Nessun intervento trovato su questo tema in questo periodo". L'assenza è
un'informazione, toglierla falsa il confronto. Base sotto 3 interventi: etichetta
"base debole" accanto al numero.

```
SALARIO MINIMO · CAMERA · XIX · 132 interventi, 9 gruppi
Accordo  [FdI Lega FI NM]·······[IV]···········[Az][PD M5S AVS]
                                                            
GOVERNO
 Gov.      Sintesi in una frase.        «Citazione...»    5 int.
MAGGIORANZA
 FdI 116   Preferisce la contrattazione «Citazione verbatim  31 int.
           collettiva alla soglia...     su due righe...»
           Nome Cognome · 12 mar 2024 · seduta 263 ↗
 Lega 64   ...                                        ⌄
OPPOSIZIONE
 PD 69     ...
MISTO
 +Europa   Nessun intervento trovato su questo tema.
```

## 2. Bussola ideologica

**Domanda**: dove si collocano i gruppi lungo le linee di frattura di questo
tema, e quanto sono sicure quelle collocazioni?

**Forma**: due *dot plot* affiancati, uno per asse (piccoli multipli con le
stesse righe). Riga = gruppo, ordinata per posizione sul primo asse. Il punto è
la posizione media, una linea orizzontale l'intervallo di incertezza (dalla
`dispersion`, o meglio un intervallo bootstrap sugli interventi). I due poli
sono scritti per esteso alle estremità dell'asse, in tondo minuscolo, non in
maiuscoletto mono a 9px.

**Perché non il piano 2D**: chiede di leggere distanze in diagonale fra assi
automatici senza unità; con assi correlati (il caso osservato) la seconda
dimensione è finta; i centroidi nascondono la dispersione; il colore dovrebbe
distinguere nove gruppi, e in un grafico a coppie libere nessuna palette ne
regge più di tre. Il dot plot per righe elimina le collisioni e mostra
l'incertezza.

Il piano 2D resta come vista secondaria ("Vedi sul piano") solo se la
correlazione fra le posizioni dei gruppi sui due assi è sotto 0,7 in valore
assoluto, con le sigle scritte e senza colori. Sopra quella soglia la vista dice
"I due assi separano i gruppi nello stesso modo: mostriamo il primo". La soglia
va calibrata, 0,7 è un punto di partenza.

**Codifica**: x = posizione, y = gruppo (ordinato). Punto pieno in inchiostro;
punto vuoto se la base è debole (`n_x` sotto soglia, gli avvisi
`LOW_STANCE_COVERAGE` esistono già). Linea di intervallo `fg-muted` 2px. Zero
come linea sottile continua: "nessuna presa di posizione". Nessun colore di
gruppo. Il gruppo a fuoco passa al colore d'accento in entrambi i pannelli.

**Interazione**: puntatore o focus su una riga evidenzia il gruppo nei due
pannelli e mostra *sotto il grafico*, non in un tooltip, la citazione più
rappresentativa (`core_evidence_ids`) con attribuzione. Frecce su/giù scorrono i
gruppi. Niente pan, niente zoom.

**Mobile**: i due pannelli si impilano; le sigle restano a sinistra, i poli
sopra e sotto ogni asse.

**Non visivo**: tabella gruppo, posizione asse 1, intervallo, posizione asse 2,
interventi su cui poggia; frase di sintesi generata dai dati ("Sul primo asse
FdI, Lega, FI e NM stanno verso 'contrattazione collettiva rafforzata'; PD, M5S
e AVS verso 'soglia minima legale'; IV al centro").

**Dati scarsi**: sotto tre gruppi collocabili niente grafico, solo la tabella e
la frase. Accanto al titolo resta sempre la nota "posizioni stimate da un
modello linguistico" con il link al metodo.

```
                Contrattazione collettiva  ←→  Soglia minima legale
FdI   116  ●━━━━━┥
Lega   64    ●━━┥
NM      9    ○──────┥          (○ = base debole)
FI     44     ━●━
IV      9               ━━●━━
Az     12                          ━●━
PD     69                               ━●━
M5S    51                                ●━
AVS    12                                ━●
           -1             0             +1
[Citazione rappresentativa del gruppo a fuoco, serif, con fonte]
```

## 3. Autorevolezza

**Domanda**: chi conosce questo tema, e perché proprio questa persona?

**Forma**: classifica a *matrice*. Riga = deputato; a sinistra rango, nome,
sigla; poi sei celle, una per criterio, nell'ordine dei pesi (interventi 25%,
commissioni 25%, atti 20%, professione 15%, istruzione 10%, ruolo 5%); a destra
il totale come barra orizzontale con il valore. La cella è una scala sequenziale
a una tinta (chiaro = basso, scuro = alto) del valore grezzo del criterio. Il
peso è scritto nell'intestazione della colonna.

**Perché**: il numero solo non spiega. La matrice mostra il profilo (chi è in
cima perché parla molto, chi per la commissione, chi per il ruolo) senza
aprire nulla.

**Riga espansa**: sei barre allineate con valore grezzo, peso e contributo
(peso × valore), che sommati danno il totale; le evidenze concrete dietro ogni
criterio (quanti interventi, quali atti, quale commissione); il rango nel
gruppo ("2° di 14 in FdI su questo tema") con un mini dot plot dei colleghi di
gruppo, il deputato in accento e gli altri in grigio.

**Interazione**: colonne ordinabili (`aria-sort`), filtri in una riga sopra.

**Mobile**: niente sei colonne. Nome, sigla, totale, e sotto una striscia di sei
celle da 12px con la legenda dei criteri fissa in cima alla lista.

**Non visivo**: è già una tabella; aggiungere i valori nelle celle come testo
nascosto visivamente.

**Dati scarsi**: con meno di cinque deputati la lista resta, la matrice no.
Criterio non disponibile (es. professione ignota): cella tratteggiata a 45°
con etichetta "dato assente", distinto da "zero".

```
                     Interv Comm  Atti  Prof  Istr  Ruolo
                      25%   25%   20%   15%   10%    5%   Totale
 1 Nome Cognome  PD   ████  ███   ██    ░     ██    ░     ━━━━━━━━ 81
 2 Nome Cognome  FdI  ██    ████  ███   ██    ░     ███   ━━━━━━━  74
 3 Nome Cognome  M5S  ███   ██    █     ▨     ██    ░     ━━━━━━   66
                                        ▨ = dato assente
```

## 4. Bilanciamento e copertura

**Domanda**: la risposta ha sentito tutti? Chi manca?

**Forma**: una *striscia di copertura* sotto il titolo della risposta. Una cella
per gruppo, in blocchi per coalizione, ordine per seggi. Cella piena = gruppo
citato, con il numero di citazioni scritto; cella vuota (anello) = trovato ma
non citato; cella barrata = nessun intervento trovato. Accanto, una frase:
"Citati 8 gruppi su 10. Maggioranza 11 citazioni, opposizione 12. Nessun
intervento: Misto-+Europa".

**Perché non il "78%"**: un indice composto non dice chi manca e si legge come
un voto di qualità. Bastano le citazioni per coalizione e l'elenco degli
assenti.

**Interazione**: tocco su una cella porta alla riga del quadro (sezione 1).

**Non visivo**: elenco "Citati: ... Trovati ma non citati: ... Assenti: ...".

**Dati scarsi**: una coalizione a zero citazioni apre la frase.

```
MAGGIORANZA  [FdI 4][Lega 3][FI 2][NM ○]   OPPOSIZIONE [PD 4][M5S 3][AVS 2][Az 2][IV 1]   MISTO [⊘]
Citati 8 gruppi su 10 · maggioranza 9 · opposizione 12 · nessun intervento: +Europa
```

## 5. Voti e coerenza fra detto e votato

**Singolo voto.** Domanda: com'è andata, e chi ha votato in modo diverso dal
proprio gruppo? Forma principale: barra dei totali con la tacca della
maggioranza richiesta, poi una *griglia per gruppo*: una riga per gruppo, un
quadratino per deputato, ordinati per esito, esito come colore + forma. Si
vedono a colpo d'occhio i dissidenti (il quadrato in una riga di cerchi).
L'emiciclo resta come seconda vista "Aula", perché è riconoscibile e condiviso
con Stenografo. Nell'emiciclo i gruppi seguono i settori dell'Aula e la legenda
lo dice ("disposizione dei settori in Aula"); ovunque altrove l'ordine è per
seggi, come vuole la regola di neutralità.

**Voti di un gruppo su un tema.** Matrice: righe = votazioni del tema in ordine
di data, colonne = gruppi. Cella = esito della maggioranza del gruppo (forma +
colore) e, se presenti, il numero di voti difformi in piccolo. Le votazioni
finali in grassetto.

**Storico di un deputato.** Lista di votazioni con due colonne di esito: il suo
e quello del suo gruppo. Le righe dove divergono hanno l'etichetta "diverso dal
gruppo"; un filtro mostra solo quelle. Sopra, un conteggio, non una
percentuale senza base: "Ha votato come il gruppo in 412 votazioni su 431".

**Coerenza.** Per gruppo, una riga a tre colonne: *detto* (direzione stimata
dagli interventi, con la citazione), *votato* (esito sul voto finale),
*lettura* (coincide, diverge, non determinabile). Il "detto" porta sempre la
marca "stimato" perché viene da un modello. Nessun punteggio di coerenza
aggregato: è un giudizio politico travestito da numero.

**Codifica esiti**: quella di Stenografo, invariata. Ho verificato la palette:
favorevole, contrario e astenuto passano la separazione a coppie libere (ΔE
daltonici 8,2 chiaro / 8,0 scuro, visione normale 15,5); la saturazione è
appena sotto la soglia (0,09) e i toni scuri sono più chiari della banda
consigliata. Va bene così perché forma, icona ed etichetta accompagnano sempre
il colore. "Non ha votato" è grigio e si distingue per forma (anello vuoto).

**Mobile**: griglia per gruppo a righe che vanno a capo; matrice dei voti
ruotata (una scheda per votazione con la fila dei gruppi).

**Non visivo**: la tabella nascosta già presente nell'emiciclo; per le matrici,
tabelle vere.

**Dati scarsi**: voto segreto: niente griglia, spiegazione. Nessun voto finale
sul tema: la colonna "votato" dice "nessuna votazione finale nel periodo".

```
Votazione finale · 6 dic 2023 · seduta 211        Respinto (badge neutro)
●●●●●●●●●●●●●■■■■■■■■■■◆○○○○   152 ● · 118 ■ · 3 ◆ · 127 ○   |maggioranza
FdI  ■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■○○○
PD   ●●●●●●●●●●●●●●●●●●●●●●●●●○○
IV   ●●●●◆○        ← il diamante si vede subito
```

## 6. Tempo

**Domanda**: quando se n'è parlato, quando si è deciso, e le posizioni sono
cambiate?

**Forma**: una *traccia del tema* a più corsie con lo stesso asse dei tempi:
1. attenzione: colonne mensili degli interventi (una tinta);
2. momenti: tacche per le votazioni, con forma dell'esito per quelle finali, e
   per le sedute chiave; etichetta diretta solo sulla votazione finale;
3. contesto: bande grigie neutre per i governi (dai dati sulle cariche),
   etichettate col nome;
4. per gruppo (a richiesta): piccoli multipli, una sparkline di interventi per
   gruppo, righe allineate al quadro della sezione 1.

Il cambio di posizione nel tempo (`_direction_by_period`) diventa una fila di
simboli per periodo accanto a ogni gruppo, solo dove la base lo regge. Mai due
scale verticali sullo stesso grafico.

**Legislature**: pannelli affiancati con un'interruzione visibile dell'asse e
l'etichetta della legislatura; i gruppi sono entità per legislatura anche se la
sigla si ripete.

**Interazione**: linea verticale che segue il puntatore e mostra il mese con i
valori di tutte le corsie; selezionare un intervallo filtra il quadro e le
citazioni.

**Mobile**: solo corsie 1 e 2; i gruppi in una lista sotto.

**Non visivo**: tabella mese, interventi, votazioni; frase ("Picco a luglio
2023, mese della votazione sulla mozione").

**Dati scarsi**: sotto sei mesi con dati, niente colonne: solo l'elenco
datato dei momenti.

```
Governo  |░░░░░░░░░░ Governo Meloni ░░░░░░░░░░░░░░░░░░░░░░░|
Interv.  ▁▁▃▁▁▂█▆▂▁▁▁▃▂▁▁▁▂▁▁▁▄▂▁
Voti         |   ■ 6 dic 2023 finale       |  |
         2023                2024              2025
```

## 7. Citazioni e verifica

**Domanda**: chi l'ha detto, quando, dove, e posso controllarlo?

**La citazione come oggetto atomico**, sempre uguale ovunque compaia:
- testo verbatim in Source Serif tra virgolette basse, con "[…]" dove è tagliato;
- attribuzione: nome, sigla del gruppo alla data, ruolo se rilevante;
- provenienza in Geist Mono piccolo: data in italiano, camera, legislatura,
  seduta, titolo del dibattito;
- link "Resoconto ufficiale ↗" alla pagina camera.it;
- stato di verifica come etichetta con icona: "Testo trovato nel resoconto"
  (lo span coincide, `verify` è già un endpoint), "Non verificabile ora"
  (errore o resoconto non raggiungibile). Una citazione che non supera il
  controllo non entra nella risposta;
- contesto: "Mostra contesto" apre la frase prima e quella dopo, con la
  citazione evidenziata.

**In linea o raccolte**: entrambe. Nel testo un marcatore numerato come in
Stenografo; il clic apre il pannello fonte laterale (desktop) o il foglio dal
basso (mobile). Le raccolte stanno nel quadro dei gruppi, non in una lista
piatta di venti schede in fondo. La lista completa resta per chi la vuole,
raggruppata per gruppo.

**Non visivo**: il marcatore ha etichetta "Fonte 3: Nome Cognome, 12 marzo
2024"; il pannello sposta il focus sul titolo e lo restituisce alla chiusura.

```
«Il salario minimo per legge rischia di abbassare i salari [...]»
Nome Cognome · FdI
12 MAR 2024 · CAMERA · XIX · SEDUTA 263 · Disposizioni in materia di...
✓ Testo trovato nel resoconto     Mostra contesto ⌄     Resoconto ufficiale ↗
```

## 8. Progresso della pipeline

**Domanda**: cosa sta succedendo, e manca molto?

**Forma**: i passi reali, come in Stenografo, ma con i *risultati parziali* in
vista. Gli eventi SSE esistono già e arrivano in ordine utile:
1. "Leggo la domanda": commissioni pertinenti (evento `commissioni`);
2. "Cerco negli interventi": numero di evidenze trovate e **la striscia di
   copertura che si riempie** (sezione 4): il lettore vede subito quali gruppi
   hanno parlato del tema;
3. "Valuto chi ne sa di più": i primi nomi (evento `experts`);
4. "Colloco i gruppi" e "Scrivo la risposta", in parallelo come nel backend;
5. "Verifico le citazioni": "18 di 20 verificate".

Ogni passo chiuso resta come ricevuta. Tempo trascorso e una stima onesta
("di solito fra 40 e 70 secondi"), nessuna percentuale inventata. Niente
scheletri per un minuto come oggi in Analisi autorità. `aria-live="polite"`
solo al cambio di passo.

```
✓ Leggo la domanda · Commissione Lavoro
✓ Cerco negli interventi · 132 evidenze
   [FdI][Lega][FI][NM○][PD][M5S][AVS][Az][IV]
✓ Valuto chi ne sa di più · 41 deputati
● Colloco i gruppi · Scrivo la risposta        0:38
○ Verifico le citazioni
```

---

## Grammatica visiva

**Segni**
- Punto 8px (r 4) con anello di 2px nel colore della superficie; area di tocco
  24px su desktop e 44px su touch.
- Linee di intervallo 2px, estremi arrotondati. Barre spesse al massimo 24px,
  estremo arrotondato 4px, base dritta, 2px di stacco fra segmenti.
- Griglie e assi: linea sottile continua, mai tratteggiata.
- Esiti: cerchio, quadrato, diamante, anello, condivisi con Stenografo.
- Tratteggio a 45° solo per "dato assente" e per stampa o `forced-colors`.

**Ruoli di colore** (token semantici, valori già nei token dell'ecosistema)

| Ruolo | Chiaro | Scuro | Uso |
|---|---|---|---|
| Segno di base | ink-700 | `#B4BFB9` | punti, barre, centroidi |
| Contesto | paper-300 | `#2F3D36` | gruppi non a fuoco, bande governo |
| Incertezza | `fg-muted` | `fg-muted` | intervalli |
| Fuoco | accento ParliamentRAG (blu `#4d78a8`, passo testo più scuro) | passo chiaro della stessa scala | gruppo o deputato selezionato |
| Scala | rampa del blu di prodotto, 5 passi chiaro→scuro | stessa rampa, passi scelti per il fondo scuro | matrice autorevolezza, attenzione |
| Esiti | brand-600, `#7568A8`, `#9A7530`, ink-400 | brand-400, `#A79CDB`, `#D2B270`, `#6F7C76` | solo voti |
| Coalizione | nessun colore | nessun colore | blocchi di layout e intestazioni |

Il blu d'accento non compare mai nelle viste di voto come esito, e il verde di
"Favorevole" non compare mai fuori dai voti. Il testo usa sempre i token di
testo, mai il colore di un segno.

**Tipografia nei grafici**: Geist per sigle (semibold) ed etichette; cifre
tabulari solo in colonne e assi; poli degli assi in tondo, frase intera, almeno
12px; Geist Mono solo per date e numeri di seduta; Source Serif solo per le
citazioni. Date sempre in italiano ("28 settembre 2026"), anche nella timeline
dove oggi compaiono in inglese.

**Movimento**: i punti scivolano alla posizione all'arrivo dei dati (320 ms,
curva di ingresso), le barre crescono dalla base, i conteggi salgono come nel
VoteCard. Al cambio di filtro il grafico precedente resta a opacità ridotta
finché arrivano i nuovi dati, senza scheletro. Con movimento ridotto: valori
finali e dissolvenza.

## Posizione sui colori di partito

**Togliere i colori di partito da tutta l'interfaccia, grafici compresi, e non
sostituirli con una palette categoriale neutra.** Le ragioni:

1. **Non funzionano come codice.** Il validatore li boccia su tutti i fronti
   misurabili: blu FdI e azzurro FI, verde Lega e verde AVS si confondono anche
   a vista piena; il giallo M5S è illeggibile su carta.
2. **Una palette neutra non risolve.** I gruppi sono dieci, più delle otto tinte
   che una palette regge, e nelle forme a coppie libere (scatter, mappe) il
   limite pratico è tre. Con il Senato e le legislature passate i gruppi
   crescono. Assegnare una tinta arbitraria a ogni gruppo crea un codice da
   imparare che non porta informazione.
3. **Neutralità.** Il colore di partito è un elemento di identità politica:
   usarlo significa prendere in prestito la comunicazione dei partiti, e i
   gruppi piccoli o del Misto non ne hanno uno riconoscibile, quindi il
   trattamento è diseguale. Rompe anche la regola comune con Stenografo e
   collide con gli esiti (verde Lega accanto a "Favorevole").
4. **Le forme scelte non ne hanno bisogno.** Dot plot per righe, quadro, griglie
   per gruppo e matrici danno a ogni gruppo una riga con la sigla scritta.
   L'identità è testuale e quindi accessibile per costruzione.

Il costo è la riconoscibilità immediata per chi conosce i colori dei partiti.
Lo si recupera con sigle sempre visibili e un ordine stabile delle righe.

## Implementazione

Consiglio **SVG scritto a mano in componenti React**, con le sole utility di
d3 che servono (`d3-scale`, `d3-array`, `d3-shape`, eventualmente
`d3-interpolate`), importate per modulo.

- **recharts**: comodo per linee e barre, ma qui servono dot plot con
  intervalli, griglie di seggi, matrici, emicicli: andrebbe forzato ovunque.
- **visx**: primitive buone, astrazione in più per pochi rettangoli e cerchi.
- **d3 completo**: il DOM lo gestisce React, da d3 servono scale e calcoli.
- **SVG a mano + utility d3**: pochi kB, stile in token Tailwind v4, temi
  gratis, rendering lato server per i grafici statici.

Primitive da costruire una volta: `Axis`, `DotRow` con `Interval`,
`OutcomeGlyph` (già in `timeline/outcomes.tsx`), `SeatGrid`, `HeatCell`,
`CoverageStrip`, `Quote`, `SrTable` (tabella gemella), `ScopeTag`. `Hemicycle`
e `OutcomeShape` vanno allineati con quelli di Stenografo e candidati al
pacchetto condiviso dei token e dei componenti civici.
