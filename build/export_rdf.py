"""
RDF export of the ParliamentRAG knowledge graph (schema v2).

Serializes the Neo4j property graph as RDF using the ontology alignment
documented in docs/plans/PLAN_db_schema_v2.md §2.7 (and in the In-Use paper
appendix): OCD, OSR, ELI, FOAF, W3C ORG, SKOS, PROV-O, Dublin Core, plus a
small project namespace for terms with no exact standard equivalent (AKN has
no canonical RDF vocabulary, so the debate structure uses project classes
aligned to Akoma Ntoso element names). Every pr: term is declared in the dump
itself (owl:Class / owl:ObjectProperty / owl:DatatypeProperty with
rdfs:comment, see ONTOLOGY).

Node → RDF mapping:
  Person / Deputy / GovernmentMember  foaf:Person (+ ocd:deputato for deputies,
    / Senator                           osr:Senatore for senators; owl:sameAs
                                        to the dati.camera.it / dati.senato.it
                                        person URI when the node id differs)
  ParliamentaryGroup, Committee,      org:Organization
    Government, MistoComponent          (+ ocd:gruppoParlamentare / ocd:organo)
  ParliamentaryAct                    ocd:atto (+ pr:Bill, pr:Motion, pr:Resolution,
                                        pr:AgendaOrder, pr:OversightAct,
                                        pr:ParliamentaryDocument from the sublabel)
  Amendment                           pr:Amendment (⊑ osr:Emendamento), with its
                                        text from the archive
  Law                                 eli:LegalResource (Normattiva ELI work URI)
                                        eli:is_realized_by the original
                                        eli:LegalExpression; owl:sameAs URN:NIR
  LegislativeProcess                  pr:LegislativeProcess (⊑ prov:Activity);
                                        pr:DocumentProcess for kind 'doc'
  TextVersion                         pr:TextVersion (dati.camera.it URI)
  EurovocConcept                      skos:Concept (canonical EuroVoc URIs),
                                        skos:inScheme EuroVoc
  TeseoConcept                        skos:Concept (TESEO, dati.senato.it/teseo/...),
                                        skos:inScheme prr:scheme/teseo
  Session / Debate / Phase / Speech   pr:Session / pr:Debate / pr:Phase /
                                        pr:Speech (≈ akn:debate,
                                        akn:debateSection, akn:speech)
  Vote                                ocd:votazione
  IndividualVote (--votes only)       ocd:voto
  SchemaMeta                          prov:Activity (build provenance)

Relationship → RDF mapping:
  HAS_DEBATE / HAS_PHASE /            dcterms:hasPart
    CONTAINS_SPEECH
  SPOKEN_BY                           pr:spokenBy (≈ akn:by / ocd:rif_deputato)
  HAS_SUBJECT                         dcterms:subject
  DISCUSSES                           pr:discusses
  PRIMARY_SIGNATORY / CO_SIGNATORY    pr:primarySignatoryOf / pr:coSignatoryOf
  HAS_VOTE                            pr:heldVote
  ON_ACT {inferred}                   pr:onAct (pr:onActInferred when deduced)
  PART_OF {reading}                   dcterms:isPartOf (+ pr:reading on the bill)
  NEXT_READING                        pr:nextReading
  BECAME_LAW                          prov:generated
  HAS_VERSION                         dcterms:hasVersion
  REFERS_TO {version, via}            pr:refersTo (+ pr:refersToVersion,
                                        pr:linkMethod on the agenda order)
  REPORTED_BY {role, source, ...}     pr:reportedBy + reified pr:Rapporteurship
                                        (one per relationship, any source)
  PRESENTED / PRESENTED_BY            pr:presenterOf / pr:presentedBy
  AMENDS {joint}                      pr:amends (pr:amendsJointAct when joint)
  SIGNED_AMENDMENT {first}            pr:primarySignatoryOf / pr:coSignatoryOf
  ON_AMENDMENT                        pr:onAmendment
  SUB_OF / RESUBMITS                  pr:subAmendmentOf / pr:resubmits
  MEMBER_OF_GROUP / _COMMITTEE /      reified org:Membership
    _COMPONENT {start,end}              (org:member / org:organization
                                         + pr:startDate / pr:endDate)
  HOLDS_OFFICE {role,...}             reified org:Post + org:holds
  GOVERNMENT_REFERENCE                pr:governmentReferenceFor
  MENTIONS (chunk -> speech level)    schema:mentions (NER-resolved)
  CITES (chunk -> speech level)       dcterms:references (NER-resolved)
  VOTED / ON_VOTE (--votes only)      ocd:voto with pr:voter / pr:onVote

Chambers: Camera and Senato share one graph. Groups and committees of the
Senate get a `senato-` prefix in their minted URI (the Camera ones keep the
URIs published on Zenodo), because acronyms such as FdI, M5S and Misto exist
in both chambers. Senate speech text is not in Neo4j since 2026-10-13: it is
read from the Postgres text archive (--archive-url or ARCHIVE_URL, see
build/archive_text.py), and the export stops if a chamber is left mostly
without text. Amendment texts are only in that archive too and get the same
check.

Amendment text goes in the dump in full (pr:text): on 2026-10-19 it is 197 MB
over 224k amendments, and a link would not replace it, since the Camera
publishes one XML per bill (388 files) rather than a page per amendment.
--skip-text leaves out both speech and amendment texts.

Deliberately excluded: embeddings (all `*embedding*` properties), Chunk nodes
(retrieval artifacts — Speech keeps the full transcript text), ChatHistory
(private), SpeakerDebateSummary (LLM-derived, not source knowledge).

License: the dataset entity carries dcterms:license CC BY-SA 4.0 (source data
from dati.camera.it is CC BY-SA, so ShareAlike carries over to the derived
graph; dati.senato.it is CC BY 3.0, which allows a CC BY-SA adaptation with
attribution); use the same license on the Zenodo record.

Usage:
    python export_rdf.py [--out DIR] [--format ttl|nt] [--votes] [--skip-text]
                         [--archive-url postgresql://...] [--allow-missing-text]

Connection comes from NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (repo-root .env
is loaded automatically, same convention as the other build scripts).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from neo4j import GraphDatabase
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, ORG, OWL, PROV, RDF, RDFS, SDO, SKOS, XSD

from archive_text import (TextCoverage, archive_url_from_env, load_amendment_texts,
                          load_speech_texts)

REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_DEFAULT = "https://w3id.org/parliamentrag/"
OCD = Namespace("http://dati.camera.it/ocd/")
OSR = Namespace("http://dati.senato.it/osr/")
ELI = Namespace("http://data.europa.eu/eli/ontology#")
EUROVOC_SCHEME = URIRef("http://eurovoc.europa.eu/100141")

# Neo4j sublabels of ParliamentaryAct, each exported as a pr: subclass of ocd:atto
ACT_CLASSES = ("Bill", "Motion", "Resolution", "AgendaOrder", "OversightAct",
               "ParliamentaryDocument")

# Every pr: term the export uses, declared in the dump itself (there is no
# separate ontology file): name -> (kind, comment, parent class or property).
# kind is "class", "object" (links two resources) or "data" (literal value).
ONTOLOGY = {
    "Session": ("class", "A sitting of the Chamber or the Senate (akn:debate).", None),
    "Debate": ("class", "An agenda item discussed in a sitting (akn:debateSection).", None),
    "Phase": ("class", "A phase of a debate, e.g. general discussion (akn:debateSection).", None),
    "Speech": ("class", "A speech in the verbatim record (akn:speech).", None),
    "GovernmentMember": ("class", "A member of the government.", FOAF.Person),
    "Bill": ("class", "A bill (progetto or disegno di legge) in one reading.", OCD.atto),
    "Motion": ("class", "A motion (mozione).", OCD.atto),
    "Resolution": ("class", "A resolution (risoluzione), on the floor or in committee.", OCD.atto),
    "AgendaOrder": ("class", "An order of the day (ordine del giorno) tabled on a bill.", OCD.atto),
    "OversightAct": ("class", "A question or interpellation (sindacato ispettivo).", OCD.atto),
    "ParliamentaryDocument": ("class", "A parliamentary document (Doc., e.g. the DEF or an "
                              "inquiry proposal) debated or voted in a chamber, one per "
                              "chamber.", OCD.atto),
    "Amendment": ("class", "An amendment (emendamento, articolo aggiuntivo, subemendamento, "
                  "or a Senate order of the day filed as amendment G) to the text of an act, "
                  "in committee or on the floor.", OSR.Emendamento),
    "LegislativeProcess": ("class", "The path of a bill through its readings in both houses, "
                           "up to the law when one is published.", PROV.Activity),
    "DocumentProcess": ("class", "The examination of one Government document (DEF, budget "
                        "plan, ...) that both houses receive under the same number; not a "
                        "legislative process, since it ends with resolutions, not a law.",
                        PROV.Activity),
    "TextVersion": ("class", "A version of the text of a bill (as presented, as reported "
                    "by the committee, ...).", None),
    "Rapporteurship": ("class", "A member acting as rapporteur (relatore) on a bill or a "
                       "document, as recorded by one source.", None),
    "spokenBy": ("object", "The member who delivered the speech.", None),
    "discusses": ("object", "An act discussed in the debate.", None),
    "primarySignatoryOf": ("object", "The member is the first signatory of the act or "
                           "amendment.", None),
    "coSignatoryOf": ("object", "The member co-signed the act or amendment.", None),
    "amends": ("object", "The act whose text the amendment changes.", None),
    "amendsJointAct": ("object", "A bill examined jointly with the one the amendment is "
                       "filed on (abbinato).", None),
    "onAmendment": ("object", "The amendment a floor roll-call vote is on, matched from the "
                    "vote description and the sitting.", None),
    "subAmendmentOf": ("object", "The amendment this sub-amendment changes.", None),
    "resubmits": ("object", "The first amendment with the same text and signatories on the "
                  "same act: this one files it again in another venue or sitting.", None),
    "textFile": ("object", "Official file (PDF) with the text of the document or of one of "
                 "its parts.", None),
    "presenterOf": ("object", "The person presented the bill on behalf of the government.", None),
    "presentedBy": ("object", "The government that presented the bill.", None),
    "heldVote": ("object", "A roll-call vote held in the sitting.", None),
    "governmentReferenceFor": ("object", "The government member is the reference for the committee.", None),
    "onAct": ("object", "The act the roll-call vote is on, as stated by the source.", None),
    "onActInferred": ("object", "The act of a vote on an amendment or article, deduced from the "
                      "nearest vote of the sitting that names its bill; not stated by the source.", None),
    "nextReading": ("object", "The bill of the next reading of the same legislative process "
                    "(e.g. C.2822 -> S.1971 -> C.2822-B).", None),
    "refersTo": ("object", "The bill an order of the day was tabled on.", DCTERMS.relation),
    "reportedBy": ("object", "A rapporteur of the bill or document (see pr:Rapporteurship "
                   "for the details).", None),
    "reportedAct": ("object", "The bill or document of the rapporteurship.", None),
    "rapporteur": ("object", "The member acting as rapporteur.", None),
    "voter": ("object", "The member who cast the individual vote.", None),
    "onVote": ("object", "The roll-call vote the individual vote belongs to.", None),
    "outcomeEvidence": ("object", "Official page the outcome of the act was read from.", None),
    "text": ("data", "Full text of the speech or of the amendment.", None),
    "number": ("data", "Number of the sitting or of the vote.", None),
    "article": ("data", "Article of the act the amendment refers to, as numbered by the "
                "source.", None),
    "amendmentVersion": ("data", "Revision of the amendment's own text as labelled by the "
                         "source (testo 2, testo corretto, ...).", None),
    "sittingDate": ("data", "Date of the sitting whose amendment file lists the amendment "
                    "(Camera).", None),
    "docSeries": ("data", "Series of a parliamentary document in Roman numerals (e.g. XXII, "
                  "inquiry proposals).", None),
    "documentType": ("data", "Description of the document series as written by the source.",
                     None),
    "initiative": ("data", "Who presented the act (governo, parlamentare, commissione, "
                   "ente, ...).", None),
    "titleSource": ("data", "Where the title of the document was read from: camera, senato "
                    "(the other chamber's record) or dibattito (the debate title).", None),
    "chamber": ("data", "House: camera or senato.", None),
    "legislature": ("data", "Legislature number.", None),
    "order": ("data", "Position within the parent resource.", None),
    "phaseType": ("data", "Kind of debate phase.", None),
    "subject": ("data", "Readable subject of a vote, motion or resolution, from the official "
                "record (debate title or vote label), never generated text.", None),
    "subjectSource": ("data", "Where pr:subject was read from (debate, vote, fallback).", None),
    "voteType": ("data", "Kind of roll-call vote.", None),
    "outcome": ("data", "Outcome, always in Italian: of an act or amendment (approvato, "
                "respinto, accolto, ritirato, precluso, inammissibile, ...), of a roll-call vote "
                "(approvato, respinto) or of an individual vote (favorevole, contrario, astenuto, "
                "assente, segreto).", None),
    "outcomeSource": ("data", "Where the outcome comes from. Acts: voto (roll-call votes on "
                      "it) or esito_senato (the Senate outcome of the amendment G). "
                      "Amendments: fonte (published by the chamber) or voto_aula (result "
                      "of the floor roll-call vote on it, when the chamber publishes no "
                      "outcome).", None),
    "outcomeRaw": ("data", "Outcome of the act or amendment as written by the source.", None),
    "voters": ("data", "Members voting.", None),
    "present": ("data", "Members present.", None),
    "inFavor": ("data", "Votes in favour.", None),
    "against": ("data", "Votes against.", None),
    "abstained": ("data", "Abstentions.", None),
    "onMission": ("data", "Members on mission.", None),
    "majority": ("data", "Majority required.", None),
    "profession": ("data", "Profession of the member.", None),
    "education": ("data", "Education of the member.", None),
    "institutionalRole": ("data", "Institutional role of the member.", None),
    "mandateStart": ("data", "Start of the current mandate.", None),
    "startDate": ("data", "Start date.", None),
    "endDate": ("data", "End date.", None),
    "role": ("data", "Role held (office in a group or committee, government post, "
             "kind of rapporteur).", None),
    "roleStart": ("data", "Start date of the role.", None),
    "roleEnd": ("data", "End date of the role.", None),
    "roleRaw": ("data", "Role as written by the source.", None),
    "officeType": ("data", "Kind of government office.", None),
    "actKind": ("data", "Normalized kind of act (pdl_ordinaria, mozione, odg_assemblea, ...).", None),
    "status": ("data", "Procedural status of the act according to the source.", None),
    "reading": ("data", "Position of the bill among the readings of its legislative process.", None),
    "refersToVersion": ("data", "Text version of the bill the order of the day refers to "
                        "(e.g. A).", None),
    "linkMethod": ("data", "How the link was established: numero (bill number in the act) "
                   "or uri (official link).", None),
    "versionLabel": ("data", "Short label of the text version (A, TU, AR, ...).", None),
    "lawKind": ("data", "Kind of law: legge or legge_costituzionale.", None),
    "gazetteNumber": ("data", "Number of the Gazzetta Ufficiale issue that published the law.", None),
    "gazetteSupplement": ("data", "Supplement of the Gazzetta Ufficiale issue.", None),
    "committeeName": ("data", "Committee named by the source, as written.", None),
    "venue": ("data", "Where the rapporteur reports or the amendment is filed: commissione "
              "or assemblea.", None),
    "source": ("data", "Source the statement was taken from (dati.camera.it, dati.senato.it, "
               "scheda_camera, resoconto, ...).", None),
    "buildToolCommit": ("data", "Commit of the code that built the graph.", None),
    "schemaVersion": ("data", "Version of the graph schema.", None),
}

SOURCE_BY_CHAMBER = {
    "camera": ("http://dati.camera.it", "Camera dei deputati"),
    "senato": ("http://dati.senato.it", "Senato della Repubblica"),
}

# Filtered inside the query (see node_rows), not client-side: the vectors are
# ~1536 floats per node and streaming them over the SSH tunnel only to drop them
# made the export take minutes per label and drop the connection.
EXCLUDED_PROP = "embedding"

# The graph keeps amendment, roll-call and individual-vote outcomes as English
# codes; the dump publishes every outcome in Italian, like the acts and the
# sources (Mirko, 19/10/2026). Values not listed here pass through unchanged.
OUTCOME_IT = {
    "approved": "approvato", "rejected": "respinto", "withdrawn": "ritirato",
    "precluded": "precluso", "inadmissible": "inammissibile", "accepted": "accolto",
    "not_accepted": "non_accolto", "accepted_as_recommendation": "accolto_come_raccomandazione",
    "lapsed": "decaduto", "absorbed": "assorbito", "identical": "identico",
    "superseded": "rinvio_ad_altro", "not_voted": "non_posto_in_votazione",
    "mixed": "approvato_in_parte", "other": "altro",
    "favor": "favorevole", "against": "contrario", "abstain": "astenuto",
    "absent": "assente", "secret": "segreto",
}
OUTCOME_SOURCE_IT = {"source": "fonte", "floor_vote": "voto_aula"}


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-") + "-" + hashlib.md5(text.encode()).hexdigest()[:8]
    return slug


def chamber_of_speech(speech_id: str) -> str:
    """Chamber of a Speech node from its id (Senate ids start with `sen_`)."""
    return "senato" if speech_id.startswith("sen_") else "camera"


def org_slug(props: dict, use_acronym: bool) -> str:
    """Local id of a group or committee URI, chamber-qualified for the Senate."""
    label = (props.get("acronym") if use_acronym else None) or props["name"]
    slug = slugify(label)
    return f"senato-{slug}" if props.get("chamber") == "senato" else slug


def act_local_id(props: dict) -> str:
    """Local id of an act with no http URI.

    Camera placeholders keep the number-based id already on Zenodo; Senate
    acts and the documents of both chambers use their full id
    (`senato:19:...`, `camera:19:doc:XXII:31`), since bare numbers repeat
    across chambers and document series.
    """
    source_uri = props.get("uri", "")
    if props.get("chamber") == "senato" or props.get("kind") == "doc":
        return source_uri
    return str(props.get("number") or source_uri)


def law_uris(props: dict) -> tuple[URIRef, URIRef | None]:
    """ELI work URI of a law and, when known, the URI of its original expression."""
    eli = props.get("eli") or ""
    if eli.startswith("http"):
        work = eli[: -len("/ORIGINAL")] if eli.endswith("/ORIGINAL") else eli
        return URIRef(work), (URIRef(eli) if eli != work else None)
    return URIRef(props["urn"]), None


class RdfExporter:
    def __init__(self, driver, base: str, include_text: bool,
                 archive_texts: dict | None = None,
                 amendment_texts: dict | None = None):
        self.driver = driver
        self.include_text = include_text
        self.archive_texts = archive_texts or {}
        self.amendment_texts = amendment_texts or {}
        self.text_coverage = TextCoverage()
        self.amendment_text_coverage = TextCoverage(unit="amendments")
        self.amendment_count = 0
        self.chambers = set()
        self.PRO = Namespace(base + "ontology#")   # classes and properties
        self.PRR = Namespace(base + "resource/")   # minted entity URIs
        self.g = Graph()
        for prefix, ns in [("ocd", OCD), ("foaf", FOAF), ("org", ORG),
                           ("skos", SKOS), ("dcterms", DCTERMS), ("prov", PROV),
                           ("schema", SDO), ("osr", OSR), ("owl", OWL),
                           ("eli", ELI), ("rdfs", RDFS),
                           ("pr", self.PRO), ("prr", self.PRR)]:
            self.g.bind(prefix, ns)
        self.uri_by_eid = {}  # Neo4j elementId -> URIRef, filled by node passes

    def mint(self, kind: str, local_id: str) -> URIRef:
        return self.PRR[f"{kind}/{quote(str(local_id), safe='')}"]

    def rows(self, cypher: str):
        with self.driver.session() as session:
            yield from session.run(cypher)

    def node_rows(self, label: str):
        """Nodes of one label as {eid, labels, n}, with n's embedding props dropped server-side."""
        cypher = (
            f"MATCH (n:`{label}`) RETURN elementId(n) AS eid, labels(n) AS labels, "
            f"[k IN keys(n) WHERE NOT toLower(k) CONTAINS '{EXCLUDED_PROP}' | [k, n[k]]] AS kv"
        )
        for rec in self.rows(cypher):
            yield {"eid": rec["eid"], "labels": rec["labels"], "n": dict(rec["kv"])}

    @staticmethod
    def to_literal(value):
        # neo4j.time.Date/DateTime expose isoformat(); plain types map directly
        type_name = type(value).__name__
        if type_name == "Date":
            return Literal(value.iso_format(), datatype=XSD.date)
        if type_name == "DateTime":
            return Literal(value.iso_format(), datatype=XSD.dateTime)
        if isinstance(value, bool):
            return Literal(value)
        if isinstance(value, int):
            return Literal(value, datatype=XSD.integer)
        if isinstance(value, float):
            return Literal(value, datatype=XSD.double)
        return Literal(str(value))

    def add_props(self, subject: URIRef, props: dict, mapping: dict):
        """Emit one triple per (property, predicate) pair present in props."""
        for key, predicate in mapping.items():
            value = props.get(key)
            if value is None or value == "":
                continue
            if predicate == self.PRO.outcome:
                value = OUTCOME_IT.get(value, value)
            elif predicate == self.PRO.outcomeSource:
                value = OUTCOME_SOURCE_IT.get(value, value)
            self.g.add((subject, predicate, self.to_literal(value)))

    # ---- node passes -------------------------------------------------------

    def export_people(self):
        PRO = self.PRO
        for rec in self.node_rows("Person"):
            props = dict(rec["n"])
            node_id = props["id"]
            uri = URIRef(node_id) if node_id.startswith("http") else self.mint("person", node_id)
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, FOAF.Person))
            if "Deputy" in rec["labels"]:
                self.g.add((uri, RDF.type, OCD.deputato))
            if "Senator" in rec["labels"]:
                self.g.add((uri, RDF.type, OSR.Senatore))
            if "GovernmentMember" in rec["labels"]:
                self.g.add((uri, RDF.type, PRO.GovernmentMember))
            for key in ("camera_id", "senato_id"):
                official = props.get(key)
                if isinstance(official, str) and official.startswith("http") and official != node_id:
                    self.g.add((uri, OWL.sameAs, URIRef(official)))
            self.add_props(uri, props, {
                "first_name": FOAF.givenName,
                "last_name": FOAF.familyName,
                "gender": FOAF.gender,
                "deputy_card": DCTERMS.identifier,
                "profession": PRO.profession,
                "education": PRO.education,
                "institutional_role": PRO.institutionalRole,
                "term_of_office_start": PRO.mandateStart,
            })
            if props.get("photo"):
                self.g.add((uri, FOAF.img, URIRef(props["photo"])))
            if props.get("term_of_office"):
                self.g.add((uri, OCD.rif_mandatoCamera, URIRef(props["term_of_office"])))

    def export_organizations(self):
        PRO = self.PRO
        for rec in self.node_rows("ParliamentaryGroup"):
            props = dict(rec["n"])
            uri = self.mint("group", org_slug(props, use_acronym=True))
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, ORG.Organization))
            self.g.add((uri, RDF.type, OCD.gruppoParlamentare))
            self.g.add((uri, SKOS.prefLabel, Literal(props["name"], lang="it")))
            if props.get("acronym"):
                self.g.add((uri, SKOS.altLabel, Literal(props["acronym"])))

        for rec in self.node_rows("Committee"):
            props = dict(rec["n"])
            uri = self.mint("committee", org_slug(props, use_acronym=False))
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, ORG.Organization))
            self.g.add((uri, RDF.type, OCD.organo))
            self.g.add((uri, SKOS.prefLabel, Literal(props["name"], lang="it")))

        for rec in self.node_rows("MistoComponent"):
            props = dict(rec["n"])
            uri = URIRef(props["uri"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, ORG.Organization))
            self.g.add((uri, SKOS.prefLabel, Literal(props["name"], lang="it")))
            if props.get("short_name"):
                self.g.add((uri, SKOS.altLabel, Literal(props["short_name"])))

        for rec in self.node_rows("Government"):
            props = dict(rec["n"])
            uri = self.mint("government", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, ORG.Organization))
            self.g.add((uri, SKOS.prefLabel, Literal(props["name"], lang="it")))
            self.add_props(uri, props, {"start_date": PRO.startDate})

    def export_acts_and_subjects(self):
        PRO = self.PRO
        for rec in self.node_rows("ParliamentaryAct"):
            props = dict(rec["n"])
            source_uri = props.get("uri", "")
            if source_uri.startswith("http"):
                uri = URIRef(source_uri)
            else:  # placeholder and Senate non-bill acts have no http URI
                uri = self.mint("act", act_local_id(props))
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, OCD.atto))
            for label in rec["labels"]:
                if label in ACT_CLASSES:
                    self.g.add((uri, RDF.type, PRO[label]))
            self.add_props(uri, props, {
                "number": DCTERMS.identifier,
                "type": DCTERMS.type,
                "kind": PRO.actKind,
                "title": DCTERMS.title,
                "presentation_date": DCTERMS.date,
                "chamber": PRO.chamber,
                "status": PRO.status,
                "subject": PRO.subject,
                "subject_source": PRO.subjectSource,
                "outcome": PRO.outcome,
                "outcome_source": PRO.outcomeSource,
                "outcome_raw": PRO.outcomeRaw,
                "initiative": PRO.initiative,
                "name": RDFS.label,
                "doc_series": PRO.docSeries,
                "doc_type_raw": PRO.documentType,
                "title_source": PRO.titleSource,
            })
            for key in ("source_page", "senato_url", "url", "outcome_url"):
                self.add_link(uri, PRO.outcomeEvidence if key == "outcome_url" else FOAF.page,
                              props.get(key))
            for url in props.get("text_urls") or []:
                self.add_link(uri, PRO.textFile, url)
            for official in props.get("official_uris") or []:
                if isinstance(official, str) and official.startswith("http") and official != str(uri):
                    self.g.add((uri, OWL.sameAs, URIRef(official)))

        for label, scheme in (("EurovocConcept", EUROVOC_SCHEME),
                              ("TeseoConcept", self.PRR["scheme/teseo"])):
            for rec in self.node_rows(label):
                props = dict(rec["n"])
                uri = URIRef(props["uri"])
                self.uri_by_eid[rec["eid"]] = uri
                self.g.add((uri, RDF.type, SKOS.Concept))
                self.g.add((uri, SKOS.inScheme, scheme))
                if props.get("label_it"):
                    self.g.add((uri, SKOS.prefLabel, Literal(props["label_it"], lang="it")))
        self.export_concept_schemes()

    def export_concept_schemes(self):
        """Declare the two subject thesauri the acts are indexed with."""
        teseo = self.PRR["scheme/teseo"]
        self.g.add((teseo, RDF.type, SKOS.ConceptScheme))
        self.g.add((teseo, SKOS.prefLabel, Literal("TESEO", lang="it")))
        self.g.add((teseo, DCTERMS.publisher, Literal("Senato della Repubblica", lang="it")))
        # dati.senato.it publishes the TESEO concepts but no ConceptScheme
        # resource (checked on its SPARQL endpoint, 2026-10-19), so the scheme
        # URI is minted here and points to the source.
        self.g.add((teseo, DCTERMS.source, URIRef("http://dati.senato.it")))
        self.g.add((EUROVOC_SCHEME, RDF.type, SKOS.ConceptScheme))
        self.g.add((EUROVOC_SCHEME, SKOS.prefLabel, Literal("EuroVoc", lang="en")))

    def add_link(self, subject: URIRef, predicate: URIRef, url):
        if isinstance(url, str) and url.startswith("http"):
            self.g.add((subject, predicate, URIRef(url)))

    def export_amendments(self):
        """Amendments with their number, outcome and, from the archive, their text."""
        PRO = self.PRO
        for rec in self.node_rows("Amendment"):
            props = dict(rec["n"])
            uri = self.mint("amendment", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.Amendment))
            self.amendment_count += 1
            self.add_props(uri, props, {
                "number": DCTERMS.identifier,
                "kind": DCTERMS.type,
                "chamber": PRO.chamber,
                "legislature": PRO.legislature,
                "venue": PRO.venue,
                "committee": PRO.committeeName,
                "article": PRO.article,
                "version": PRO.amendmentVersion,
                "presented_on": DCTERMS.dateSubmitted,
                "sitting_date": PRO.sittingDate,
                "outcome": PRO.outcome,
                "outcome_source": PRO.outcomeSource,
                "outcome_raw": PRO.outcomeRaw,
            })
            self.add_link(uri, FOAF.page, props.get("source_url"))
            if not self.include_text:
                continue
            # pop: each id is read once and the 197 MB of texts (2026-10-19)
            # are released as the rdflib literals take their place
            text = self.amendment_texts.pop(props["id"], None)
            self.amendment_text_coverage.add(props.get("chamber"), bool(text))
            if text:
                self.g.add((uri, PRO.text, Literal(text, lang="it")))

    def export_legislation(self):
        """Laws (ELI), legislative processes and the text versions of bills.

        A Law node is the work published in the Gazzetta Ufficiale; its `eli`
        property is Normattiva's ELI of the original expression
        (`.../{code}/ORIGINAL`). The work URI is that ELI without the version
        segment, which Normattiva resolves (302 to the consolidated text,
        checked 2026-10-19).
        """
        PRO = self.PRO
        for rec in self.node_rows("Law"):
            props = dict(rec["n"])
            work, expression = law_uris(props)
            self.uri_by_eid[rec["eid"]] = work
            self.g.add((work, RDF.type, ELI.LegalResource))
            self.add_props(work, props, {
                "number": ELI.number,
                "code": ELI.id_local,
                "date": ELI.date_document,
                "gu_date": ELI.date_publication,
                "gu_number": PRO.gazetteNumber,
                "gu_supplement": PRO.gazetteSupplement,
                "kind": PRO.lawKind,
                "title": DCTERMS.title,
                "legislature": PRO.legislature,
            })
            if props.get("urn"):
                self.g.add((work, OWL.sameAs, URIRef(props["urn"])))
            self.add_link(work, RDFS.seeAlso, props.get("normattiva_url"))
            if expression is not None:
                self.g.add((work, ELI.is_realized_by, expression))
                self.g.add((expression, RDF.type, ELI.LegalExpression))
                if props.get("title"):
                    self.g.add((expression, ELI.title, Literal(props["title"], lang="it")))

        for rec in self.node_rows("LegislativeProcess"):
            props = dict(rec["n"])
            uri = self.mint("process", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            # ingest_documents.py stores the Government documents both chambers
            # receive as LegislativeProcess nodes with kind 'doc'
            kind = PRO.DocumentProcess if props.get("kind") == "doc" else PRO.LegislativeProcess
            self.g.add((uri, RDF.type, kind))
            self.add_props(uri, props, {"title": DCTERMS.title, "legislature": PRO.legislature})

        for rec in self.node_rows("TextVersion"):
            props = dict(rec["n"])
            node_id = props["id"]
            uri = URIRef(node_id) if node_id.startswith("http") else self.mint("text", node_id)
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.TextVersion))
            self.add_props(uri, props, {
                "code": DCTERMS.identifier,
                "title": DCTERMS.title,
                "date": DCTERMS.date,
                "label": PRO.versionLabel,
            })
            self.add_link(uri, FOAF.page, props.get("url"))

    def export_proceedings(self):
        PRO = self.PRO
        for rec in self.node_rows("Session"):
            props = dict(rec["n"])
            uri = self.mint("session", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.Session))
            self.add_props(uri, props, {
                "date": DCTERMS.date,
                "number": PRO.number,
                "chamber": PRO.chamber,
                "legislature": PRO.legislature,
            })
            if props.get("chamber"):
                self.chambers.add(props["chamber"])

        for rec in self.node_rows("Debate"):
            props = dict(rec["n"])
            uri = self.mint("debate", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.Debate))
            self.add_props(uri, props, {"title": DCTERMS.title, "order": PRO.order})

        for rec in self.node_rows("Phase"):
            props = dict(rec["n"])
            uri = self.mint("phase", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.Phase))
            self.add_props(uri, props, {
                "title": DCTERMS.title,
                "order": PRO.order,
                "phaseType": PRO.phaseType,
            })

        for rec in self.node_rows("Speech"):
            props = dict(rec["n"])
            uri = self.mint("speech", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, PRO.Speech))
            if not self.include_text:
                continue
            text = props.get("text") or self.archive_texts.get(props["id"])
            self.text_coverage.add(chamber_of_speech(props["id"]), bool(text))
            if text:
                self.g.add((uri, PRO.text, Literal(text, lang="it")))

        for rec in self.node_rows("Vote"):
            props = dict(rec["n"])
            uri = self.mint("vote", props["id"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, OCD.votazione))
            self.add_props(uri, props, {
                "number": PRO.number,
                "subject": PRO.subject,
                "type": PRO.voteType,
                "outcome": PRO.outcome,
                "voters": PRO.voters,
                "present": PRO.present,
                "inFavor": PRO.inFavor,
                "against": PRO.against,
                "abstained": PRO.abstained,
                "onMission": PRO.onMission,
                "majority": PRO.majority,
            })

    def export_provenance(self):
        PRO = self.PRO
        dataset = self.PRR["dataset"]
        chambers = [c for c in SOURCE_BY_CHAMBER if c in self.chambers] or ["camera"]
        scope = ("Italian Parliament" if len(chambers) > 1
                 else "Italian Chamber of Deputies" if chambers == ["camera"]
                 else "Italian Senate")
        self.g.add((dataset, RDF.type, PROV.Entity))
        self.g.add((dataset, DCTERMS.title,
                    Literal(f"ParliamentRAG knowledge graph ({scope}, leg. 19)", lang="en")))
        # CC BY-SA 4.0: dati.camera.it is CC BY-SA, ShareAlike carries over;
        # dati.senato.it is CC BY 3.0, compatible with a BY-SA adaptation
        self.g.add((dataset, DCTERMS.license,
                    URIRef("https://creativecommons.org/licenses/by-sa/4.0/")))
        for chamber in chambers:
            self.g.add((dataset, DCTERMS.source, URIRef(SOURCE_BY_CHAMBER[chamber][0])))
        if any(True for _ in self.g.subjects(RDF.type, ELI.LegalResource)):
            self.g.add((dataset, DCTERMS.source, URIRef("https://www.normattiva.it")))
        holders = ", ".join(SOURCE_BY_CHAMBER[c][1] for c in chambers)
        self.g.add((dataset, DCTERMS.rightsHolder,
                    Literal(f"{holders} (source data); ParliamentRAG (derived graph)", lang="en")))

        meta = None
        for rec in self.node_rows("SchemaMeta"):
            meta = dict(rec["n"])
        if not meta:
            return
        activity = self.mint("build", meta.get("id", "singleton"))
        self.g.add((activity, RDF.type, PROV.Activity))
        for source in meta.get("source_datasets", []):
            self.g.add((activity, PROV.used, URIRef(source)))
        if meta.get("built_at"):
            self.g.add((activity, PROV.endedAtTime, self.to_literal(meta["built_at"])))
        self.add_props(activity, meta, {
            "build_tool_commit": PRO.buildToolCommit,
            "version": PRO.schemaVersion,
        })
        self.g.add((dataset, PROV.wasGeneratedBy, activity))

    def export_ontology(self):
        """Declare the pr: terms (ONTOLOGY) so the dump documents its own vocabulary."""
        ontology = URIRef(str(self.PRO).rstrip("#"))
        self.g.add((ontology, RDF.type, OWL.Ontology))
        self.g.add((ontology, RDFS.label, Literal("ParliamentRAG ontology", lang="en")))
        self.g.add((ontology, RDFS.comment, Literal(
            "Terms with no exact equivalent in OCD, OSR, ELI, FOAF, W3C ORG, SKOS, "
            "PROV-O or Dublin Core.", lang="en")))
        kinds = {"class": OWL.Class, "object": OWL.ObjectProperty, "data": OWL.DatatypeProperty}
        for name, (kind, comment, parent) in ONTOLOGY.items():
            term = self.PRO[name]
            self.g.add((term, RDF.type, kinds[kind]))
            self.g.add((term, RDFS.label, Literal(name, lang="en")))
            self.g.add((term, RDFS.comment, Literal(comment, lang="en")))
            self.g.add((term, RDFS.isDefinedBy, ontology))
            if parent is not None:
                self.g.add((term, RDFS.subClassOf if kind == "class" else RDFS.subPropertyOf,
                            parent))

    # ---- relationship passes ----------------------------------------------

    def export_simple_relationships(self):
        PRO = self.PRO
        predicate_by_rel = {
            "HAS_DEBATE": DCTERMS.hasPart,
            "HAS_PHASE": DCTERMS.hasPart,
            "CONTAINS_SPEECH": DCTERMS.hasPart,
            "SPOKEN_BY": PRO.spokenBy,
            "HAS_SUBJECT": DCTERMS.subject,
            "DISCUSSES": PRO.discusses,
            "PRIMARY_SIGNATORY": PRO.primarySignatoryOf,
            "CO_SIGNATORY": PRO.coSignatoryOf,
            "HAS_VOTE": PRO.heldVote,
            "GOVERNMENT_REFERENCE": PRO.governmentReferenceFor,
            "HAS_VERSION": DCTERMS.hasVersion,
            "NEXT_READING": PRO.nextReading,
            "BECAME_LAW": PROV.generated,
            "PRESENTED": PRO.presenterOf,
            "PRESENTED_BY": PRO.presentedBy,
        }
        for rel_type, predicate in predicate_by_rel.items():
            count = 0
            for rec in self.rows(
                f"MATCH (a)-[r:`{rel_type}`]->(b) "
                "RETURN elementId(a) AS a, elementId(b) AS b"
            ):
                subject = self.uri_by_eid.get(rec["a"])
                obj = self.uri_by_eid.get(rec["b"])
                if subject is None or obj is None:
                    continue
                self.g.add((subject, predicate, obj))
                count += 1
            print(f"  {rel_type}: {count}")

    def export_mentions_citations(self):
        """NER-resolved MENTIONS/CITES, lifted from Chunk to Speech level.

        Chunks are deliberately not part of the dump, so the chunk-level
        relationships are aggregated onto the parent Speech (DISTINCT pairs):
        schema:mentions towards persons, dcterms:references towards acts.
        """
        for rel_type, predicate in (
            ("MENTIONS", SDO.mentions),
            ("CITES", DCTERMS.references),
        ):
            count = 0
            for rec in self.rows(
                f"MATCH (sp:Speech)-[:HAS_CHUNK]->(:Chunk)-[:`{rel_type}`]->(t) "
                "RETURN DISTINCT elementId(sp) AS a, elementId(t) AS b"
            ):
                subject = self.uri_by_eid.get(rec["a"])
                obj = self.uri_by_eid.get(rec["b"])
                if subject is None or obj is None:
                    continue
                self.g.add((subject, predicate, obj))
                count += 1
            print(f"  {rel_type} (speech-level): {count}")

    def export_memberships(self):
        """MEMBER_OF_* {start,end} → reified org:Membership (W3C ORG)."""
        PRO = self.PRO
        for rel_type in ("MEMBER_OF_GROUP", "MEMBER_OF_COMMITTEE", "MEMBER_OF_COMPONENT"):
            count = 0
            for rec in self.rows(
                f"MATCH (a)-[r:`{rel_type}`]->(b) "
                "RETURN elementId(a) AS a, elementId(b) AS b, r"
            ):
                person = self.uri_by_eid.get(rec["a"])
                organization = self.uri_by_eid.get(rec["b"])
                if person is None or organization is None:
                    continue
                props = dict(rec["r"])
                start = props.get("start_date")
                local = (f"{person.rsplit('/', 1)[-1]}_{organization.rsplit('/', 1)[-1]}"
                         f"_{start.iso_format() if start else 'na'}")
                membership = self.mint("membership", local)
                self.g.add((membership, RDF.type, ORG.Membership))
                self.g.add((membership, ORG.member, person))
                self.g.add((membership, ORG.organization, organization))
                self.add_props(membership, props, {
                    "chamber": PRO.chamber,
                    "start_date": PRO.startDate,
                    "end_date": PRO.endDate,
                    "officerRole": PRO.role,
                    "officerRoleStart": PRO.roleStart,
                    "officerRoleEnd": PRO.roleEnd,
                    "role": PRO.role,
                })
                count += 1
            print(f"  {rel_type}: {count}")

    def export_offices(self):
        """HOLDS_OFFICE {role, office_type, start} → reified org:Post."""
        PRO = self.PRO
        count = 0
        for rec in self.rows(
            "MATCH (a)-[r:HOLDS_OFFICE]->(b) "
            "RETURN elementId(a) AS a, elementId(b) AS b, r"
        ):
            person = self.uri_by_eid.get(rec["a"])
            government = self.uri_by_eid.get(rec["b"])
            if person is None or government is None:
                continue
            props = dict(rec["r"])
            post = self.mint("post", f"{person.rsplit('/', 1)[-1]}_{slugify(props.get('role', 'post'))}")
            self.g.add((post, RDF.type, ORG.Post))
            self.g.add((post, ORG.postIn, government))
            self.g.add((person, ORG.holds, post))
            self.add_props(post, props, {
                "role": PRO.role,
                "office_type": PRO.officeType,
                "start_date": PRO.startDate,
                "end_date": PRO.endDate,
            })
            count += 1
        print(f"  HOLDS_OFFICE: {count}")

    def rel_rows(self, rel_type: str):
        """Relationships of one type as (subject URI, object URI, properties), mapped ends only."""
        for rec in self.rows(
            f"MATCH (a)-[r:`{rel_type}`]->(b) "
            "RETURN elementId(a) AS a, elementId(b) AS b, r"
        ):
            subject = self.uri_by_eid.get(rec["a"])
            obj = self.uri_by_eid.get(rec["b"])
            if subject is not None and obj is not None:
                yield subject, obj, dict(rec["r"])

    def export_act_links(self):
        """Relationships of acts whose properties are kept: readings, agenda orders, voted acts."""
        PRO = self.PRO
        count = 0
        for bill, process, props in self.rel_rows("PART_OF"):
            self.g.add((bill, DCTERMS.isPartOf, process))
            self.add_props(bill, props, {"reading": PRO.reading})
            count += 1
        print(f"  PART_OF: {count}")

        # one REFERS_TO per agenda order (2026-10-19), so its properties sit
        # on the order itself
        count = 0
        for order, bill, props in self.rel_rows("REFERS_TO"):
            self.g.add((order, PRO.refersTo, bill))
            self.add_props(order, props, {"version": PRO.refersToVersion,
                                          "via": PRO.linkMethod})
            count += 1
        print(f"  REFERS_TO: {count}")

        counts = {}
        for vote, act, props in self.rel_rows("ON_ACT"):
            # inferred='vicini': act deduced from the nearest linked vote in the
            # sitting (build/repair_vote_data.py), not stated by the source
            predicate = PRO.onActInferred if props.get("inferred") else PRO.onAct
            self.g.add((vote, predicate, act))
            counts[predicate] = counts.get(predicate, 0) + 1
        print(f"  ON_ACT: {counts.get(PRO.onAct, 0)} + {counts.get(PRO.onActInferred, 0)} inferred")

    def export_rapporteurs(self):
        """REPORTED_BY → direct pr:reportedBy plus a reified pr:Rapporteurship.

        A rapporteur can be recorded by several sources (dati.camera.it,
        dati.senato.it, the bill page, the transcript) with different details,
        so each relationship becomes its own Rapporteurship whatever its source.
        """
        PRO = self.PRO
        count = 0
        for bill, person, props in self.rel_rows("REPORTED_BY"):
            self.g.add((bill, PRO.reportedBy, person))
            date = props.get("date")
            key = "|".join(str(x) for x in (
                bill, person, props.get("source"), props.get("role"),
                date.iso_format() if hasattr(date, "iso_format") else date,
                props.get("committee")))
            node = self.mint("rapporteurship", hashlib.md5(key.encode()).hexdigest()[:16])
            self.g.add((node, RDF.type, PRO.Rapporteurship))
            self.g.add((node, PRO.reportedAct, bill))
            self.g.add((node, PRO.rapporteur, person))
            self.add_props(node, props, {
                "role": PRO.role,
                "date": DCTERMS.date,
                "committee": PRO.committeeName,
                "source": PRO.source,
            })
            for key_list, predicate in (("roles_raw", PRO.roleRaw), ("venues", PRO.venue)):
                for value in props.get(key_list) or []:
                    self.g.add((node, predicate, Literal(str(value))))
            count += 1
        print(f"  REPORTED_BY: {count}")

    def export_amendment_links(self):
        """Amended act, signatories, floor votes, sub-amendments and re-submissions."""
        PRO = self.PRO
        counts = {}

        def add(s, p, o, label):
            self.g.add((s, p, o))
            counts[label] = counts.get(label, 0) + 1

        for amendment, act, props in self.rel_rows("AMENDS"):
            add(amendment, PRO.amendsJointAct if props.get("joint") else PRO.amends, act, "AMENDS")
        for person, amendment, props in self.rel_rows("SIGNED_AMENDMENT"):
            add(person, PRO.primarySignatoryOf if props.get("first") else PRO.coSignatoryOf,
                amendment, "SIGNED_AMENDMENT")
        for rel_type, predicate in (("ON_AMENDMENT", PRO.onAmendment),
                                    ("SUB_OF", PRO.subAmendmentOf),
                                    ("RESUBMITS", PRO.resubmits)):
            for a, b, _ in self.rel_rows(rel_type):
                add(a, predicate, b, rel_type)
        for label, count in counts.items():
            print(f"  {label}: {count}")

    # ---- individual votes (streamed, N-Triples) ----------------------------

    def export_votes_stream(self, path: Path) -> int:
        """Stream the individual votes (8.2M, 2026-10) to N-Triples, never in RAM."""
        PRO = self.PRO

        def nt(s, p, o):
            return f"<{s}> <{p}> {o} .\n"

        count = 0
        with open(path, "w", encoding="utf-8") as fh:
            for rec in self.rows(
                "MATCH (p:Person)-[:VOTED]->(iv:IndividualVote)-[:ON_VOTE]->(v:Vote) "
                "RETURN p.id AS person, iv.id AS iv, iv.outcome AS outcome, v.id AS vote"
            ):
                person = rec["person"] if rec["person"].startswith("http") \
                    else str(self.mint("person", rec["person"]))
                ivote = str(self.mint("ivote", rec["iv"]))
                vote = str(self.mint("vote", rec["vote"]))
                fh.write(nt(ivote, RDF.type, f"<{OCD.voto}>"))
                fh.write(nt(ivote, PRO.voter, f"<{person}>"))
                fh.write(nt(ivote, PRO.onVote, f"<{vote}>"))
                fh.write(nt(ivote, PRO.outcome, f'"{OUTCOME_IT.get(rec["outcome"], rec["outcome"])}"'))
                count += 1
                if count % 500_000 == 0:
                    print(f"  {count:,} individual votes...")
        print(f"  total: {count:,} individual votes -> {path.name}")
        return count


