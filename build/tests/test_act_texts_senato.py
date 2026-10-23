"""Senate bill texts from Akoma Ntoso: S. 1779 as the Senate publishes it (AkomaNtosoBulkData, 2026-10-23)."""

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import act_texts_senato as S  # noqa: E402
import load_act_texts as T  # noqa: E402

AKN = Path(__file__).parent / "data" / "akn_senato"
FOLDER = AKN / "Leg19" / "Atto00059859"


def parsed(kind: str) -> dict:
    return S.parse_akn(next((FOLDER / kind).glob("*.xml")).read_bytes())


def test_versions_from_the_bulk_data_folder():
    vs = S.versions_from_akn(AKN, 19)
    assert {v["tipodoc"] for v in vs} == {"ddlpres", "ddlcomm", "ddlmess"}
    v = next(v for v in vs if v["tipodoc"] == "ddlmess")
    assert v["act"] == "http://dati.senato.it/ddl/59859"
    assert v["number"] == "1779"
    assert v["id"] == "senato:19:ddl:59859:ddlmess:01518287"
    assert v["url"] == "https://www.senato.it/show-doc?leg=19&tipodoc=DDLMESS&id=1518287&idoggetto=0"


def test_approved_text_articles_heading_and_paragraphs():
    p = parsed("ddlmess")
    t = p["articolato"]
    assert p["kind"] == "testo" and p["number"] == "1779" and p["date"] == "2026-08-04"
    assert p["title"] == "Disposizioni in materia di protezione civile"
    lines = t.split("\n")
    i = lines.index("Art. 6.")
    assert lines[i + 1] == "(Linee guida e responsabilità penale nelle attività di protezione civile)"
    assert lines[i + 2].startswith("1. Nel capo VI del codice della protezione civile")
    assert "da adottare entro dodici mesi dalla data di entrata in vigore" in t
    assert "Art. 42-ter. (Responsabilità penale colposa nello svolgimento delle attività di protezione civile)" in t
    # Inline italics across a pretty-printed line break stay attached.
    assert "articolo 23-ter del decreto-legge 6 dicembre 2011, n. 201" in t
    assert "a) il trattamento giuridico nonché la specifica formazione" in t


def test_committee_column_takes_identico_from_the_left():
    p = parsed("ddlcomm")
    t = p["articolato"]
    assert S.version_label({"tipodoc": "ddlcomm", "label": "A", "number": "1779"}, p) == "A"
    # Changed by the committee: its own column.
    assert "e alla corrispondente area delle funzioni locali" in t
    # «2. Identico:» and «a) identica;» take the proposers' words.
    assert "2. Nel rispetto di quanto previsto dalla presente legge" in t
    assert "a) il trattamento giuridico nonché la specifica formazione" in t
    assert "Identico" not in t and "identica" not in t
    # Opinions of the other committees are not the text.
    assert "PARERI DELLA 2ª COMMISSIONE" not in t


def test_presented_text_has_no_report_when_it_is_only_images():
    p = parsed("ddlpres")
    assert p["kind"] == "testo"
    assert "Art. 42-ter (Responsabilità colposa per morte o lesioni personali" in p["articolato"]
    assert p["relazione"] == ""


def test_rows_and_hashes():
    vs = S.versions_from_akn(AKN, 19)
    rows = []
    for v in vs:
        rows += T.rows_for(v, S.parse_akn(v["path"].read_bytes()), 19, "senato")
    assert {r["chamber"] for r in rows} == {"senato"}
    assert {r["version_label"] for r in rows} == {None, "A", "approvato"}
    assert all(r["source_url"].startswith("https://www.senato.it/show-doc?") for r in rows)
    again = [r for v in vs for r in T.rows_for(v, S.parse_akn(v["path"].read_bytes()), 19, "senato")]
    assert [r["row_hash"] for r in rows] == [r["row_hash"] for r in again]
    stats: Counter = Counter()
    T.estimate(rows, stats)
    assert stats["rows"] == 3 and stats["chunks"] > 0


def test_squash_joins_breaks_before_punctuation_only():
    assert S._squash("Identico\n\t\t:") == "Identico:"
    assert S._squash("articolo 23\n\t-ter\n\tdel") == "articolo 23-ter del"
    assert S._squash("comparto \n\t\te alla") == "comparto e alla"
    assert S._squash("(Estensore: \n\tRastrelli\n\t)") == "(Estensore: Rastrelli)"


def test_side_by_side_identical_lines_inside_a_quoted_article():
    xml = (
        '<an:akomaNtoso xmlns:an="http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03"><an:bill>'
        "<an:body><an:hcontainer><an:content><an:table>"
        "<an:tr><an:td><an:p>Art. 1.</an:p></an:td><an:td><an:p>Art. 1.</an:p></an:td></an:tr>"
        "<an:tr><an:td><an:p>«1-bis. Testo vigente.</an:p><an:p>1-ter. Vecchio.»</an:p></an:td>"
        "<an:td><an:p>«1-bis. <an:i>Identico</an:i>.</an:p><an:p>1-ter. Nuovo.»</an:p></an:td></an:tr>"
        "<an:tr><an:td><an:p>Art. 2.</an:p></an:td><an:td><an:p><an:i>Soppresso</an:i></an:p></an:td></an:tr>"
        "</an:table></an:content></an:hcontainer></an:body></an:bill></an:akomaNtoso>"
    )
    assert S.parse_akn(xml)["articolato"] == "Art. 1.\n«1-bis. Testo vigente.\n1-ter. Nuovo.»"
