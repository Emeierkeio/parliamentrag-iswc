"""Senate support in the dataset exports (Zenodo RDF, Hugging Face card, Zenodo metadata)."""

import json
import os
import re
import sys
from pathlib import Path

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import export_hf
import zenodo_update
from archive_text import TextCoverage
from export_rdf import OSR, RdfExporter, act_local_id, chamber_of_speech, org_slug

BUILD = Path(__file__).resolve().parent.parent


class FakeExporter(RdfExporter):
    """RdfExporter fed from in-memory node lists instead of Neo4j."""

    def __init__(self, nodes, **kwargs):
        super().__init__(driver=None, base="https://w3id.org/parliamentrag/", **kwargs)
        self.nodes = nodes

    def node_rows(self, label):
        for i, (labels, props) in enumerate(self.nodes.get(label, [])):
            yield {"eid": f"{label}:{i}", "labels": labels, "n": props}


def test_groups_with_same_acronym_get_distinct_uris_per_chamber():
    camera = {"name": "FRATELLI D'ITALIA", "acronym": "FDI", "chamber": "camera"}
    senato = {"name": "Fratelli d'Italia", "acronym": "FdI", "chamber": "senato"}
    assert org_slug(camera, use_acronym=True) == "fdi"
    assert org_slug(senato, use_acronym=True) == "senato-fdi"


def test_camera_committee_uri_unchanged():
    committee = {"name": "GIUNTA PER IL REGOLAMENTO", "chamber": "camera"}
    assert org_slug(committee, use_acronym=False) == "giunta-per-il-regolamento"
    committee_senato = {"name": "Giunta per il Regolamento", "chamber": "senato"}
    assert org_slug(committee_senato, use_acronym=False) == "senato-giunta-per-il-regolamento"


def test_senate_acts_minted_from_full_id_camera_from_number():
    assert act_local_id({"uri": "placeholder:pdl:977", "number": "977"}) == "977"
    senate = {"uri": "senato:19:aic:9/DOC.XXIV,NN.6-7/007", "number": "977", "chamber": "senato"}
    assert act_local_id(senate) == "senato:19:aic:9/DOC.XXIV,NN.6-7/007"


def test_chamber_of_speech():
    assert chamber_of_speech("sen_leg19_sed100_p1103_deb1_0") == "senato"
    assert chamber_of_speech("leg19_sed1_deb1_0") == "camera"


def test_senator_typed_and_linked_to_official_uris():
    exporter = FakeExporter({"Person": [
        (["Person", "Senator"], {"id": "http://dati.senato.it/senatore/36404",
                                 "senato_id": "http://dati.senato.it/senatore/36404"}),
        (["Person", "GovernmentMember", "Senator"],
         {"id": "gov_urso_adolfo", "senato_id": "http://dati.senato.it/senatore/1"}),
    ]}, include_text=True)
    exporter.export_people()
    senator = URIRef("http://dati.senato.it/senatore/36404")
    assert (senator, RDF.type, OSR.Senatore) in exporter.g
    assert not list(exporter.g.objects(senator, OWL.sameAs))  # id already official
    minister = exporter.mint("person", "gov_urso_adolfo")
    assert (minister, OWL.sameAs, URIRef("http://dati.senato.it/senatore/1")) in exporter.g


def test_speech_text_from_graph_then_archive():
    exporter = FakeExporter({"Speech": [
        (["Speech"], {"id": "leg19_sed1_a", "text": "testo Camera"}),
        (["Speech"], {"id": "sen_leg19_sed1_a"}),
        (["Speech"], {"id": "sen_leg19_sed1_b"}),
    ]}, include_text=True, archive_texts={"sen_leg19_sed1_a": "testo Senato"})
    exporter.export_proceedings()
    texts = {str(o) for o in exporter.g.objects(None, exporter.PRO.text)}
    assert texts == {"testo Camera", "testo Senato"}
    assert exporter.text_coverage.as_dict() == {
        "camera": {"speeches": 1, "without_text": 0},
        "senato": {"speeches": 2, "without_text": 1},
    }


def test_skip_text_does_not_count_coverage():
    exporter = FakeExporter({"Speech": [(["Speech"], {"id": "sen_leg19_sed1_a"})]},
                            include_text=False)
    exporter.export_proceedings()
    assert exporter.text_coverage.as_dict() == {}


