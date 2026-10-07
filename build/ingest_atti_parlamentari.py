"""
Script per l'ingestion degli atti parlamentari dalla Camera dei Deputati in Neo4j.

Per ogni deputato della XIX legislatura estrae:
- Atti di cui è primo_firmatario
- Atti di cui è altro_firmatario

Schema Neo4j:
- Nodo: AttoParlamentare
  - uri: URI univoco dell'atto
  - tipo: tipo di atto (es. INTERROGAZIONE A RISPOSTA IN COMMISSIONE)
  - titolo: titolo dell'atto
  - descrizione: descrizione estesa
  - dataPresentazione: data di presentazione (YYYYMMDD)
  - numero: numero dell'atto (es. 5/02533)
  - destinatario: destinatario dell'atto (es. MINISTERO DELLA CULTURA)
  - eurovoc: temi/argomenti dell'atto (classificazione EuroVoc, separati da "; ")

- Relazioni:
  - (Deputato)-[:PRIMO_FIRMATARIO]->(AttoParlamentare)
  - (Deputato)-[:ALTRO_FIRMATARIO]->(AttoParlamentare)
"""

import requests
import time
import csv
import os
from neo4j import GraphDatabase
from typing import Dict, List, Optional

# Configurazione Neo4j
NEO4J_URI = "bolt://localhost:7688"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Endpoint SPARQL
SPARQL_CAMERA = "https://dati.camera.it/sparql"
SPARQL_EUROVOC = "https://publications.europa.eu/webapi/rdf/sparql"

# Rate limiting
REQUEST_DELAY = 0.3  # secondi tra le richieste
CACHE_FILE = "data/eurovoc.csv"


