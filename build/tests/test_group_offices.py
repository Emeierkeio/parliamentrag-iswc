"""Senate group offices from osr:carica (build/ingest_group_offices.py)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest_group_offices import senate_group_names, senate_offices  # noqa: E402

LEGA = "http://dati.senato.it/gruppo/1"


def test_members_skipped_and_highest_office_kept():
    rows = [
        {"senatore": "s/romeo", "gruppo": LEGA, "carica": "Presidente"},
        {"senatore": "s/bizzotto", "gruppo": LEGA, "carica": "Membro"},
        # Germanà: Vicepresidente since 2022, Tesoriere since 2025
        {"senatore": "s/germana", "gruppo": LEGA, "carica": "Tesoriere"},
        {"senatore": "s/germana", "gruppo": LEGA, "carica": "Vicepresidente"},
        {"senatore": "s/minasi", "gruppo": LEGA, "carica": "Vicepresidente Vicario"},
        {"senatore": "s/aula", "gruppo": LEGA, "carica": "Segretario d'Aula"},
    ]
    assert senate_offices(rows) == {
        "s/romeo": {"role": "president", "group": LEGA},
        "s/germana": {"role": "vice_president", "group": LEGA},
        "s/minasi": {"role": "vice_president", "group": LEGA},
        "s/aula": {"role": "secretary", "group": LEGA},
    }


def test_group_names_use_the_current_name(tmp_path):
    path = tmp_path / "gruppi.csv"
    path.write_text(
        "senatore,gruppoLabel,gruppoBreve,gruppoStart,gruppoEnd,gruppoUri,gruppoAttuale\n"
        "s/1,Forza Italia Berlusconi Presidente,FIBP,20221018,,g/56,Forza Italia - Berlusconi Presidente - PPE\n",
        encoding="utf-8")
    assert senate_group_names(str(path)) == {"g/56": "Forza Italia - Berlusconi Presidente - PPE"}
    assert senate_group_names(str(tmp_path / "missing.csv")) == {}