def test_coverage_flags_a_chamber_without_text():
    coverage = TextCoverage()
    for i in range(100):
        coverage.add("camera", True)
        coverage.add("senato", i < 10)  # 90% of Senate speeches without text
    assert coverage.broken_chambers() == ["senato"]
    coverage = TextCoverage()
    for i in range(200):
        coverage.add("senato", i != 0)  # 0.5%: a few gaps stay below the threshold
    assert coverage.broken_chambers() == []


def test_provenance_names_both_sources():
    exporter = FakeExporter({"Session": [
        (["Session"], {"id": "leg19_sed1", "chamber": "camera"}),
        (["Session"], {"id": "sen_leg19_sed1", "chamber": "senato"}),
    ]}, include_text=True)
    exporter.export_proceedings()
    exporter.export_provenance()
    dataset = exporter.PRR["dataset"]
    sources = set(exporter.g.objects(dataset, DCTERMS.source))
    assert sources == {URIRef("http://dati.camera.it"), URIRef("http://dati.senato.it")}
    title = next(exporter.g.objects(dataset, DCTERMS.title))
    assert "Italian Parliament" in str(title)
    assert (dataset, DCTERMS.license,
            URIRef("https://creativecommons.org/licenses/by-sa/4.0/")) in exporter.g
    assert isinstance(title, Literal)


def test_coverage_spans_first_and_last_sitting():
    from datetime import date
    exporter = FakeExporter({"Session": [
        (["Session"], {"id": "leg19_sed2", "chamber": "camera", "date": date(2026, 10, 14)}),
        (["Session"], {"id": "sen_leg19_sed1", "chamber": "senato", "date": date(2022, 10, 13)}),
    ]}, include_text=True)
    exporter.export_proceedings()
    assert exporter.coverage() == {"start": "2022-10-13", "end": "2026-10-14"}


def test_hf_card_tokens_all_filled():
    template = (BUILD / "hf_dataset_card.md").read_text()
    tokens = set(re.findall(r"\{\{([A-Z_]+)\}\}", template))
    known = set(export_hf.CARD_STAT_QUERIES) | {"MAX_DATE", "HF_REPO"}
    assert tokens <= known, tokens - known
    assert "emeierkeio/parliamentrag-leg19" not in template


def test_zenodo_metadata_filled_from_export_meta():
    meta = zenodo_update.render_metadata(
        BUILD / "zenodo_metadata.json",
        {"triples": 1234567, "individual_votes": 8200000, "amendments": 224173,
         "coverage": {"start": "2022-10-13", "end": "2026-10-14"}})
    assert meta["license"] == "cc-by-sa-4.0"
    assert "1,234,567 triples" in meta["description"]
    assert "8,200,000 individual votes" in meta["description"]
    assert "224,173 amendments" in meta["description"]
    assert "Senate" in meta["title"]
    assert meta["dates"][0]["end"] == "2026-10-14"
    assert "www.senato.it" in meta["description"]
    assert json.dumps(meta).count("{{") == 0


def test_zenodo_metadata_refuses_missing_counts():
    with pytest.raises(SystemExit):
        zenodo_update.render_metadata(BUILD / "zenodo_metadata.json", {"triples": 1})


def test_source_chamber_falls_back_on_uri():
    assert export_hf.source_chamber({"chamber": "senato", "uri": "x"}) == "senato"
    assert export_hf.source_chamber({"uri": "http://dati.camera.it/ocd/aic.rdf/aic4_00001_19"}) == "camera"
    assert export_hf.source_chamber({"uri": "placeholder:pdl:5-A"}) == "camera"
    assert export_hf.source_chamber({"uri": "http://dati.senato.it/ddl/1"}) == "senato"
    assert export_hf.source_chamber({"id": "gov_meloni"}) is None


def test_senate_speaker_is_the_senate_uri():
    cam, sen = "http://dati.camera.it/ocd/persona.rdf/p302892", "http://dati.senato.it/senatore/25555"
    assert export_hf.senate_speaker("senato", cam, sen) == sen
    assert export_hf.senate_speaker("camera", cam, sen) == cam
    assert export_hf.senate_speaker("senato", "gov_nordio_carlo", None) == "gov_nordio_carlo"
