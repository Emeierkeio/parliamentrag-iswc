"""Laws from the Senate, the Camera's Gazzetta notes and Normattiva (decision D5)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest_laws import apply_normattiva, camera_gazette, merge_sources, parse_normattiva, senate_laws

CAM = "http://dati.camera.it/ocd/attocamera.rdf/ac19_"
SEN = "http://dati.senato.it/ddl/"


def _phase(ddl, iter_id, numero, legge, data, natura="ordinaria", ramo="S"):
    return {"ddl": SEN + ddl, "idDdl": iter_id, "numero": numero, "ramo": ramo, "natura": natura,
            "numeroLegge": legge, "dataLegge": data}


NORMATTIVA_PAGE = """
<title>LEGGE 9 ottobre 2026, n. 180 - Normattiva</title>
<meta about="na:id/2026/10/09/26G00201/ORIGINAL" property="eli:uri_schema" content="x"/>
<input type="hidden" name="atto.codiceRedazionale" value="26G00201" />
<div id="titoloAtto" class="data_info"> <h2> LEGGE 9 ottobre 2026, n. 180 </h2></div>
<h3 style="font-size: 18px;">Disposizioni in materia di elezioni della Camera dei deputati  e  del
Senato della Repubblica. (26G00201)
</h3>
<a href="https://www.gazzettaufficiale.it/eli/gu/2026/10/09/235/sg/pdf">(GU n.235 del 09-10-2026)</a>
"""


def test_every_phase_of_the_iter_names_one_law_and_placeholders_are_left_out():
    laws, placeholders = senate_laws([
        _phase("60317", "55214", "1971", "180", "2026-10-09"),
        _phase("60001", "55214", "2822-B", "180", "2026-10-09", ramo="C"),
        _phase("59541", "53811", "1353-B", "690", "2100-01-01", natura="costituzionale"),
        _phase("1", "9", "5", "", ""),
    ], 19)
    assert laws == [{"kind": "legge", "number": 180, "senate_date": "2026-10-09",
                     "processes": ["senato:19:iter:55214"]}]
    assert [p["numero"] for p in placeholders] == ["1353-B"]


def test_camera_note_parsed_with_first_of_month():
    rows = camera_gazette([
        {"a": CAM + "2822-B", "desc": "Legge 180 del 9 ottobre 2026  pubblicata nella Gazzetta "
                                      "Ufficiale n. 235 del 9 ottobre 2026 "},
        {"a": CAM + "1", "desc": "Legge 7 del 1° agosto 2025 pubblicata nella Gazzetta Ufficiale n. 3 "
                                 "dell'11 agosto 2025"},
        {"a": CAM + "2", "desc": "Testo unificato"},
    ])
    assert [(r["number"], r["date"], r["gu_number"], r["gu_date"]) for r in rows] == [
        (180, "2026-10-09", 235, "2026-10-09"), (7, "2025-08-01", 3, "2025-08-11")]


def test_camera_date_wins_and_constitutional_law_matched_by_number():
    senate, _ = senate_laws([
        _phase("1", "100", "1803", "162", "2025-11-04"),
        _phase("2", "200", "13", "1", "2023-09-26", natura="costituzionale"),
    ], 19)
    camera = camera_gazette([
        {"a": CAM + "1803", "desc": "Legge 162 del 22 ottobre 2025 pubblicata nella Gazzetta Ufficiale "
                                    "n. 256 del 4 novembre 2025"},
        {"a": CAM + "715-B", "desc": "Legge 1 del 26 settembre 2023 pubblicata nella Gazzetta Ufficiale "
                                     "n. 229 del 30 settembre 2023"},
        {"a": CAM + "952", "desc": "Legge 162 del 22 ottobre 2025 pubblicata nella Gazzetta Ufficiale "
                                   "n. 256 del 4 novembre 2025"},
    ])
    bill_process = {CAM + "1803": "senato:19:iter:100", CAM + "715-B": "senato:19:iter:200",
                    CAM + "952": "senato:19:iter:300"}
    laws, merged = merge_sources(senate, camera, bill_process)
    by_urn = {law["urn"]: law for law in laws}
    assert set(by_urn) == {"urn:nir:stato:legge:2025;162", "urn:nir:stato:legge.costituzionale:2023;1"}
    assert by_urn["urn:nir:stato:legge:2025;162"]["date"] == "2025-10-22"
    assert by_urn["urn:nir:stato:legge:2025;162"]["gu_number"] == 256
    assert merged == 1


def test_law_known_only_to_the_camera_takes_its_bill_process():
    camera = camera_gazette([{"a": CAM + "50", "desc": "Legge 68 del 3 aprile 2026 pubblicata nella "
                                                       "Gazzetta Ufficiale n. 80 del 7 aprile 2026"}])
    laws, _ = merge_sources([], camera, {CAM + "50": "senato:19:iter:7"})
    assert [(law["urn"], law["processes"]) for law in laws] == [
        ("urn:nir:stato:legge:2026;68", ["senato:19:iter:7"])]


def test_normattiva_page():
    nt = parse_normattiva(NORMATTIVA_PAGE)
    assert nt == {"kind": "legge", "number": 180, "date": "2026-10-09",
                  "title": "Disposizioni in materia di elezioni della Camera dei deputati e del Senato "
                           "della Repubblica",
                  "eli": "https://www.normattiva.it/eli/id/2026/10/09/26G00201/ORIGINAL", "code": "26G00201",
                  "gu_number": 235, "gu_date": "2026-10-09", "gu_supplement": None}
    assert parse_normattiva("<title>Errore</title>") is None


def test_normattiva_supplement():
    page = NORMATTIVA_PAGE.replace("(GU n.235 del 09-10-2026)", "(GU n.305 del 31-12-2024 - Suppl. Ordinario n. 43)")
    assert parse_normattiva(page)["gu_supplement"] == "Suppl. Ordinario n. 43"


def test_normattiva_page_of_another_law_is_refused():
    nt = parse_normattiva(NORMATTIVA_PAGE)
    law = {"kind": "legge", "number": 180, "date": "2025-10-09", "gu_number": None, "gu_date": None}
    assert not apply_normattiva(law, nt) and "eli" not in law
    law = {"kind": "legge", "number": 180, "date": "2026-10-20", "gu_number": None, "gu_date": None}
    assert apply_normattiva(law, nt)
    assert law["date"] == "2026-10-09" and law["code"] == "26G00201" and law["gu_number"] == 235
