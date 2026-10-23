"""Committees the bills are assigned to (card 233)."""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest_bill_committees import (CommitteeIndex, camera_records, fold, is_joint, merge_assignments,
                                    plan_writes, senate_label, senate_number, senate_organ_numbers,
                                    senate_records)

COMMITTEES = [
    {"chamber": "camera", "name": "XI COMMISSIONE (LAVORO PUBBLICO E PRIVATO)"},
    {"chamber": "camera", "name": "X COMMISSIONE (ATTIVITA'  PRODUTTIVE, COMMERCIO E TURISMO)"},
    {"chamber": "camera", "name": "IX COMMISSIONE (TRASPORTI, POSTE E TELECOMUNICAZIONI)"},
    {"chamber": "senato", "name": "2ª Commissione permanente (Giustizia)"},
    {"chamber": "senato", "name": "10ª Commissione permanente (Affari sociali, sanità, lavoro pubblico e privato, "
                                  "previdenza sociale)"},
    {"chamber": "senato", "name": "1ª Commissione permanente (Affari Costituzionali)"},
    {"chamber": "senato", "name": "Commissione parlamentare per le questioni regionali "
                                  "(Commissione parlamentare questioni regionali)"},
]
INDEX = CommitteeIndex(COMMITTEES)
S10 = "http://dati.senato.it/commissione/0-148"
S2 = "http://dati.senato.it/commissione/0-2"


def test_fold_collapses_spaces_and_apostrophes():
    assert fold("X COMMISSIONE (ATTIVITA'  PRODUTTIVE)") == fold("X Commissione (Attività produttive)")


def test_senate_label_and_number():
    assert senate_label("10&ordf; (Sanità e lavoro)") == "10ª (Sanità e lavoro)"
    assert senate_number("10&ordf; (Sanità e lavoro)") == 10
    assert senate_number("1&ordf; (Aff. costituzionali)") == 1
    assert senate_number("Commissioni riunite 2&ordf; (Giustizia) 10&ordf; (Affari sociali) 10&ordf; ") is None
    assert senate_number(" Questioni regionali") is None
    assert is_joint("Commissioni riunite 2&ordf; (Giustizia)")
    assert is_joint("Assegnato  alle Commissioni riunite VII Cultura e XII Affari sociali in sede Referente")
    assert not is_joint("Assegnato  alla XI Commissione Lavoro in sede Referente il 13 febbraio 2024")


def test_index_resolves_both_chambers():
    assert INDEX.camera("X COMMISSIONE (ATTIVITA' PRODUTTIVE, COMMERCIO E TURISMO)") == \
        ("camera", "X COMMISSIONE (ATTIVITA'  PRODUTTIVE, COMMERCIO E TURISMO)")
    assert INDEX.camera("COMMISSIONE SPECIALE") is None
    assert INDEX.senate(2, "") == ("senato", "2ª Commissione permanente (Giustizia)")
    assert INDEX.senate(None, " Questioni regionali")[1].startswith("Commissione parlamentare per le questioni")
    assert INDEX.senate(None, " Comitato legislazione") is None
    assert INDEX.senate(7, "") is None


def test_camera_records():
    rows = [
        {"a": "ac19_1", "sede": "Referente", "date": "20240213", "committee": "XI COMMISSIONE (LAVORO PUBBLICO E PRIVATO)",
         "title": "Assegnato  alla XI Commissione Lavoro in sede Referente il 13 febbraio 2024"},
        {"a": "ac19_2", "sede": "Referente", "date": "20231023", "committee": "IX COMMISSIONE (TRASPORTI, POSTE E TELECOMUNICAZIONI)",
         "title": "Assegnato  alle Commissioni riunite X Attività produttive e IX Trasporti in sede Referente"},
        {"a": "ac19_2", "sede": "Referente", "date": "20231023",
         "committee": "X COMMISSIONE (ATTIVITA'  PRODUTTIVE, COMMERCIO E TURISMO)",
         "title": "Assegnato  alle Commissioni riunite X Attività produttive e IX Trasporti in sede Referente"},
        {"a": "ac19_3", "sede": "Referente", "date": "20230101", "committee": "COMMISSIONE SPECIALE", "title": ""},
        {"a": "ac19_9", "sede": "Referente", "date": "20230101", "committee": "XI COMMISSIONE (LAVORO PUBBLICO E PRIVATO)"},
    ]
    stats = Counter()
    out = camera_records(rows, INDEX, {"ac19_1", "ac19_2", "ac19_3"}, stats)
    assert [(r["bill"], r["committee"][:3], r["joint"], r["date"]) for r in out] == [
        ("ac19_1", "XI ", False, "2024-02-13"), ("ac19_2", "IX ", True, "2023-10-23"),
        ("ac19_2", "X C", True, "2023-10-23")]
    assert stats["camera_committee_unresolved"] == 1 and stats["camera_bill_missing"] == 1


