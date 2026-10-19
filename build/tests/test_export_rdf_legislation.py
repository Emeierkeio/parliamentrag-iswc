"""RDF export of laws, legislative processes, readings, rapporteurs, agenda orders and TESEO."""

import os
import re
import sys

from neo4j.time import Date
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from export_rdf import ELI, EUROVOC_SCHEME, ONTOLOGY, RdfExporter, law_uris

CAMERA = "http://dati.camera.it/ocd/attocamera.rdf/ac19_"
PERSON = "http://dati.camera.it/ocd/persona.rdf/p308851"
SENATOR = "http://dati.senato.it/senatore/36404"
LAW_ELI = "https://www.normattiva.it/eli/id/2026/10/09/26G00201"


class FakeExporter(RdfExporter):
    """RdfExporter fed from in-memory nodes and relationships instead of Neo4j."""

    def __init__(self, nodes, rels=None):
        super().__init__(driver=None, base="https://w3id.org/parliamentrag/", include_text=False)
        self.nodes = nodes
        self.rels = rels or {}

    def node_rows(self, label):
        for i, (labels, props) in enumerate(self.nodes.get(label, [])):
            yield {"eid": f"{label}:{i}", "labels": labels, "n": props}

    def rows(self, cypher):
        rel_type = re.search(r"\[r?:`?(\w+)`?\]", cypher).group(1)
        for a, b, props in self.rels.get(rel_type, []):
            yield {"a": a, "b": b, "r": props}


def electoral_law_graph():
    """L. 180/2026: C.2822 -> S.1971 -> C.2822-B, two rapporteurs, one agenda order."""
    nodes = {
        "ParliamentaryAct": [
            (["ParliamentaryAct", "Bill"], {"uri": CAMERA + "2822", "number": "2822",
                                            "chamber": "camera", "kind": "pdl_ordinaria",
                                            "title": "Disposizioni in materia di elezioni",
                                            "presentation_date": Date(2026, 3, 2)}),
            (["ParliamentaryAct", "Bill"], {"uri": "http://dati.senato.it/ddl/60317",
                                            "number": "1971", "chamber": "senato",
                                            "status": "approvato"}),
            (["ParliamentaryAct", "Bill"], {"uri": CAMERA + "2822-B", "number": "2822-B",
                                            "chamber": "camera"}),
            (["ParliamentaryAct", "AgendaOrder"], {
                "uri": "senato:19:aic:9/01971/005", "chamber": "senato",
                "outcome": "precluso", "outcome_source": "esito_senato", "outcome_raw": "Precluso",
                "outcome_url": "https://www.senato.it/show-doc?leg=19&tipodoc=EMEND&id=1"}),
            (["ParliamentaryAct", "Motion"], {
                "uri": "http://dati.camera.it/ocd/aic.rdf/aic1_00052_19", "number": "1/00052",
                "subject": "Iniziative per le pensioni minime", "subject_source": "debate",
                "official_uris": ["http://dati.camera.it/ocd/aic.rdf/aic1_00052_19",
                                  "http://dati.senato.it/sindacatoispettivo/1"]}),
        ],
        "Law": [(["Law"], {"number": 180, "date": Date(2026, 10, 9), "gu_date": Date(2026, 10, 9),
                            "gu_number": 235, "code": "26G00201", "kind": "legge",
                            "urn": "urn:nir:stato:legge:2026;180", "eli": LAW_ELI + "/ORIGINAL",
                            "normattiva_url": "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2026;180",
                            "title": "Disposizioni in materia di elezioni", "legislature": 19})],
        "LegislativeProcess": [(["LegislativeProcess"], {"id": "senato:19:iter:55214",
                                                         "title": "Elezioni", "legislature": 19})],
        "TextVersion": [(["TextVersion"], {"id": "http://dati.camera.it/ocd/versioneTestoAtto.rdf/vta19_x",
                                           "code": "19PDL0011910", "label": "A",
                                           "date": Date(2026, 4, 1),
                                           "url": "http://documenti.camera.it/doc?codice=x"})],
        "TeseoConcept": [(["TeseoConcept"], {"uri": "http://dati.senato.it/teseo/00002323",
                                             "label_it": "DEPUTATI"})],
        "EurovocConcept": [(["EurovocConcept"], {"uri": "http://eurovoc.europa.eu/100", "label_it": "voto"})],
        "Person": [(["Person", "Deputy"], {"id": PERSON}),
                   (["Person", "Senator"], {"id": SENATOR})],
        "Vote": [(["Vote"], {"id": "vote_1"}), (["Vote"], {"id": "vote_2"})],
    }
    act = "ParliamentaryAct:"
    rels = {
        "PART_OF": [(act + "0", "LegislativeProcess:0", {"reading": 1, "chamber": "camera"}),
                    (act + "1", "LegislativeProcess:0", {"reading": 2, "chamber": "senato"}),
                    (act + "2", "LegislativeProcess:0", {"reading": 3, "chamber": "camera"})],
        "NEXT_READING": [(act + "0", act + "1", {}), (act + "1", act + "2", {})],
        "BECAME_LAW": [("LegislativeProcess:0", "Law:0", {})],
        "HAS_VERSION": [(act + "0", "TextVersion:0", {})],
        "HAS_SUBJECT": [(act + "1", "TeseoConcept:0", {})],
        "REFERS_TO": [(act + "3", act + "1", {"version": "A", "via": "numero"})],
        "ON_ACT": [("Vote:0", act + "0", {}), ("Vote:1", act + "0", {"inferred": "vicini"})],
        "REPORTED_BY": [
            (act + "0", "Person:0", {"role": "relatore", "roles_raw": ["relatore"],
                                     "committee": "I COMMISSIONE", "source": "dati.camera.it"}),
            (act + "0", "Person:0", {"role": "relatore", "roles_raw": ["relatore"],
                                     "source": "resoconto", "date": Date(2026, 4, 2)}),
            (act + "1", "Person:1", {"role": "relatore", "roles_raw": ["relatore"],
                                     "venues": ["assemblea", "commissione"],
                                     "date": Date(2026, 6, 1), "source": "dati.senato.it"}),
        ],
    }
    return FakeExporter(nodes, rels)


