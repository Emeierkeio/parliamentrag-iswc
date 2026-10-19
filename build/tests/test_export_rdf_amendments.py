"""RDF export of amendments and parliamentary documents."""

import os
import sys

from neo4j.time import Date
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, FOAF, PROV, RDF, RDFS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from export_rdf import ONTOLOGY, OSR, act_local_id  # noqa: E402
from test_export_rdf_legislation import CAMERA, PERSON, SENATOR, FakeExporter  # noqa: E402

AMENDMENT_ID = "C|C.2822|assemblea|20260401|1.1|"
SUB_ID = "C|C.2822|assemblea|20260401|1.1.1|"
RESUBMITTED_ID = "C|C.2822|commissione|20260320|1.1|"
SENATE_ID = "S|1371053"


def amendments_and_documents_graph(amendment_texts=None, include_text=True):
    """C.2822 with three Camera amendments and one Senate one; the DEF in both chambers."""
    nodes = {
        "ParliamentaryAct": [
            (["ParliamentaryAct", "Bill"], {"uri": CAMERA + "2822", "number": "2822",
                                            "chamber": "camera"}),
            (["ParliamentaryAct", "Bill"], {"uri": CAMERA + "2900", "number": "2900",
                                            "chamber": "camera"}),
            (["ParliamentaryAct", "ParliamentaryDocument"], {
                "uri": "camera:19:doc:LVII:1", "id": "camera:19:doc:LVII:1", "kind": "doc",
                "number": "1", "doc_series": "LVII", "name": "Doc. LVII, n. 1",
                "chamber": "camera", "title": "Documento di economia e finanza 2023",
                "presentation_date": Date(2023, 4, 11), "initiative": "governo",
                "title_source": "senato", "doc_type_raw": "Documento di economia e finanza",
                "url": "https://www.camera.it/doc/LVII/1",
                "text_urls": ["http://documenti.camera.it/a.pdf", "http://documenti.camera.it/b.pdf"],
                "official_uris": ["http://dati.camera.it/ocd/doc.rdf/doc19_LVIIn1"]}),
            (["ParliamentaryAct", "ParliamentaryDocument"], {
                "uri": "camera:19:doc:XXII:1", "id": "camera:19:doc:XXII:1", "kind": "doc",
                "number": "1", "doc_series": "XXII", "chamber": "camera"}),
            (["ParliamentaryAct", "ParliamentaryDocument"], {
                "uri": "senato:19:doc:LVII:1", "id": "senato:19:doc:LVII:1", "kind": "doc",
                "number": "1", "doc_series": "LVII", "chamber": "senato"}),
        ],
        "Amendment": [
            (["Amendment"], {"id": AMENDMENT_ID, "chamber": "camera", "legislature": 19,
                             "act": "C.2822", "number": "1.1", "kind": "emendamento",
                             "venue": "assemblea", "article": "1", "outcome": "rejected",
                             "outcome_source": "floor_vote", "sitting_date": Date(2026, 4, 1),
                             "source_url": "https://documenti.camera.it/leg19/emendamenti/xml/x.xml",
                             "row_hash": "abc", "group_id": RESUBMITTED_ID,
                             "member_signatories": 2}),
            (["Amendment"], {"id": SUB_ID, "chamber": "camera", "legislature": 19,
                             "number": "1.1.1", "kind": "subEmendamento", "venue": "assemblea"}),
            (["Amendment"], {"id": RESUBMITTED_ID, "chamber": "camera", "legislature": 19,
                             "number": "1.1", "kind": "emendamento", "venue": "commissione",
                             "committee": "I Commissione", "outcome": "approved",
                             "outcome_source": "source", "outcome_raw": "Approvato"}),
            (["Amendment"], {"id": SENATE_ID, "chamber": "senato", "legislature": 19,
                             "number": "3.1", "kind": "emendamento", "version": "testo 2",
                             "presented_on": Date(2023, 5, 25), "outcome": "withdrawn",
                             "outcome_source": "source", "outcome_raw": "Ritirato"}),
        ],
        "LegislativeProcess": [
            (["LegislativeProcess"], {"id": "parlamento:19:doc:LVII:1", "kind": "doc",
                                      "title": "Documento di economia e finanza 2023"}),
            (["LegislativeProcess"], {"id": "senato:19:iter:55214", "title": "Elezioni"}),
        ],
        "Person": [(["Person", "Deputy"], {"id": PERSON}),
                   (["Person", "Senator"], {"id": SENATOR})],
        "Vote": [(["Vote"], {"id": "vote_1"}), (["Vote"], {"id": "vote_2"})],
    }
    act, amd = "ParliamentaryAct:", "Amendment:"
    rels = {
        "AMENDS": [(amd + "0", act + "0", {"joint": False}),
                   (amd + "0", act + "1", {"joint": True}),
                   (amd + "1", act + "0", {"joint": False}),
                   (amd + "2", act + "0", {"joint": False})],
        "SIGNED_AMENDMENT": [("Person:0", amd + "0", {"first": True}),
                             ("Person:1", amd + "0", {"first": False})],
        "ON_AMENDMENT": [("Vote:0", amd + "0", {"method": "act"})],
        "SUB_OF": [(amd + "1", amd + "0", {})],
        "RESUBMITS": [(amd + "0", amd + "2", {})],
        "PART_OF": [(act + "2", "LegislativeProcess:0", {"chamber": "camera"}),
                    (act + "4", "LegislativeProcess:0", {"chamber": "senato"})],
        "ON_ACT": [("Vote:1", act + "3", {})],
        "REPORTED_BY": [(act + "2", "Person:0", {"role": "relatore", "source": "resoconto"})],
    }
    if amendment_texts is None:
        amendment_texts = {AMENDMENT_ID: "Al comma 1, sopprimere le parole: e maggiormente.",
                           SENATE_ID: "Sopprimere l'articolo 3."}
    exporter = FakeExporter(nodes, rels)
    exporter.include_text = include_text
    exporter.amendment_texts = dict(amendment_texts)
    return exporter


