"""Rapporteurs of the bills of both chambers (card 133)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest_reporters import (camera_role, fold, match_deputy, merge_reports, senate_records, senate_role,
                              split_camera_label)

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