def exported():
    exporter = electoral_law_graph()
    exporter.export_people()
    exporter.export_acts_and_subjects()
    exporter.export_legislation()
    exporter.export_proceedings()
    exporter.export_ontology()
    exporter.export_simple_relationships()
    exporter.export_act_links()
    exporter.export_rapporteurs()
    return exporter


def test_law_uris_strip_the_version_segment():
    work, expression = law_uris({"eli": LAW_ELI + "/ORIGINAL", "urn": "urn:nir:x"})
    assert work == URIRef(LAW_ELI)
    assert expression == URIRef(LAW_ELI + "/ORIGINAL")
    assert law_uris({"urn": "urn:nir:x"}) == (URIRef("urn:nir:x"), None)


def test_law_is_an_eli_legal_resource():
    g = exported().g
    law = URIRef(LAW_ELI)
    assert (law, RDF.type, ELI.LegalResource) in g
    assert (law, ELI.number, Literal(180)) in g
    assert (law, ELI.id_local, Literal("26G00201")) in g
    assert (law, OWL.sameAs, URIRef("urn:nir:stato:legge:2026;180")) in g
    assert (law, ELI.is_realized_by, URIRef(LAW_ELI + "/ORIGINAL")) in g
    assert (URIRef(LAW_ELI + "/ORIGINAL"), RDF.type, ELI.LegalExpression) in g
    assert str(g.value(law, ELI.date_document)) == "2026-10-09"