def exported(**kwargs):
    exporter = amendments_and_documents_graph(**kwargs)
    exporter.export_people()
    exporter.export_acts_and_subjects()
    exporter.export_amendments()
    exporter.export_legislation()
    exporter.export_proceedings()
    exporter.export_ontology()
    exporter.export_simple_relationships()
    exporter.export_act_links()
    exporter.export_rapporteurs()
    exporter.export_amendment_links()
    return exporter


def test_amendment_properties_text_and_outcome_provenance():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    amendment = exporter.mint("amendment", AMENDMENT_ID)
    assert (amendment, RDF.type, pr.Amendment) in g
    assert (amendment, DCTERMS.identifier, Literal("1.1")) in g
    assert (amendment, DCTERMS.type, Literal("emendamento")) in g
    assert (amendment, pr.article, Literal("1")) in g
    assert (amendment, pr.outcome, Literal("respinto")) in g
    assert (amendment, pr.outcomeSource, Literal("voto_aula")) in g
    assert (amendment, pr.text,
            Literal("Al comma 1, sopprimere le parole: e maggiormente.", lang="it")) in g
    assert (amendment, FOAF.page,
            URIRef("https://documenti.camera.it/leg19/emendamenti/xml/x.xml")) in g
    senate = exporter.mint("amendment", SENATE_ID)
    assert (senate, pr.amendmentVersion, Literal("testo 2")) in g
    assert str(g.value(senate, DCTERMS.dateSubmitted)) == "2023-05-25"


def test_amendment_internal_keys_stay_out():
    exporter = exported()
    amendment = exporter.mint("amendment", AMENDMENT_ID)
    values = {str(o) for o in exporter.g.objects(amendment, None)}
    assert "abc" not in values
    assert RESUBMITTED_ID not in values


def test_amendment_links():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    amendment = exporter.mint("amendment", AMENDMENT_ID)
    assert (amendment, pr.amends, URIRef(CAMERA + "2822")) in g
    assert (amendment, pr.amendsJointAct, URIRef(CAMERA + "2900")) in g
    assert (amendment, pr.amends, URIRef(CAMERA + "2900")) not in g
    assert (URIRef(PERSON), pr.primarySignatoryOf, amendment) in g
    assert (URIRef(SENATOR), pr.coSignatoryOf, amendment) in g
    assert (exporter.mint("vote", "vote_1"), pr.onAmendment, amendment) in g
    assert (exporter.mint("amendment", SUB_ID), pr.subAmendmentOf, amendment) in g
    assert (amendment, pr.resubmits, exporter.mint("amendment", RESUBMITTED_ID)) in g


def test_amendments_to_a_bill_with_outcome_by_sparql():
    g = exported().g
    query = """
        PREFIX pr: <https://w3id.org/parliamentrag/ontology#>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?number ?outcome ?source WHERE {
            ?bill dcterms:identifier "2822" .
            ?a pr:amends ?bill ; dcterms:identifier ?number .
            OPTIONAL { ?a pr:outcome ?outcome ; pr:outcomeSource ?source }
        } ORDER BY ?number ?source
    """
    rows = [(str(r.number), str(r.outcome or ""), str(r.source or "")) for r in g.query(query)]
    assert sorted(rows) == [("1.1", "approvato", "fonte"), ("1.1", "respinto", "voto_aula"),
                            ("1.1.1", "", "")]


