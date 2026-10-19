"""Parliamentary documents (Doc.) of both chambers (card 181)."""

import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from doc_refs import DocRef, doc_keys, doc_uri, parse_doc_refs  # noqa: E402
from ingest_documents import (camera_index, camera_record_title, plan_camera, plan_processes,  # noqa: E402
                              reporter_names, title_before)
from ingest_reporters import resoconto_records  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("Doc. IV-ter, n. 13-A", [("IV-ter", "13", "A")]),
    ("(DOC. XVIII-BIS, n. 10)", [("XVIII-bis", "10", None)]),
    ("Doc. LVII, n. 1.bis)", [("LVII", "1-bis", None)]),
    ("Doc. LVII, n. 1-bis-A", [("LVII", "1-bis", "A")]),
    ("Doc. CCXXXII n. 1", [("CCXXXII", "1", None)]),
    ("Doc.LVII,n.1-A/I", [("LVII", "1", "A/I")]),
    ("Doc.LVII,n.1-Annesso-bis", [("LVII", "1", None)]),
    ("Doc. XXIV, n 16. Risoluzione", [("XXIV", "16", None)]),
    ("Doc.XXII,n.9-28-29-A", [("XXII", "9", "A"), ("XXII", "28", "A"), ("XXII", "29", "A")]),
    ("(Doc. XXII, nn. 9, 5, 6 e 11) - Istituzione", [("XXII", n, None) for n in ("9", "5", "6", "11")]),
    ("Relatrice sui documenti LXXXVI, n. 1, e LXXXVII, n. 1",
     [("LXXXVI", "1", None), ("LXXXVII", "1", None)]),
    ("Docc. LVII, n. 01-bis e LVII, 01-bis-Integrazione. Proposta di risoluzione n. 5",
     [("LVII", "01-bis", None)]),
    ("Si riprende la discussione del Doc. VIII, n. 1 e del Doc. VIII, n. 2.",
     [("VIII", "1", None), ("VIII", "2", None)]),
    ("Votazione Doc. VII", []),
    ("Organizzazione dei tempi di esame di Doc. CCXLVII e di disegni di legge.", []),
    ("di Doc. XV n. 3 e di 4", [("XV", "3", None)]),
])
def test_parse_doc_refs(text, expected):
    assert parse_doc_refs(text) == [DocRef(*e) for e in expected]


def test_doc_keys_fold_the_report_into_its_document():
    assert doc_keys("Doc. IV-ter, n. 13 e Doc. IV-ter, n. 13-A") == [("IV-ter", "13")]
    assert doc_uri("senato", 19, "LVII", "1-bis") == "senato:19:doc:LVII:1-bis"


def test_titles():
    assert camera_record_title("Documento di economia e finanza 2023 Presentato dal Presidente del Consiglio "
                               "dei ministri: MELONI SEZIONE I") == "Documento di economia e finanza 2023 SEZIONE I"
    assert camera_record_title("D'iniziativa dei deputati: RIZZETTO ed altri Istituzione di una Commissione "
                               "parlamentare di inchiesta") == "Istituzione di una Commissione parlamentare di inchiesta"
    assert camera_record_title("Presentata dalla GIUNTA PER IL REGOLAMENTO (Modifiche al Regolamento "
                               "relative ad adeguamenti)") == "Modifiche al Regolamento relative ad adeguamenti"
    assert camera_record_title("Anno 2022 Presentata dal Ministro dell'interno: PIANTEDOSI") is None
    assert camera_record_title("nei confronti del Senatore: Alessandro MORELLI") is None
    title = ("Discussione congiunta dei documenti: Conto consuntivo della Camera dei deputati per l'anno "
             "finanziario 2022 (Doc. VIII, n. 1); Progetto di bilancio della Camera dei deputati per l'anno "
             "finanziario 2023 (Doc. VIII, n. 2) (ore 10,22)")
    assert title_before(title, ("VIII", "1")) == "Conto consuntivo della Camera dei deputati per l'anno finanziario 2022"
    assert title_before(title, ("VIII", "2")) == "Progetto di bilancio della Camera dei deputati per l'anno finanziario 2023"
    assert title_before("Emendamento 2.6 MORFINO DANIELA (M5S) (Doc. XXII, n. 31-A)", ("XXII", "31")) is None


def test_reporter_names():
    assert reporter_names("Relatrice: FORATTINI Relazione della Giunta") == [("FORATTINI", "")]
    assert reporter_names("Relatore: Enrico COSTA Relazione della Giunta") == [("COSTA", "Enrico")]
    assert reporter_names("Relazione delle Commissioni riunite III e IV (Relatore per la III Commissione: "
                          "LOPERFIDO) (Relatore per la IV Commissione: FORMENTINI)") == [
        ("LOPERFIDO", ""), ("FORMENTINI", "")]


def _rec(uri, ident, title="", date="20230412", rel=None):
    return {"d": uri, "id": ident, "title": title, "type": "DOCUMENTO", "date": date, "rel": rel}


