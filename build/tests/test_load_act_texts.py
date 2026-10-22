"""Chamber bill texts: section split, committee column, version codes, row hashes."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import load_act_texts as T  # noqa: E402

PAGE = """<html><body><div id="divWrapper" class="allegato_main_text">
<div id="telecomando"><p><a href="#FR">FRONTESPIZIO</a></p><p><a href="#PD">PROGETTO DI LEGGE</a></p></div>
<div id="FR"><p>CAMERA DEI DEPUTATI N. 2715</p></div>
<div id="RL"><p>Onorevoli Colleghi! La proposta istituisce il Registro.</p></div>
<div id="PD"><p align="center"><b>PROPOSTA DI LEGGE</b></p>
<div class="articolo" id="art.1"><p>Art. 1.<br /><i>(Finalità)</i></p><p>1. La presente legge tutela gli orfani.</p></div>
</div>
<p>Per tornare alla pagina di provenienza azionare il tasto BACK del browser</p>
<div id="tree_menu_1">Mappa del sito</div>
</div></body></html>"""

SIDE = """<div id="telecomando"></div>
<div id="FR"><p>N. 2715-A</p></div>
<div id="TFPD"><table>
<tr><td valign="top" width="50%"><p>Art. 2.</p></td><td valign="top" width="50%"><p>Art. 2.</p></td></tr>
<tr><td valign="top" width="50%"><p>1. È istituito, presso la Presidenza del Consiglio, il Registro.</p></td>
<td valign="top" width="50%"><p>1. È istituito, presso il Ministero della giustizia, il Registro.</p></td></tr>
<tr><td valign="top" width="50%"><p>2. Il Registro è aggiornato ogni anno.</p></td>
<td valign="top" width="50%"><p>2. <i>Identico</i>.</p></td></tr>
<tr><td valign="top" width="50%"><p>Art. 8.</p></td><td valign="top" width="50%"><p>Soppresso</p></td></tr>
<tr><td valign="top" width="50%"><p>1. Il PIAT è definito dalle amministrazioni.</p></td><td valign="top" width="50%"></td></tr>
</table></div>
<div id="pareri.1"><p>PARERE DELLA I COMMISSIONE</p></div>
"""


def test_single_column_sections():
    parsed = T.parse_document(PAGE)
    assert parsed["kind"] == "testo"
    assert "Art. 1." in parsed["articolato"]
    assert "tutela gli orfani" in parsed["articolato"]
    assert parsed["relazione"].startswith("Onorevoli Colleghi!")
    for chrome in ("FRONTESPIZIO", "Per tornare", "Mappa del sito", "CAMERA DEI DEPUTATI"):
        assert chrome not in parsed["articolato"]


def test_committee_column_wins():
    text = T.parse_document(SIDE)["articolato"]
    assert "presso il Ministero della giustizia" in text
    assert "Presidenza del Consiglio" not in text


def test_identico_takes_the_proposers_text():
    assert "Il Registro è aggiornato ogni anno." in T.parse_document(SIDE)["articolato"]


def test_suppressed_article_is_dropped():
    text = T.parse_document(SIDE)["articolato"]
    assert "PIAT" not in text
    assert "Soppresso" not in text
    assert "PARERE" not in text


def test_supplement_has_no_text():
    page = '<div id="telecomando"></div><div id="FR"><p>SUPPLEMENTO</p></div><div id="AI"><p>ANALISI DI IMPATTO</p></div>'
    parsed = T.parse_document(page)
    assert parsed["kind"] == "supplemento"
    assert parsed["articolato"] == "" and parsed["relazione"] == ""


def test_unified_text_without_sections():
    page = ('<div id="metadati"></div><div class="articolo" id="art.1"><p>Art. 1.</p>'
            '<p>1. Testo unificato.</p></div>')
    assert "Testo unificato." in T.parse_document(page)["articolato"]


def test_version_codes():
    assert T.version_of("leg.19.pdl.camera.2715_A.19PDL0217670") == {
        "leg": 19, "number": "2715", "label": "A", "doc": "19PDL0217670"}
    assert T.version_of("leg.19.pdl.camera.2715.19PDL0171260")["label"] is None
    assert T.version_of("leg.19.pdl.camera.1660_A-bis.19PDL0104250")["label"] == "A-bis"
    assert T.version_of("leg.19.pdl.camera.536.19PDLTU05360")["doc"] == "19PDLTU05360"
    assert T.version_of("not a code") is None


def test_rows_and_stable_hash():
    version = {"act": "http://dati.camera.it/ocd/attocamera.rdf/ac19_2715",
               "id": "http://dati.camera.it/ocd/versioneTestoAtto.rdf/vta19_leg.19.pdl.camera.2715.19PDL0171260",
               "code": "leg.19.pdl.camera.2715.19PDL0171260", "label": None, "date": None, "title": None}
    rows = T.rows_for(version, T.parse_document(PAGE), 19)
    assert [r["section"] for r in rows] == ["articolato", "relazione"]
    assert rows[0]["act_number"] == "2715"
    assert rows[0]["id"].endswith("#articolato")
    assert rows == T.rows_for(version, T.parse_document(PAGE), 19)
