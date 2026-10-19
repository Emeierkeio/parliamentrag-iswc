"""Rapporteurs of the bills of both chambers (card 133)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest_reporters import (RETRACT, ROLE_ORDER, SOURCES, STALE_COUNT, WRITE, camera_role, fold, match_deputy,
                              merge_reports, pages_to_fetch, parse_scheda, resoconto_records, scheda_roles,
                              senate_records, senate_role, split_camera_label)

DEPUTIES = {
    (fold("SCHIFONE"), fold("MARTA")): "p1",
    (fold("D'ALESSIO"), fold("ANTONIO")): "p2",
    (fold("IEZZI"), fold("IGOR GIANCARLO")): "p3",
    (fold("SACCANI"), fold("GLORIA")): "p4",
    (fold("ROSSI"), fold("MARIO")): "p5",
    (fold("ROSSI"), fold("LUCA")): "p6",
    (fold("DI SANZO"), fold("CHRISTIAN DIEGO")): "p7",
}


@pytest.mark.parametrize("label, expected", [
    ("SCHIFONE Marta, relatore per la maggioranza", ("SCHIFONE", "MARTA")),
    ("D'ALESSIO Antonio, relatore di minoranza", ("D ALESSIO", "ANTONIO")),
    ("DI SANZO Christian", ("DI SANZO", "CHRISTIAN")),
    ("SACCANI JOTTI Gloria, relatore per la Commissione  IV Difesa", ("SACCANI JOTTI", "GLORIA")),
    ("Relatore", None),
    (None, None),
])
def test_split_camera_label(label, expected):
    assert split_camera_label(label) == expected


@pytest.mark.parametrize("label, expected", [
    ("SCHIFONE Marta, relatore per la maggioranza", "p1"),
    ("D'ALESSIO Antonio", "p2"),
    ("IEZZI Igor", "p3"),
    ("SACCANI JOTTI Gloria", "p4"),
    ("ROSSI Mario", "p5"),
    ("ROSSI Giulia", None),
    ("DI SANZO Christian", "p7"),
    ("BIANCHI Anna", None),
])
def test_match_deputy(label, expected):
    assert match_deputy(split_camera_label(label), DEPUTIES) == expected


def test_roles():
    assert camera_role("maggioranza", "X Y, relatore per la maggioranza") == "maggioranza"
    assert camera_role(None, "BICCHIELLI Pino, relatore per la Commissione IV Difesa, per la maggioranza") == "maggioranza"
    assert camera_role(None, "SCHIFONE Marta") == "relatore"
    assert senate_role("relatore", "1") == "minoranza"
    assert senate_role("facente funzione", "0") == "facente_funzione"
    assert senate_role("sostituto", "0") == "sostituto"
    assert senate_role("relatore", "0") == "relatore"


def test_merge_keeps_one_relationship_per_bill_and_person():
    recs = [
        {"bill": "b", "person": "p", "role": "relatore", "date": "2023-01-17", "venue": "assemblea",
         "committee": None, "source": "s"},
        {"bill": "b", "person": "p", "role": "relatore", "date": "2022-12-13", "venue": "commissione",
         "committee": None, "source": "s"},
        {"bill": "b", "person": "q", "role": "facente_funzione", "date": None, "venue": "commissione",
         "committee": None, "source": "s"},
        {"bill": "c", "person": "p", "role": "maggioranza", "date": None, "venue": None, "committee": "XI", "source": "s"},
        {"bill": "c", "person": "p", "role": "relatore", "date": None, "venue": None, "committee": "XI", "source": "s"},
    ]
    out = {(m["bill"], m["person"]): m for m in merge_reports(recs)}
    assert len(out) == 3
    assert out[("b", "p")]["date"] == "2022-12-13"
    assert out[("b", "p")]["venues"] == ["assemblea", "commissione"]
    assert out[("c", "p")]["role"] == "maggioranza" and out[("c", "p")]["roles_raw"] == ["maggioranza", "relatore"]
    assert out[("b", "q")]["role"] == "facente_funzione"


def test_senate_records_skip_unknown_bills_and_people():
    from collections import Counter
    rows = [{"ddl": "d1", "sen": "s1", "tipo": "relatore", "min": "0", "data": "2023-05-03", "organo": "commissione"},
            {"ddl": "d2", "sen": "s1", "tipo": "relatore", "min": "0", "data": "", "organo": ""},
            {"ddl": "d1", "sen": "s9", "tipo": "relatore", "min": "0", "data": "", "organo": ""}]
    stats = Counter()
    out = senate_records(rows, {"s1": "P1"}, {"d1"}, stats)
    assert out == [{"bill": "d1", "person": "P1", "role": "relatore", "date": "2023-05-03",
                    "venue": "commissione", "committee": None, "source": "dati.senato.it"}]
    assert stats["senato_bill_missing"] == 1 and stats["senato_person_missing"] == 1


def _person(pid: str, name: str) -> str:
    return (f'<a href="https://documenti.camera.it/apps/commonServices/getDocumento.ashx?sezione=deputati'
            f'&amp;tipoDoc=schedaDeputato&amp;idlegislatura=19&amp;idPersona={pid}" title="x" '
            f'target="_blank">{name}</a>')


def _speech(pid: str, name: str, label: str, section: str) -> str:
    return (f'<li><span>{_person(pid, name)}</span> (FDI)<em>, {label}</em> pag. '
            f'<a href="https://documenti.camera.it/apps/commonServices/getDocumento.ashx?idLegislatura=19'
            f'&amp;sezione={section}&amp;tipoDoc=x">32</a></li>')


# Shape of www.camera.it/leg19/126?leg=19&idDocumento=1275, 19/10/2026.
PAGE = f"""<h2>Atto Camera: 1275</h2>
<div class="relatori">
            <div class="inCommissione">