def test_camera_index_groups_the_sheets_of_a_document():
    rows = [
        _rec("doc19_LVIIn1", "Doc.LVII,n.1", "Documento di economia e finanza 2023", rel="pdf/main"),
        _rec("doc19_LVIIn1_1", "Doc.LVII,n.1", "ALLEGATI"),
        _rec("doc19_LVIIn1A", "Doc.LVII,n.1-A", "Relatore: PELLA"),
        _rec("doc19_LVIIn1bis", "Doc.LVII,n.1-bis", "Nota di aggiornamento 2023", "20230929"),
        # A NADEF 2022 sheet under a wrong number at the source (19/10/2026).
        _rec("doc19_LVIIn1BIS", "Doc.LVII,n.1-BIS", "Documento di economia e finanza 2022", "20220930"),
    ]
    idx = camera_index(rows)
    assert set(idx) == {("LVII", "1"), ("LVII", "1-bis")}
    assert idx[("LVII", "1")]["main"]["uri"] == "doc19_LVIIn1"
    assert [r["uri"] for r in idx[("LVII", "1")]["reports"]] == ["doc19_LVIIn1A"]
    assert idx[("LVII", "1-bis")]["main"]["date"] == "20230929"


def test_plan_camera_votes_and_placeholders():
    stats = Counter()
    records = camera_index([_rec("doc19_XXIIn31A", "Doc.XXII,n.31-A",
                                 "Relatrice: FORATTINI Istituzione di una Commissione di inchiesta")])
    votes = [
        {"id": "v1", "description": "Articolo 1 (Doc. XXII, n. 31-A)",
         "acts": [{"uri": "ac19_2049", "inferred": "vicini", "doc": False}]},
        {"id": "v2", "description": "Risoluzione n. 6-00031 riferita alla Relazione (Doc. LVII, n. 1)",
         "acts": [{"uri": "aic6", "inferred": None, "doc": False}]},
        {"id": "v3", "description": "Votazione finale (Doc. IV, nn. 3 e 4)", "acts": []},
    ]
    plan = plan_camera(19, records, {}, [{"number": "Doc. II, n. 5"}], votes, [], set(), stats)
    assert {n["uri"] for n in plan["nodes"]} == {
        "camera:19:doc:II:5", "camera:19:doc:XXII:31", "camera:19:doc:IV:3", "camera:19:doc:IV:4"}
    assert plan["on_act"] == [{"vote": "v1", "uri": "camera:19:doc:XXII:31"},
                              {"vote": "v3", "uri": "camera:19:doc:IV:3"},
                              {"vote": "v3", "uri": "camera:19:doc:IV:4"}]
    assert plan["drop"] == [{"vote": "v1", "uri": "ac19_2049"}]
    assert plan["reporters"][0]["name"] == ("FORATTINI", "")


def test_processes_join_the_government_documents_of_both_chambers():
    stats = Counter()
    docs = [
        {"uri": "camera:19:doc:LVII:1", "series": "LVII", "number": "1", "chamber": "camera", "date": "2023-04-12",
         "title": "DEF"},
        {"uri": "senato:19:doc:LVII:1", "series": "LVII", "number": "1", "chamber": "senato", "date": "2023-04-12",
         "title": "Documento di economia e finanza 2023"},
        {"uri": "camera:19:doc:IV-ter:3", "series": "IV-ter", "number": "3", "chamber": "camera", "date": None},
        {"uri": "senato:19:doc:IV-ter:3", "series": "IV-ter", "number": "3", "chamber": "senato", "date": None},
        {"uri": "camera:19:doc:CCXL:1", "series": "CCXL", "number": "1", "chamber": "camera", "date": "2024-01-01"},
        {"uri": "senato:19:doc:CCXL:1", "series": "CCXL", "number": "1", "chamber": "senato", "date": "2025-04-10"},
    ]
    rows = plan_processes(19, docs, stats)
    assert {(r["process"], r["uri"]) for r in rows} == {
        ("parlamento:19:doc:LVII:1", "camera:19:doc:LVII:1"), ("parlamento:19:doc:LVII:1", "senato:19:doc:LVII:1")}
    assert stats["process_date_mismatch"] == 1


def _sp(label, bills=(), docs=(), person="p"):
    return {"speech": "s1", "label": label, "person": person, "session": "leg19_sed1", "date": "2026-09-30",
            "bills": [{"uri": u, "number": n} for u, n in bills],
            "docs": [{"uri": u, "number": n, "series": s} for u, s, n in docs]}


def test_resoconto_documents():
    stats = Counter()
    out = resoconto_records([
        _sp("Relatore", docs=[("d1", "IV-ter", "3")], person="giunta"),
        _sp("Relatrice sui documenti LXXXVI, n. 1, e LXXXVII, n. 1", bills=[("b969", "969")],
            docs=[("d86", "LXXXVI", "1"), ("d87", "LXXXVII", "1")], person="docs"),
        _sp("Relatore", bills=[("b969", "969")], docs=[("d86", "LXXXVI", "1")], person="bill"),
        _sp("Relatore", docs=[("d57", "LVII", "1")], person="pella"),
        _sp("Relatrice", docs=[("d13", "IV-ter", "13")], person="standin"),
    ], {("d13", "forattini"): {"relatore"}}, stats, {("1-bis", "pella")})
    got = {(r["bill"], r["person"]): r["role"] for r in out}
    assert got == {("d1", "giunta"): "relatore", ("d86", "docs"): "relatore", ("d87", "docs"): "relatore",
                   ("b969", "bill"): "sostituto", ("d57", "pella"): "relatore", ("d13", "standin"): "sostituto"}
