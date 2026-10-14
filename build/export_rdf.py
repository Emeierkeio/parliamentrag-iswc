"""
RDF export of the ParliamentRAG knowledge graph (schema v2).

Serializes the Neo4j property graph as RDF using the ontology alignment
documented in docs/plans/PLAN_db_schema_v2.md §2.7 (and in the In-Use paper
appendix): OCD, FOAF, W3C ORG, SKOS, PROV-O, plus a small project namespace
for terms with no exact standard equivalent (AKN has no canonical RDF
vocabulary, so the debate structure uses project classes aligned to Akoma
Ntoso element names in rdfs:comment annotations).

Node → RDF mapping:
  Person / Deputy / GovernmentMember  foaf:Person (+ ocd:deputato for deputies,
    / Senator                           osr:Senatore for senators; owl:sameAs
                                        to the dati.camera.it / dati.senato.it
                                        person URI when the node id differs)
  ParliamentaryGroup, Committee,      org:Organization
    Government, MistoComponent          (+ ocd:gruppoParlamentare / ocd:organo)
  ParliamentaryAct                    ocd:atto
  EurovocConcept                      skos:Concept (canonical EuroVoc URIs)
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
without text.

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
from rdflib.namespace import DCTERMS, FOAF, ORG, OWL, PROV, RDF, SDO, SKOS, XSD

from archive_text import TextCoverage, archive_url_from_env, load_speech_texts

REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_DEFAULT = "https://w3id.org/parliamentrag/"
OCD = Namespace("http://dati.camera.it/ocd/")
OSR = Namespace("http://dati.senato.it/osr/")

SOURCE_BY_CHAMBER = {
    "camera": ("http://dati.camera.it", "Camera dei deputati"),
    "senato": ("http://dati.senato.it", "Senato della Repubblica"),
}

# Filtered inside the query (see node_rows), not client-side: the vectors are
# ~1536 floats per node and streaming them over the SSH tunnel only to drop them
# made the export take minutes per label and drop the connection.
EXCLUDED_PROP = "embedding"


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
    acts use their full `senato:19:...` id, since bare numbers repeat across
    chambers.
    """
    source_uri = props.get("uri", "")
    if props.get("chamber") == "senato":
        return source_uri
    return str(props.get("number") or source_uri)


class RdfExporter:
    def __init__(self, driver, base: str, include_text: bool,
                 archive_texts: dict | None = None):
        self.driver = driver
        self.include_text = include_text
        self.archive_texts = archive_texts or {}
        self.text_coverage = TextCoverage()
        self.chambers = set()
        self.PRO = Namespace(base + "ontology#")   # classes and properties
        self.PRR = Namespace(base + "resource/")   # minted entity URIs
        self.g = Graph()
        for prefix, ns in [("ocd", OCD), ("foaf", FOAF), ("org", ORG),
                           ("skos", SKOS), ("dcterms", DCTERMS), ("prov", PROV),
                           ("schema", SDO), ("osr", OSR), ("owl", OWL),
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
        for rec in self.node_rows("ParliamentaryAct"):
            props = dict(rec["n"])
            source_uri = props.get("uri", "")
            if source_uri.startswith("http"):
                uri = URIRef(source_uri)
            else:  # placeholder and Senate non-bill acts have no http URI
                uri = self.mint("act", act_local_id(props))
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, OCD.atto))
            self.add_props(uri, props, {
                "number": DCTERMS.identifier,
                "type": DCTERMS.type,
            })

        for rec in self.node_rows("EurovocConcept"):
            props = dict(rec["n"])
            uri = URIRef(props["uri"])
            self.uri_by_eid[rec["eid"]] = uri
            self.g.add((uri, RDF.type, SKOS.Concept))
            if props.get("label_it"):
                self.g.add((uri, SKOS.prefLabel, Literal(props["label_it"], lang="it")))

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
                fh.write(nt(ivote, PRO.outcome, f'"{rec["outcome"]}"'))
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

    archive_texts = {}
    if not args.skip_text:
        archive_texts = load_speech_texts(archive_url_from_env(args.archive_url))

    driver = GraphDatabase.driver(uri, auth=(user, password))
    exporter = RdfExporter(driver, args.base, include_text=not args.skip_text,
                           archive_texts=archive_texts)
    started = time.time()
    try:
        print("Exporting nodes...")
        exporter.export_people()
        exporter.export_organizations()
        exporter.export_acts_and_subjects()
        exporter.export_proceedings()
        exporter.export_provenance()
        print(f"  {len(exporter.uri_by_eid):,} nodes mapped")
        coverage = exporter.text_coverage.as_dict()
        if coverage:
            print(f"  speech text coverage: {coverage}")
        broken = exporter.text_coverage.broken_chambers()
        if broken and not args.allow_missing_text:
            sys.exit(f"speech text missing for {broken}: pass --archive-url (or set "
                     "ARCHIVE_URL) to read it from the Postgres archive")

        print("Exporting relationships...")
        exporter.export_simple_relationships()
        exporter.export_mentions_citations()
        exporter.export_memberships()
        exporter.export_offices()

        kg_path = out_dir / f"parliamentrag_kg.{args.format}"
        print(f"Serializing {len(exporter.g):,} triples -> {kg_path} ...")
        exporter.g.serialize(destination=str(kg_path),
                             format="turtle" if args.format == "ttl" else "nt")

        # Consumed by the backend /api/data/stats endpoint
        meta = {
            "triples": len(exporter.g),
            "chambers": sorted(exporter.chambers),
            "speech_text": exporter.text_coverage.as_dict(),
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