<span class="label">Relatori in Commissione:</span><ul><li><span>{_person("1", "SCHIFONE Marta")}</span></li></ul>
</div>
            <div class="inAssemblea">
<span class="label">Relatori in Assemblea:</span><ul>
<li>
<span>{_person("1", "SCHIFONE Marta")}</span> (<em>per la maggioranza</em>)</li>
<li><span>{_person("2", "MARI Francesco")}</span></li>
</ul>
</div>
        </div>
<ul>
{_speech("3", "PELLA Roberto", "Relatore per la commissione", "bollettini")}
{_speech("4", "SCOTTO Arturo", "Relatore di minoranza", "assemblea")}
{_speech("1", "SCHIFONE Marta", "Relatore per la maggioranza", "assemblea")}
{_speech("5", "CERRETO Marco", "Relatore per la commissione", "assemblea")}
{_speech("6", "SBARDELLA Luca", "Relatore f.f.", "assemblea")}
{_speech("7", "RIZZETTO Walter", "Presidente", "assemblea")}
</ul>"""


def test_parse_scheda_reads_the_box_and_the_floor_labels():
    parsed = parse_scheda(PAGE)
    assert parsed["header"] == [
        {"venue": "commissione", "pid": "1", "name": "SCHIFONE Marta", "note": ""},
        {"venue": "assemblea", "pid": "1", "name": "SCHIFONE Marta", "note": "per la maggioranza"},
        {"venue": "assemblea", "pid": "2", "name": "MARI Francesco", "note": ""},
    ]
    assert [(a["pid"], a["label"]) for a in parsed["aula"]] == [
        ("4", "Relatore di minoranza"), ("1", "Relatore per la maggioranza"),
        ("5", "Relatore per la commissione"), ("6", "Relatore f.f."),
    ]


def test_scheda_roles():
    roles = {(r["pid"], r["venue"], r["role"]) for r in scheda_roles(parse_scheda(PAGE))}
    assert roles == {
        ("1", "commissione", "relatore"), ("1", "assemblea", "maggioranza"),
        ("2", "assemblea", "minoranza"),  # unmarked next to a "per la maggioranza"
        ("4", "assemblea", "minoranza"), ("5", "assemblea", "sostituto"), ("6", "assemblea", "facente_funzione"),
    }


def test_scheda_roles_without_split_floor_keep_plain_rapporteurs():
    page = parse_scheda(PAGE.replace("(<em>per la maggioranza</em>)", ""))
    roles = {(r["pid"], r["venue"]): r["role"] for r in scheda_roles(page)}
    assert roles[("2", "assemblea")] == "relatore"


def test_pages_to_fetch_reads_new_changed_and_newly_debated_bills():
    cache = {"1": {"fetched_at": "2026-10-10T10:00:00Z"}, "2": {"fetched_at": "2026-10-10T10:00:00Z"},
             "3": {"fetched_at": "2026-10-10T10:00:00Z"}}
    bills = [{"number": "1", "modified": "2026-10-09T00:00:00Z", "last_debate": "2026-10-01"},
             {"number": "2", "modified": "2026-10-11T00:00:00Z", "last_debate": None},
             {"number": "3", "modified": None, "last_debate": "2026-10-12"},
             {"number": "4", "modified": None, "last_debate": None}]
    assert [b["number"] for b in pages_to_fetch(bills, cache, 10)] == ["3", "2", "4"]
    assert len(pages_to_fetch(bills, cache, 1)) == 1


def _sp(label, bills, person="p", speech="s1"):
    return {"speech": speech, "label": label, "person": person, "session": "leg19_sed1", "date": "2026-09-30",
            "bills": [{"uri": u, "number": n} for u, n in bills]}


def test_resoconto_records():
    from collections import Counter
    stats = Counter()
    other = {("b1", "listed"): {"relatore"}, ("b1", "major"): {"maggioranza"}}
    out = resoconto_records([
        _sp("Relatore di minoranza", [("b1", "1")], person="new"),
        _sp("Relatore", [("b1", "1")], person="standin"),
        _sp("Relatrice di minoranza per la I Commissione", [("b1", "1")], person="listed"),
        _sp("Relatore di minoranza", [("b1", "1")], person="major"),
        _sp("Relatore", [("b1", "1")], person="listed"),
        _sp("Relatore sul disegno di legge n. 792", [("b1", "791"), ("b2", "792")], person="joint"),
        _sp("Relatore sui documenti LXXXVI, n. 1", [("b1", "1")], person="doc"),
    ], other, stats)
    got = {(r["bill"], r["person"]): r["role"] for r in out}
    assert got == {("b1", "new"): "minoranza", ("b1", "standin"): "sostituto",
                   ("b1", "listed"): "minoranza", ("b2", "joint"): "sostituto"}
    assert all(r["source"] == "resoconto" and r["session"] == "leg19_sed1" for r in out)
    assert stats["resoconto_side_conflict"] == 1 and stats["resoconto_label_on_document"] == 1


def test_resoconto_skips_the_rapporteur_of_a_split_bill():
    from collections import Counter
    stats = Counter()
    out = resoconto_records([_sp("Relatore", [("b1532", "1532")], person="ciocchetti")], {}, stats,
                            {("1532-ter", "ciocchetti")})
    assert out == [] and stats["resoconto_split_bill_speeches"] == 1


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEO4J_PASSWORD"), reason="NEO4J_PASSWORD not set")
def test_sources_attest_one_edge_and_retract_only_their_own():
    """Run the write queries on a scratch graph inside a transaction that is rolled back."""
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://localhost:7689"),
                                  auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    params = {"roles": ROLE_ORDER, "sources": SOURCES}

    def row(source, role, person="T:p1", session=None):
        return {"bill": "T:b1", "person": person, "role": role, "roles_raw": [role], "date": None,
                "venues": ["assemblea"], "committee": None, "source": source, "session": session}

    def edges(tx):
        return {r["p"]: r for r in tx.run("""
            MATCH (:Bill {uri: 'T:b1'})-[r:REPORTED_BY]->(p) RETURN p.id AS p, r.role AS role,
            r.roles_raw AS roles_raw, r.source AS source, r.sources AS sources, r.session AS session""")}

    try:
        with driver.session() as session:
            tx = session.begin_transaction()
            try:
                tx.run("""CREATE (:ParliamentaryAct:Bill {uri: 'T:b1', chamber: 'camera', number: '1'}),
                          (:Person {id: 'T:p1'}), (:Person {id: 'T:p2'})""")
                tx.run("""MATCH (b:Bill {uri: 'T:b1'}), (p:Person {id: 'T:p1'})
                          CREATE (b)-[:REPORTED_BY {role: 'relatore', roles_raw: ['relatore'],
                                                    source: 'dati.camera.it'}]->(p)""")
                tx.run(WRITE, rows=[row("scheda_camera", "minoranza"), row("resoconto", "sostituto", "T:p2", "s9")],
                       **params)
                e = edges(tx)
                assert e["T:p1"]["role"] == "minoranza" and e["T:p1"]["source"] == "dati.camera.it"
                assert e["T:p1"]["sources"] == ["dati.camera.it", "scheda_camera"]
                assert e["T:p2"]["role"] == "sostituto" and e["T:p2"]["session"] == "s9"
                tx.run(WRITE, rows=[row("dati.camera.it", "relatore")], **params)
                assert edges(tx)["T:p1"]["role"] == "minoranza"
                stale = list(tx.run(STALE_COUNT, chamber="camera", bills=None, source="resoconto", keep=[]))
                assert [(s["person"], s["orphan"]) for s in stale] == [("T:p2", True)]
                tx.run(RETRACT, chamber="camera", bills=["T:b1"], source="scheda_camera", keep=[], **params)
                e = edges(tx)
                assert e["T:p1"]["role"] == "relatore" and e["T:p1"]["sources"] == ["dati.camera.it"]
                tx.run(RETRACT, chamber="camera", bills=None, source="resoconto", keep=[], **params)
                assert set(edges(tx)) == {"T:p1"}
            finally:
                tx.rollback()
    finally:
        driver.close()
