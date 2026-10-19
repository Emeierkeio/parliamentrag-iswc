"""Senate votes, debate titles and links in the timeline API. Cards 202, 204."""
import asyncio

from app.routers import search as search_router
from app.services import timeline_service as ts
from app.services.laws import parse_law_reference
from app.services.links import act_public_url, act_text_url, camera_speech_url, https

ACT_1903 = {"number": "1903", "title": "Delega al Governo per il riordino della polizia locale",
            "type": "Disegno di legge", "status": "appr. def. non pubbl"}
ACT_610 = {"number": "610", "title": "Legge quadro", "type": "Disegno di legge", "status": "assorbito"}


def test_senate_bill_links():
    assert act_public_url("http://dati.senato.it/ddl/59875") == (
        "https://www.senato.it/leg/19/BGT/Schede/Ddliter/59875.htm")
    assert act_text_url("http://dati.senato.it/ddl/60149") == (
        "https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl?tab=testiEmendamenti&did=60149")


def test_later_reading_page_and_https_text():
    assert act_public_url("http://dati.camera.it/ocd/attocamera.rdf/ac19_2822-B") == (
        "https://www.camera.it/leg19/126?tab=1&leg=19&idDocumento=2822-B")
    pdf = "http://documenti.camera.it/_dati/leg19/lavori/stampati/pdf/19PDL0199150.pdf"
    assert act_text_url("x", pdf) == "https" + pdf[4:]
    assert https("http://example.org/a") == "http://example.org/a"


def test_camera_speech_url_from_chunk_id():
    assert camera_speech_url("leg19_sed210_tit00020.int00060_chunk_10") == (
        "https://www.camera.it/leg19/410?idSeduta=0210&tipo=stenografico"
        "#sed0210.stenografico.tit00020.int00060")
    assert camera_speech_url("sen_leg19_sed465_x") is None


def test_senate_vote_description_names_the_bill():
    text = ts.senate_vote_description([ACT_610, ACT_1903])
    assert text.startswith("Ddl n. 1903: Delega al Governo")
    assert text.endswith("(assorbiti i ddl n. 610)")
    assert ts.senate_vote_description([]) is None


def test_quorum_check_is_not_a_rejected_vote():
    row = {"id": "senato_leg19_sed465_v001", "number": 1, "subject": "Verifica del numero legale",
           "description": None, "final_vote": False, "outcome": "rejected", "in_favor": 0,
           "against": 0, "abstained": 0, "present": 159, "chamber": "senato",
           "act_subject": None, "acts": []}
    vote = ts._vote_info(row)
    assert vote.kind == "quorum_check" and vote.outcome is None
    assert "numero legale" in vote.description and "159" in vote.description


def test_senate_vote_gets_a_description():
    row = {"id": "v", "number": 19, "subject": "Votazione finale", "description": None,
           "final_vote": True, "outcome": "approved", "in_favor": 80, "against": 46,
           "abstained": 4, "present": 131, "chamber": "senato", "act_subject": None,
           "acts": [ACT_1903, ACT_610]}
    vote = ts._vote_info(row)
    assert vote.outcome == "approved" and vote.kind is None
    assert "1903" in vote.description
    assert vote.act_number == "1903" and vote.act_title.startswith("Delega al Governo")


def test_debate_titles():
    assert ts.clean_debate_title(
        "Seguito della discussione (A.C. 2822-B) (ore 9,08). (ore 9,08) (ore 9,08)") == (
        "Seguito della discussione (A.C. 2822-B) (ore 9,08)")
    assert ts.clean_debate_title("Sull'ordine dei lavori. . .") == "Sull'ordine dei lavori."
    act = {"number": "2029", "title": "Conversione in legge del decreto-legge n. 157"}
    assert ts.clean_debate_title("Ripresa della discussione del disegno di legge n.", act) == (
        "Ripresa della discussione del disegno di legge n. 2029: Conversione in legge del decreto-legge n. 157")
    assert ts.clean_debate_title("Discussione del disegno di legge:", act).startswith(
        "Discussione del disegno di legge n. 2029: ")
    assert ts.clean_debate_title("Si riprende la discussione.", {"number": "2822-B"}, "camera") == (
        "Si riprende la discussione (A.C. 2822-B)")
    assert ts.clean_debate_title("Ripresa della discussione (ore 11,37)") == "Ripresa della discussione (ore 11,37)"


def test_outcome_fragments_fold_into_the_debate_before():
    folded = ts.fold_fragments([
        {"id": "a", "title": "Approvazione del disegno di legge n.1903", "speech_count": 6},
        {"id": "b", "title": "È approvato.", "speech_count": 1},
        {"id": "c", "title": "Non è approvato.", "speech_count": 2},
        {"id": "d", "title": "Per fatto personale", "speech_count": 1},
    ])
    assert [f["id"] for f in folded] == ["a", "d"]
    assert folded[0]["continuation_ids"] == ["b", "c"] and folded[0]["speech_count"] == 9