class AttiParlamentariIngester:
    def __init__(self, uri: str, user: str, password: str, legislature: int = 19):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.legislature = legislature
        self.session_requests = requests.Session()
        self.session_requests.headers.update({
            'Accept': 'application/sparql-results+json',
            'User-Agent': 'CameraAttiIngester/1.0'
        })
        # Cache per le label eurovoc (evita query duplicate)
        self.eurovoc_cache: Dict[str, str] = {}
        self.load_cache()
        
        # Circuit breaker per EuroVoc
        self.eurovoc_errors = 0
        self.MAX_EUROVOC_ERRORS = 3
        self.eurovoc_disabled = False

    def load_cache(self):
        """Carica la cache EuroVoc da file CSV."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            self.eurovoc_cache[row[0]] = row[1]
                print(f"Caricati {len(self.eurovoc_cache)} termini EuroVoc dalla cache.")
            except Exception as e:
                print(f"Errore caricamento cache EuroVoc: {e}")

    def save_eurovoc_entry(self, uri: str, label: str):
        """Salva una nuova entry nella cache CSV."""
        try:
            # Assicura che la directory esista
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            
            with open(CACHE_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([uri, label])
        except Exception as e:
            print(f"Errore salvataggio cache EuroVoc: {e}")

    def close(self):
        self.driver.close()
        self.session_requests.close()

    def sparql_query(self, endpoint: str, query: str) -> Optional[Dict]:
        """Esegue una query SPARQL e ritorna i risultati."""
        # Se EuroVoc è disabilitato, salta subito
        if endpoint == SPARQL_EUROVOC and self.eurovoc_disabled:
            return None

        try:
            params = {'query': query}
            if endpoint == SPARQL_EUROVOC:
                params['format'] = 'application/sparql-results+json'
                # Timeout molto breve per EuroVoc (non critico)
                current_timeout = 5
            else:
                params['format'] = 'json'
                # Timeout standard per Camera (dati critici)
                current_timeout = 60

            response = self.session_requests.get(endpoint, params=params, timeout=current_timeout)
            response.raise_for_status()
            
            # Reset contatore errori se successo
            if endpoint == SPARQL_EUROVOC:
                self.eurovoc_errors = 0
                
            return response.json()
        except Exception as e:
            if endpoint == SPARQL_EUROVOC:
                self.eurovoc_errors += 1
                print(f"ATTENZIONE: errore EuroVoc ({self.eurovoc_errors}/{self.MAX_EUROVOC_ERRORS}): {e}")
                if self.eurovoc_errors >= self.MAX_EUROVOC_ERRORS:
                    print("STOP: troppi errori consecutivi su EuroVoc. Disabilito il recupero delle label per questa sessione.")
                    self.eurovoc_disabled = True
            else:
                print(f"ERRORE: query SPARQL fallita ({endpoint}): {e}")
            return None

    def get_eurovoc_label(self, eurovoc_uri: str) -> str:
        """Recupera la label italiana di un termine EuroVoc."""
        if eurovoc_uri in self.eurovoc_cache:
            return self.eurovoc_cache[eurovoc_uri]

        query = f"""
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT ?label WHERE {{
            <{eurovoc_uri}> skos:prefLabel ?label .
            FILTER(LANG(?label) = "it")
        }}
        """

        results = self.sparql_query(SPARQL_EUROVOC, query)

        label = ""
        if results and 'results' in results:
            bindings = results['results'].get('bindings', [])
            if bindings:
                label = bindings[0].get('label', {}).get('value', '')

        self.eurovoc_cache[eurovoc_uri] = label
        self.save_eurovoc_entry(eurovoc_uri, label)
        return label

    def create_constraints(self):
        """Schema v2: il constraint su ParliamentaryAct.uri lo crea db_builder.
        Qui non si creano più constraint sullo schema morto AttoParlamentare (C7)."""
        pass

    def create_indexes(self):
        """Crea indici per performance sullo schema v2 (ParliamentaryAct)."""
        with self.driver.session() as session:
            indexes = [
                "CREATE INDEX act_type IF NOT EXISTS FOR (a:ParliamentaryAct) ON (a.type)",
                "CREATE INDEX act_date IF NOT EXISTS FOR (a:ParliamentaryAct) ON (a.presentation_date)",
                "CREATE INDEX act_recipient IF NOT EXISTS FOR (a:ParliamentaryAct) ON (a.recipient)",
            ]
            for index in indexes:
                try:
                    session.run(index)
                except Exception:
                    pass
            print("Indici ParliamentaryAct creati.")

    def clear_atti_data(self):
        """Rimuove i dati degli atti parlamentari preservando il resto."""
        with self.driver.session() as session:
            session.run("MATCH (n:AttoParlamentare) DETACH DELETE n")
            print("Dati AttoParlamentare rimossi.")

    def get_deputati_xix(self) -> List[Dict]:
        """Recupera tutti i deputati della XIX legislatura dal database Neo4j."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Deputato)
                RETURN d.id as uri, d.nome as nome, d.cognome as cognome
            """)
            return [dict(record) for record in result]

    def get_atti_deputato(self, deputato_uri: str, since: str | None = None) -> Dict[str, List[Dict]]:
        """
        Recupera tutti gli atti di un deputato (primo_firmatario e altro_firmatario).
        Usa dc:subject per eurovoc e ocd:destinatario con rdfs:label per il destinatario.

        since: soglia "YYYYMMDD" su ocd:startDate per l'update incrementale —
        limita la SPARQL agli atti presentati da quella data in poi. Gli atti
        senza startDate passano comunque (mai esclusi per dato mancante).
        """
        # Se l'URI non è completo, costruiscilo.
        # NB: nell'ontologia OCD ocd:primo_firmatario/altro_firmatario puntano
        # alla URI deputato PER LEGISLATURA (deputato.rdf/d<N>_<leg>), NON alla
        # persona (persona.rdf/p<N>). Con la persona la query torna 0 righe
        # (verificato 2026-07-22: p307394 → 0 atti, d307394_19 → 685 atti).
        if not deputato_uri.startswith('http'):
            full_uri = f"http://dati.camera.it/ocd/deputato.rdf/{deputato_uri}"
        elif '/persona.rdf/p' in deputato_uri:
            num = deputato_uri.rsplit('/persona.rdf/p', 1)[1]
            full_uri = (
                f"http://dati.camera.it/ocd/deputato.rdf/d{num}_{self.legislature}"
            )
        else:
            full_uri = deputato_uri

        query = f"""
        PREFIX ocd: <http://dati.camera.it/ocd/>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT DISTINCT ?atto ?tipo ?titolo ?descrizione ?dataPresentazione ?numero
                        ?destinatarioLabel ?ruolo
                        (GROUP_CONCAT(DISTINCT ?eurovocUri; SEPARATOR="|") AS ?eurovocUris)
        WHERE {{
            {{
                ?atto ocd:primo_firmatario <{full_uri}> .
                BIND("primo_firmatario" AS ?ruolo)
            }}
            UNION
            {{
                ?atto ocd:altro_firmatario <{full_uri}> .
                BIND("altro_firmatario" AS ?ruolo)
            }}

            OPTIONAL {{ ?atto dc:type ?tipo }}
            OPTIONAL {{ ?atto dc:title ?titolo }}
            OPTIONAL {{ ?atto dc:description ?descrizione }}
            # Bills (ocd:atto) carry their date in dc:date, oversight acts in ocd:startDate
            OPTIONAL {{ ?atto ocd:startDate ?startDate }}
            OPTIONAL {{ ?atto dc:date ?dcDate }}
            BIND(COALESCE(?startDate, ?dcDate) AS ?dataPresentazione)
            OPTIONAL {{ ?atto dc:identifier ?numero }}
            OPTIONAL {{
                ?atto ocd:destinatario ?destinatario .
                ?destinatario rdfs:label ?destinatarioLabel .
            }}
            OPTIONAL {{
                ?atto dcterms:subject ?eurovocUri .
                FILTER(STRSTARTS(STR(?eurovocUri), "http://eurovoc.europa.eu/"))
            }}
            {f'FILTER(!BOUND(?dataPresentazione) || STR(?dataPresentazione) >= "{since}")' if since else ''}
        }}
        GROUP BY ?atto ?tipo ?titolo ?descrizione ?dataPresentazione ?numero ?destinatarioLabel ?ruolo
        """

        results = self.sparql_query(SPARQL_CAMERA, query)

        atti = {'primo_firmatario': [], 'altro_firmatario': []}

        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            
            # Fase 1: Identifica tutti gli EuroVoc univoci da risolvere
            all_eurovoc_uris = set()
            for binding in bindings:
                uris_str = binding.get('eurovocUris', {}).get('value', '')
                if uris_str:
                    for uri in uris_str.split('|'):
                        if uri:
                            all_eurovoc_uris.add(uri)
            
            # Filtra quelli non in cache
            missing_eurovocs = [u for u in all_eurovoc_uris if u not in self.eurovoc_cache]
            
            # Fase 2: Risolvi i mancanti (sequenziale per rispetto rate limit, ma con log)
            if missing_eurovocs:
                print(f"  [EuroVoc] Risoluzione di {len(missing_eurovocs)} nuovi termini...", end="", flush=True)
                for i, uri in enumerate(missing_eurovocs):
                    self.get_eurovoc_label(uri)
                    time.sleep(REQUEST_DELAY) # Rate limiting
                    if (i + 1) % 10 == 0:
                        print(".", end="", flush=True)
                print(" Fatto.")

            # Fase 3: Costruisci il risultato
            for binding in bindings:
                atto_uri = binding.get('atto', {}).get('value', '')
                ruolo = binding.get('ruolo', {}).get('value', '')

                if not atto_uri or not ruolo:
                    continue

                # Risolvi le label EuroVoc (ora sono in cache).
                # Schema v2 (C10): le URI dei concetti si CONSERVANO — diventano
                # nodi EurovocConcept, non vengono più appiattite a stringa.
                eurovoc_uris_raw = binding.get('eurovocUris', {}).get('value', '')
                eurovoc_concepts = []  # list of {'uri': ..., 'label': ...}
                if eurovoc_uris_raw:
                    for uri in eurovoc_uris_raw.split('|'):
                        if uri:
                            label = self.get_eurovoc_label(uri)
                            if label:
                                eurovoc_concepts.append({'uri': uri, 'label': label})

                atto_data = {
                    'uri': atto_uri,
                    'tipo': binding.get('tipo', {}).get('value', ''),
                    'titolo': binding.get('titolo', {}).get('value', ''),
                    'descrizione': binding.get('descrizione', {}).get('value', ''),
                    'dataPresentazione': binding.get('dataPresentazione', {}).get('value', ''),
                    'numero': binding.get('numero', {}).get('value', ''),
                    'destinatario': binding.get('destinatarioLabel', {}).get('value', ''),
                    'eurovoc_concepts': eurovoc_concepts,
                }

                if ruolo in atti:
                    # Evita duplicati
                    if atto_uri not in [a['uri'] for a in atti[ruolo]]:
                        atti[ruolo].append(atto_data)

        # Aggiungi un piccolo log se nessun atto trovato, per debug
        # else:
        #     print("  (Nessun atto trovato)")

        return atti

    def save_atto_to_neo4j(self, atto: Dict, deputato_uri: str, relazione: str):
        """Salva un atto parlamentare in Neo4j con la relazione al deputato."""
        with self.driver.session() as session:
            params = {
                'uri': atto.get('uri', ''),
                'tipo': atto.get('tipo', ''),
                'titolo': atto.get('titolo', ''),
                'descrizione': atto.get('descrizione', ''),
                'dataPresentazione': atto.get('dataPresentazione', ''),
                'numero': atto.get('numero', ''),
                'destinatario': atto.get('destinatario', ''),
                'eurovoc': atto.get('eurovoc', ''),
            }

            # Crea o aggiorna il nodo AttoParlamentare
            session.run("""
                MERGE (a:AttoParlamentare {uri: $uri})
                SET a.tipo = $tipo,
                    a.titolo = $titolo,
                    a.descrizione = $descrizione,
                    a.dataPresentazione = $dataPresentazione,
                    a.numero = $numero,
                    a.destinatario = $destinatario,
                    a.eurovoc = $eurovoc
            """, **params)

            # Crea la relazione con il deputato
            rel_type = "PRIMO_FIRMATARIO" if relazione == "primo_firmatario" else "ALTRO_FIRMATARIO"

            session.run(f"""
                MATCH (d:Deputato {{id: $deputato_uri}})
                MATCH (a:AttoParlamentare {{uri: $atto_uri}})
                MERGE (d)-[:{rel_type}]->(a)
            """, deputato_uri=deputato_uri, atto_uri=atto['uri'])

    def ingest_all(self):
        """Esegue l'ingestion completa degli atti parlamentari."""
        self.create_constraints()
        self.create_indexes()

        deputati = self.get_deputati_xix()
        print(f"Trovati {len(deputati)} deputati nel database.")

        total_atti_primo = 0
        total_atti_altro = 0
        atti_unici = set()

        for i, dep in enumerate(deputati):
            dep_uri = dep['uri']
            dep_nome = f"{dep.get('nome', '')} {dep.get('cognome', '')}"

            print(f"[{i+1}/{len(deputati)}] Elaborazione {dep_nome}...", end=" ", flush=True)

            atti = self.get_atti_deputato(dep_uri)

            n_primo = len(atti['primo_firmatario'])
            n_altro = len(atti['altro_firmatario'])

            if n_primo > 0 or n_altro > 0:
                print(f"-> {n_primo} primo, {n_altro} altro")
            else:
                print("-> Nessun atto.")

            for atto in atti['primo_firmatario']:
                if atto['uri'] not in atti_unici:
                    atti_unici.add(atto['uri'])
                self.save_atto_to_neo4j(atto, dep_uri, 'primo_firmatario')
                total_atti_primo += 1

            for atto in atti['altro_firmatario']:
                if atto['uri'] not in atti_unici:
                    atti_unici.add(atto['uri'])
                self.save_atto_to_neo4j(atto, dep_uri, 'altro_firmatario')
                total_atti_altro += 1

            if (i + 1) % 50 == 0:
                print(f"Progresso: {i+1}/{len(deputati)} deputati, {len(self.eurovoc_cache)} termini eurovoc in cache")

        return {
            'deputati_processati': len(deputati),
            'atti_primo_firmatario': total_atti_primo,
            'atti_altro_firmatario': total_atti_altro,
            'atti_unici': len(atti_unici)
        }


def main():
    print("=" * 60)
    print("Ingestion Atti Parlamentari - Camera dei Deputati")
    print("XIX Legislatura")
    print("=" * 60)

    ingester = AttiParlamentariIngester(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    try:
        # Decommentare per pulire i dati esistenti
        # ingester.clear_atti_data()

        stats = ingester.ingest_all()

        print("\n" + "=" * 60)
        print("RIEPILOGO FINALE")
        print("=" * 60)
        print(f"Deputati processati:        {stats['deputati_processati']}")
        print(f"Relazioni primo_firmatario: {stats['atti_primo_firmatario']}")
        print(f"Relazioni altro_firmatario: {stats['atti_altro_firmatario']}")
        print(f"Atti unici creati:          {stats['atti_unici']}")
        print("=" * 60)

    finally:
        ingester.close()


if __name__ == "__main__":
    main()