def test_senate_records_numbers_joint_organs_from_single_assignments():
    rows = [
        {"ddl": "d1", "tipo": "primaria", "sede": "redigente", "label": "10&ordf; (Affari sociali)", "organo": S10,
         "data": "2026-10-21"},
        {"ddl": "d1", "tipo": "consultiva", "sede": "", "label": "2&ordf; (Giustizia)", "organo": S2,
         "data": "2026-10-21"},
        {"ddl": "d1", "tipo": "consultiva", "sede": "", "label": " Questioni regionali",
         "organo": "http://dati.senato.it/commissione/4-40", "data": "2026-10-21"},
        {"ddl": "d1", "tipo": "consultiva", "sede": "", "label": " Comitato legislazione",
         "organo": "http://dati.senato.it/commissione/0-149", "data": "2026-10-21"},
        {"ddl": "d2", "tipo": "primaria", "sede": "referente",
         "label": "Commissioni riunite 2&ordf; (Giustizia) 10&ordf; (Affari sociali) 10&ordf; ", "organo": S2,
         "data": "2024-01-10"},
        {"ddl": "d2", "tipo": "primaria", "sede": "referente",
         "label": "Commissioni riunite 2&ordf; (Giustizia) 10&ordf; (Affari sociali) 10&ordf; ", "organo": S10,
         "data": "2024-01-10"},
    ]
    assert senate_organ_numbers(rows) == {S10: 10, S2: 2}
    stats = Counter()
    out = senate_records(rows, INDEX, {"d1", "d2"}, stats)
    got = {(r["bill"], r["committee"].split(" ")[0], r["sede"], r["mode"], r["joint"]) for r in out}
    assert got == {
        ("d1", "10ª", "referente", "redigente", False), ("d1", "2ª", "consultiva", None, False),
        ("d1", "Commissione", "consultiva", None, False),
        ("d2", "2ª", "referente", "referente", True), ("d2", "10ª", "referente", "referente", True)}
    assert stats["senato_committee_unresolved_consultiva"] == 1


def test_merge_keeps_first_date_and_latest_mode():
    rec = {"bill": "d1", "chamber": "senato", "committee": "2ª", "sede": "referente", "joint": False,
           "source": "dati.senato.it"}
    merged = merge_assignments([{**rec, "mode": "redigente", "date": "2024-05-01"},
                                {**rec, "mode": "referente", "date": "2023-01-10", "joint": True},
                                {**rec, "sede": "consultiva", "mode": None, "date": "2023-01-10"}])
    assert [(m["sede"], m["mode"], m["date"], m["joint"]) for m in merged] == [
        ("consultiva", None, "2023-01-10", False), ("referente", "redigente", "2023-01-10", True)]


def test_plan_writes_only_new_or_changed():
    base = {"bill": "b", "chamber": "camera", "committee": "XI", "sede": "referente", "mode": "referente",
            "date": "2024-02-13", "joint": False, "source": "dati.camera.it"}
    same = dict(base)
    changed = {**base, "bill": "c", "joint": True}
    new = {**base, "bill": "d"}
    existing = [dict(base), {**base, "bill": "c"}, {**base, "bill": "gone"}]
    todo, stale = plan_writes([same, changed, new], existing)
    assert [t["bill"] for t in todo] == ["c", "d"]
    assert [s["bill"] for s in stale] == ["gone"]
