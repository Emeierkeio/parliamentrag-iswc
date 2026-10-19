"""Resumed debates and split bills linked to the bills they discuss."""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from link_resumed_debates import (  # noqa: E402
    camera_key,
    camera_split_keys,
    camera_title_keys,
    clean_title,
    is_bare_resumption,
    plan_camera,
    plan_senate,
    senate_index,
    senate_lookup,
    senate_title_numbers,
)

AC = "http://dati.camera.it/ocd/attocamera.rdf/ac19_"


def test_camera_keys_follow_the_readings():
    assert camera_key("1660-A") == "1660"
    assert camera_key("1234-A/R") == "1234"
    assert camera_key("2822-B") == "2822-B"
    assert camera_key("643-bis-A") == "643-bis"
    assert camera_key("536-891-910-B") == "536-B"


def test_titles():
    assert clean_title("Si riprende la discussione del disegno di legge n. 2316-A (ore 15,05).\xa0(ore 15,05)\xa0.") \
        == "Si riprende la discussione del disegno di legge n. 2316-A"
    assert clean_title("(13) - Modifica") == "(13) - Modifica"
    assert is_bare_resumption("Si riprende la discussione.")
    assert is_bare_resumption("Si riprende la discussione (16,40).\xa0(16,40)")
    assert not is_bare_resumption("Si riprende la discussione del disegno di legge n. 1555.")
    assert camera_title_keys("Si riprende la discussione del disegno di legge n. 2112-bis-A.\xa0bis") == ["2112-bis"]
    assert camera_title_keys("Si riprende l'esame del disegno di legge n. 1555.") == ["1555"]
    assert camera_title_keys("Sul rinvio in Commissione del disegno di legge n. 1665.") == ["1665"]
    assert camera_title_keys("Trasferimento a Commissione in sede legislativa della proposta di legge n. 12.") == []
    assert camera_split_keys("Seguito della discussione del disegno di legge: Disposizioni (Già articoli 10, 11 "
                             "e 13 del disegno di legge n. 1532 - Stralcio) (A.C. 1532-ter-A).") == ["1532-ter"]
    assert camera_split_keys("Bilancio di previsione (A.C. 643-bis-A/R); Nota di variazioni") == ["643-bis"]
    assert camera_split_keys("Discussione del disegno di legge (A.C. 1660-A)") == []


def test_senate_numbers():
    assert senate_title_numbers("Ripresa della discussione del disegno di legge n. 180-1041 - Alunni") == ["180-1041"]
    assert senate_title_numbers("Discussione e approvazione, in prima deliberazione, del disegno di legge "
                                "costituzionale: (13) - Modifica all'articolo 33") == ["13"]
    assert senate_title_numbers("Ripresa della discussione del documento: (Doc. CCXL, n. 2) - DPF 2026") == []
    assert senate_title_numbers("Per l'inserimento all'ordine del giorno del disegno di legge n. 12") == []
    index = senate_index([("u180", "180"), ("u1041", "1041"), ("u93", "93-338-353-B")])
    assert senate_lookup("180-1041", index) == ["u180", "u1041"]
    assert senate_lookup("338", index) == ["u93"]
    assert senate_lookup("999", index) == []


def _deb(i, title, bills=(), sitting=1):
    return {"id": f"s{sitting}_tit{i:03d}", "title": title, "order": i, "sitting": sitting,
            "bills": [AC + b for b in bills], "linked": bool(bills)}


def test_plan_camera():
    first = [
        _deb(1, "Discussione della proposta di legge: X (A.C. 887-A).", ["887", "1026", "342"], sitting=1),
    ]
    second = [
        _deb(1, "Missioni."),
        _deb(2, "Seguito della discussione del disegno di legge: Bilancio (A.C. 643-bis-A).", ["643"], sitting=2),
        _deb(3, "Sull'ordine dei lavori.", sitting=2),
        _deb(4, "Svolgimento di interrogazioni a risposta immediata.", sitting=2),
        _deb(5, "Si riprende la discussione.", sitting=2),
        _deb(6, "Si riprende la discussione della proposta di legge n. 887-A e abbinate.", sitting=2),
        _deb(7, "Si riprende la discussione.", sitting=2),
        _deb(8, "Comunicazioni del Governo.", sitting=2),
        _deb(9, "Si riprende la discussione.", sitting=2),
    ]
    uris = {AC + k for k in ("643", "643-bis", "887", "1026", "342")}
    stats = Counter()
    rows = plan_camera({"a": first, "b": second}, 19, uris, stats)
    got = {(r["debate"].split("_")[1], r["uri"].rsplit("_", 1)[1], r["via"]) for r in rows}
    assert got == {
        ("tit002", "643-bis", "titolo"),
        ("tit005", "643", "ripresa"), ("tit005", "643-bis", "ripresa"),
        ("tit006", "887", "titolo"), ("tit006", "1026", "ripresa"), ("tit006", "342", "ripresa"),
        ("tit007", "887", "ripresa"), ("tit007", "1026", "ripresa"), ("tit007", "342", "ripresa"),
    }
    assert stats["camera_bare_without_bill"] == 1


def test_bare_resumption_of_a_document_debate():
    # Sitting 545, 08/09/2025: the Giunta's report on Doc. IV-bis, n. 1.
    debates = [
        _deb(1, "Sull'ordine dei lavori."),
        {**_deb(2, "Discussione della Relazione della Giunta per le autorizzazioni sulla domanda di "
                   "autorizzazione a procedere in giudizio (Doc. IV-bis, n. 1-A)."),
         "docs": ["camera:19:doc:IV-bis:1"], "linked": True},
        _deb(3, "Preavviso di votazioni elettroniche (ore 10,57)."),
        _deb(4, "Si riprende la discussione."),
    ]
    rows = plan_camera({"a": debates}, 19, set(), Counter())
    assert rows == [{"debate": "s1_tit004", "uri": "camera:19:doc:IV-bis:1", "via": "ripresa"}]


def test_plan_senate():
    debates = [
        {"id": "d1", "title": "Discussione del disegno di legge: (274) - Benefici", "order": 1,
         "bills": [], "linked": False},
        {"id": "d2", "title": "Ripresa della discussione del disegno di legge n. 180-1041 - Alunni", "order": 2,
         "bills": [], "linked": False},
        {"id": "d3", "title": "Ripresa della discussione del documento: (Doc. LVII, n. 1) - DEF 2023", "order": 3,
         "bills": [], "linked": False},
    ]
    index = senate_index([("u274", "274"), ("u180", "180"), ("u1041", "1041")])
    rows = plan_senate({"s": debates}, index, Counter())
    assert {(r["debate"], r["uri"]) for r in rows} == {("d1", "u274"), ("d2", "u180"), ("d2", "u1041")}
