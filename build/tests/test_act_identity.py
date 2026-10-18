"""Readings grouped into legislative processes (decision D2)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migrate_act_identity import processes

CAM = "http://dati.camera.it/ocd/attocamera.rdf/ac19_"
SEN = "http://dati.senato.it/ddl/"


def _phase(ddl, iter_id, ramo, numero, date):
    return {"ddl": ddl, "idDdl": iter_id, "ramo": ramo, "numero": numero,
            "dataPresentazione": date, "titolo": "Legge X"}


def test_navetta_across_chambers_in_date_order():
    phases = [_phase(SEN + "58001", "7", "S", "816", "2023-07-21"),
              _phase(SEN + "9", "7", "C", "107", "2022-10-13"),
              _phase(SEN + "10", "7", "C", "107-B", "2024-09-18")]
    rows = processes(phases, 19, {CAM + "107": "107", CAM + "107-B": "107-B"}, {SEN + "58001"})
    assert [(r["uri"], r["reading"], r["chamber"]) for r in rows] == [
        (CAM + "107", 1, "camera"), (SEN + "58001", 2, "senato"), (CAM + "107-B", 3, "camera")]
    assert rows[0]["next"] == SEN + "58001" and rows[2]["next"] is None
    assert {r["process"] for r in rows} == {"senato:19:iter:7"}


def test_chamber_bill_unknown_to_the_senate_gets_its_own_process():
    rows = processes([], 19, {CAM + "2950": "2950"}, set())
    assert rows == [{"process": "camera:19:ac:2950", "uri": CAM + "2950", "reading": 1,
                     "chamber": "camera", "title": None, "next": None}]


def test_phases_missing_from_the_graph_are_skipped():
    rows = processes([_phase(SEN + "1", "8", "S", "5", "2023-01-01")], 19, {}, set())
    assert rows == []


def test_unified_text_found_by_number():
    phases = [_phase(SEN + "1", "9", "C", "536-891-910", "2023-01-01"),
              _phase(SEN + "2", "9", "C", "536-891-910-B", "2024-01-01")]
    bills = {CAM + "536": "536-891-910", CAM + "536-B": "536-891-910-B"}
    rows = processes(phases, 19, bills, set())
    assert [r["uri"] for r in rows] == [CAM + "536", CAM + "536-B"]