def main():
    parser = argparse.ArgumentParser(description="Export the ParliamentRAG KG as RDF")
    parser.add_argument("--out", default=str(REPO_ROOT / "dumps" / "rdf"),
                        help="output directory (default: dumps/rdf)")
    parser.add_argument("--format", choices=["ttl", "nt"], default="ttl",
                        help="serialization for the main KG file (default: ttl)")
    parser.add_argument("--base", default=BASE_DEFAULT,
                        help=f"base namespace for minted URIs (default: {BASE_DEFAULT})")
    parser.add_argument("--votes", action="store_true",
                        help="also export the 6.3M individual votes (separate .nt file)")
    parser.add_argument("--skip-text", action="store_true",
                        help="omit speech transcript text (much smaller dump)")
    parser.add_argument("--archive-url", default=None,
                        help="Postgres text archive for speeches stripped from the "
                             "graph (default: ARCHIVE_URL)")
    parser.add_argument("--allow-missing-text", action="store_true",
                        help="write the dump even if a chamber is mostly without text")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set (checked environment and repo-root .env)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_texts, amendment_texts = {}, {}
    if not args.skip_text:
        archive_url = archive_url_from_env(args.archive_url)
        archive_texts = load_speech_texts(archive_url)
        amendment_texts = load_amendment_texts(archive_url)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    exporter = RdfExporter(driver, args.base, include_text=not args.skip_text,
                           archive_texts=archive_texts, amendment_texts=amendment_texts)
    started = time.time()
    try:
        print("Exporting nodes...")
        exporter.export_people()
        exporter.export_organizations()
        exporter.export_acts_and_subjects()
        exporter.export_amendments()
        exporter.export_legislation()
        exporter.export_proceedings()
        exporter.export_provenance()
        exporter.export_ontology()
        print(f"  {len(exporter.uri_by_eid):,} nodes mapped")
        coverage = exporter.text_coverage.as_dict()
        if coverage:
            print(f"  speech text coverage: {coverage}")
        amendment_coverage = exporter.amendment_text_coverage.as_dict()
        if amendment_coverage:
            print(f"  amendment text coverage: {amendment_coverage}")
        broken = ([f"speech/{c}" for c in exporter.text_coverage.broken_chambers()]
                  + [f"amendment/{c}" for c in exporter.amendment_text_coverage.broken_chambers()])
        if broken and not args.allow_missing_text:
            sys.exit(f"text missing for {broken}: pass --archive-url (or set "
                     "ARCHIVE_URL) to read it from the Postgres archive")

        print("Exporting relationships...")
        exporter.export_simple_relationships()
        exporter.export_mentions_citations()
        exporter.export_memberships()
        exporter.export_offices()
        exporter.export_act_links()
        exporter.export_rapporteurs()
        exporter.export_amendment_links()

        kg_path = out_dir / f"parliamentrag_kg.{args.format}"
        print(f"Serializing {len(exporter.g):,} triples -> {kg_path} ...")
        exporter.g.serialize(destination=str(kg_path),
                             format="turtle" if args.format == "ttl" else "nt")

        # Consumed by the backend /api/data/stats endpoint
        meta = {
            "triples": len(exporter.g),
            "chambers": sorted(exporter.chambers),
            "speech_text": exporter.text_coverage.as_dict(),
            "amendments": exporter.amendment_count,
            "amendment_text": exporter.amendment_text_coverage.as_dict(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        meta_path = out_dir / "export_meta.json"
        meta_path.write_text(json.dumps(meta) + "\n")

        if args.votes:
            print("Streaming individual votes...")
            meta["individual_votes"] = exporter.export_votes_stream(
                out_dir / "parliamentrag_votes.nt")
            meta_path.write_text(json.dumps(meta) + "\n")
    finally:
        driver.close()
    print(f"Done in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