def test_law_references():
    for q in ("legge 180/2026", "L. 180/2026", "legge n. 180 del 2026", "la legge n. 180 del 9 ottobre 2026",
              "legge 9 ottobre 2026, n. 180"):
        assert parse_law_reference(q) == (180, 2026, None), q
    assert parse_law_reference("legge costituzionale n. 1 del 2026") == (1, 2026, "legge_costituzionale")
    assert parse_law_reference("salario minimo") is None


def test_misto_party_is_the_component():
    assert ts._party("MISTO", "Minoranze Linguistiche") == ("Minoranze Linguistiche", "MISTO")
    assert ts._party("MISTO", None) == (ts.MISTO_WITHOUT_COMPONENT, "MISTO")
    assert ts._party("LEGA - SALVINI PREMIER", None) == ("LEGA - SALVINI PREMIER", None)


def test_display_case():
    assert ts._display_case("WANDA") == "Wanda"
    assert ts._display_case("D'ALESSIO") == "D'Alessio"
    assert ts._display_case("Della Porta") == "Della Porta"


class _Graph:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def query(self, cypher, params=None):
        self.calls.append((cypher, params))
        return self.rows


def test_vote_on_second_reading_shows_that_reading():
    first = {"uri": "http://dati.camera.it/ocd/attocamera.rdf/ac19_2822", "number": "2822"}
    later = {"uri": "http://dati.camera.it/ocd/attocamera.rdf/ac19_2822-B", "number": "2822-B"}
    graph = _Graph([{"uri": first["uri"], "act": later}])
    assert ts._later_readings(graph, [first], "PDL 2822-B - ARTICOLO 8") == [later]
    assert graph.calls[0][1]["codes"] == ["2822-B"]
    untouched = _Graph([])
    assert ts._later_readings(untouched, [first], "PDL 2822-A - ARTICOLO 1") == [first]
    assert untouched.calls == []


def test_article_of_a_named_bill_in_an_earlier_annex():
    paras = [("ac.1000.art_8", "Art. 8 di un altro progetto"), (None, "testo altro"),
             ("ac.2822-B.art_8", "Art. 8. (Fuori sede)"), (None, "1. È istituito"),
             (None, "EMENDAMENTI NON SEGNALATI PER LA VOTAZIONE"), (None, "ART. 1."), ("ac.2822-B.art_9", "Art. 9")]
    assert ts._extract_article(paras, "8", "2822-B") == ["Art. 8. (Fuori sede)", "1. È istituito"]
    assert ts._extract_article(paras, "8")[0] == "Art. 8 di un altro progetto"


def test_search_attributes_misto_to_the_component():
    results = [
        {"type": "speech", "id": "leg19_sed723_tit00040.int00010_chunk_0", "group": "MISTO", "chamber": "camera"},
        {"type": "speech", "id": "leg19_sed723_tit00040.int00020_chunk_0", "group": "MISTO", "chamber": "camera"},
        {"type": "speech", "id": "x", "group": "MOVIMENTO 5 STELLE", "chamber": "camera"},
        {"type": "act", "id": "http://dati.senato.it/ddl/60317", "group": "MISTO", "last_name": ""},
    ]
    graph = _Graph([{"id": "leg19_sed723_tit00040.int00010_chunk_0", "component": "Minoranze Linguistiche"}])
    search_router._attribute_misto(graph, results)
    assert results[0]["group"] == "Minoranze Linguistiche" and results[0]["parliamentary_group"] == "MISTO"
    assert results[1]["group"] == ts.MISTO_WITHOUT_COMPONENT
    assert "parliamentary_group" not in results[2]
    assert results[3]["group"] is None
    search_router._add_links(results)
    assert results[0]["url"].startswith("https://www.camera.it/leg19/410?idSeduta=0723")


def test_debate_votes_are_filtered_by_the_discussed_acts():
    class Graph:
        def query_single(self, cypher, params=None):
            return {"id": "d", "title": "Approvazione del disegno di legge n.1903", "recap": None,
                    "chamber": "senato", "siblings": [{"id": "d", "title": "x", "ord": 3}]}

        def query(self, cypher, params=None):
            if "HAS_VOTE" in cypher:
                assert "size(mine) > 0" in cypher
            return []

    detail = asyncio.run(ts.get_debate_detail(Graph(), "d", "it"))
    assert detail.votes == []


def test_article_candidates_include_earlier_sittings(monkeypatch):
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        if "idSeduta=0720" in url:
            return [("ac.2822-B.art_8", "Art. 8."), (None, "1. Testo")]
        return [(None, "altro")]

    monkeypatch.setattr(ts, "_fetch_annex_paragraphs", fake_fetch)
    meta = {"subject": "Votazione Articolo 8", "description": "PDL 2822-B - ARTICOLO 8",
            "session_number": 722, "legislature": 19, "chamber": "camera", "earlier_sittings": [721, 720, 718]}
    seg, url = ts._annex_block(meta, "article", "8")
    assert seg == ["Art. 8.", "1. Testo"] and "idSeduta=0720" in url
    assert len(fetched) == 3