def test_amendment_text_skipped_and_coverage():
    exporter = exported(include_text=False)
    assert not list(exporter.g.subject_objects(exporter.PRO.text))
    exporter = exported(amendment_texts={})
    coverage = exporter.amendment_text_coverage
    assert coverage.as_dict()["camera"] == {"amendments": 3, "without_text": 3}
    assert coverage.broken_chambers() == ["camera", "senato"]


def test_documents_with_the_same_number_get_distinct_uris():
    assert act_local_id({"uri": "camera:19:doc:XXII:1", "kind": "doc", "number": "1",
                         "chamber": "camera"}) == "camera:19:doc:XXII:1"
    assert act_local_id({"uri": "placeholder:2822", "number": "2822",
                         "chamber": "camera"}) == "2822"
    exporter = exported()
    pr = exporter.PRO
    docs = set(exporter.g.subjects(RDF.type, pr.ParliamentaryDocument))
    assert docs == {exporter.mint("act", "camera:19:doc:LVII:1"),
                    exporter.mint("act", "camera:19:doc:XXII:1"),
                    exporter.mint("act", "senato:19:doc:LVII:1")}


def test_document_properties_votes_and_rapporteur():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    doc = exporter.mint("act", "camera:19:doc:LVII:1")
    assert (doc, RDFS.label, Literal("Doc. LVII, n. 1")) in g
    assert (doc, pr.docSeries, Literal("LVII")) in g
    assert (doc, pr.documentType, Literal("Documento di economia e finanza")) in g
    assert (doc, pr.initiative, Literal("governo")) in g
    assert (doc, pr.titleSource, Literal("senato")) in g
    assert (doc, FOAF.page, URIRef("https://www.camera.it/doc/LVII/1")) in g
    assert set(g.objects(doc, pr.textFile)) == {URIRef("http://documenti.camera.it/a.pdf"),
                                                URIRef("http://documenti.camera.it/b.pdf")}
    assert (doc, pr.reportedBy, URIRef(PERSON)) in g
    inquiry = exporter.mint("act", "camera:19:doc:XXII:1")
    assert (exporter.mint("vote", "vote_2"), pr.onAct, inquiry) in g


def test_document_process_is_not_a_legislative_process():
    exporter = exported()
    g, pr = exporter.g, exporter.PRO
    process = exporter.mint("process", "parlamento:19:doc:LVII:1")
    assert (process, RDF.type, pr.DocumentProcess) in g
    assert (process, RDF.type, pr.LegislativeProcess) not in g
    assert (exporter.mint("process", "senato:19:iter:55214"), RDF.type, pr.LegislativeProcess) in g
    members = set(g.subjects(DCTERMS.isPartOf, process))
    assert members == {exporter.mint("act", "camera:19:doc:LVII:1"),
                       exporter.mint("act", "senato:19:doc:LVII:1")}
    assert (pr.DocumentProcess, RDFS.subClassOf, PROV.Activity) in g


def test_new_terms_are_declared():
    exporter = exported()
    used = {term for triple in exporter.g for term in triple
            if isinstance(term, URIRef) and str(term).startswith(str(exporter.PRO))}
    declared = {exporter.PRO[name] for name in ONTOLOGY}
    assert used <= declared, used - declared
    assert (exporter.PRO.Amendment, RDFS.subClassOf, OSR.Emendamento) in exporter.g


def test_turtle_round_trip():
    exporter = exported()
    data = exporter.g.serialize(format="turtle")
    assert len(Graph().parse(data=data, format="turtle")) == len(exporter.g)


def test_every_outcome_in_the_graph_is_published_in_italian():
    # Outcome codes found in the production graph on 19/10/2026.
    from export_rdf import OUTCOME_IT, OUTCOME_SOURCE_IT
    graph_codes = {
        "rejected", "precluded", "inadmissible", "withdrawn", "approved", "superseded",
        "identical", "accepted", "lapsed", "absorbed", "not_accepted",
        "accepted_as_recommendation", "not_voted", "mixed", "other",
        "favor", "against", "abstain", "absent", "secret",
    }
    assert graph_codes <= OUTCOME_IT.keys()
    assert set(OUTCOME_SOURCE_IT) == {"source", "floor_vote"}