def test_readings_process_and_law_answer_a_sparql_query():
    g = exported().g
    query = """
        PREFIX eli: <http://data.europa.eu/eli/ontology#>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX pr: <https://w3id.org/parliamentrag/ontology#>
        SELECT ?number WHERE {
            ?law eli:number 180 .
            ?process prov:generated ?law .
            ?bill dcterms:isPartOf ?process ; pr:reading ?reading ; dcterms:identifier ?number .
        } ORDER BY ?reading
    """
    assert [str(r.number) for r in g.query(query)] == ["2822", "1971", "2822-B"]
    pr = exported().PRO
    assert (URIRef(CAMERA + "2822"), pr.nextReading, URIRef("http://dati.senato.it/ddl/60317")) in g


def test_text_version_keeps_the_official_uri():
    g = exported().g
    version = URIRef("http://dati.camera.it/ocd/versioneTestoAtto.rdf/vta19_x")
    assert (URIRef(CAMERA + "2822"), DCTERMS.hasVersion, version) in g
    assert (version, DCTERMS.identifier, Literal("19PDL0011910")) in g


def test_rapporteurs_one_rapporteurship_per_source():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    bill = URIRef(CAMERA + "2822")
    assert set(g.objects(bill, pr.reportedBy)) == {URIRef(PERSON)}
    sources = {str(g.value(node, pr.source)) for node in g.subjects(pr.reportedAct, bill)}
    assert sources == {"dati.camera.it", "resoconto"}
    senate = next(g.subjects(pr.rapporteur, URIRef(SENATOR)))
    assert {str(v) for v in g.objects(senate, pr.venue)} == {"assemblea", "commissione"}
    assert (senate, RDF.type, pr.Rapporteurship) in g


def test_agenda_order_outcome_and_bill():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    order = exporter.mint("act", "senato:19:aic:9/01971/005")
    assert (order, RDF.type, pr.AgendaOrder) in g
    assert (order, pr.refersTo, URIRef("http://dati.senato.it/ddl/60317")) in g
    assert (order, pr.refersToVersion, Literal("A")) in g
    assert (order, pr.outcome, Literal("precluso")) in g
    assert (order, pr.outcomeSource, Literal("esito_senato")) in g
    assert (order, pr.outcomeEvidence,
            URIRef("https://www.senato.it/show-doc?leg=19&tipodoc=EMEND&id=1")) in g


def test_motion_subject_and_official_uris():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    motion = URIRef("http://dati.camera.it/ocd/aic.rdf/aic1_00052_19")
    assert (motion, pr.subject, Literal("Iniziative per le pensioni minime")) in g
    assert set(g.objects(motion, OWL.sameAs)) == {URIRef("http://dati.senato.it/sindacatoispettivo/1")}


def test_votes_on_acts_keep_inferred_links_apart():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    bill = URIRef(CAMERA + "2822")
    assert (exporter.mint("vote", "vote_1"), pr.onAct, bill) in g
    assert (exporter.mint("vote", "vote_2"), pr.onActInferred, bill) in g
    assert (exporter.mint("vote", "vote_2"), pr.onAct, bill) not in g


def test_teseo_subject_in_its_scheme():
    exporter = exported()
    g = exporter.g
    teseo = URIRef("http://dati.senato.it/teseo/00002323")
    assert (URIRef("http://dati.senato.it/ddl/60317"), DCTERMS.subject, teseo) in g
    assert (teseo, SKOS.inScheme, exporter.PRR["scheme/teseo"]) in g
    assert (exporter.PRR["scheme/teseo"], RDF.type, SKOS.ConceptScheme) in g
    assert (URIRef("http://eurovoc.europa.eu/100"), SKOS.inScheme, EUROVOC_SCHEME) in g


def test_every_project_term_is_declared():
    exporter = exported()
    used = {term for triple in exporter.g for term in triple
            if isinstance(term, URIRef) and str(term).startswith(str(exporter.PRO))}
    declared = {exporter.PRO[name] for name in ONTOLOGY}
    assert used <= declared, used - declared
    assert (exporter.PRO.LegislativeProcess, RDFS.subClassOf, PROV.Activity) in exporter.g


def test_turtle_round_trip():
    exporter = exported()
    data = exporter.g.serialize(format="turtle")
    assert len(Graph().parse(data=data, format="turtle")) == len(exporter.g)
