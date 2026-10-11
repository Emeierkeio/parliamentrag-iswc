"""Senate group memberships: renamed groups and adhesions left open at the source."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_builder import _close_superseded_memberships
import download_senators_csv as dsc


def _memberships(rows):
    return pd.DataFrame(rows, columns=["senatore", "gruppoStart", "gruppoEnd"], dtype=str)


def test_open_membership_closed_before_next_one():
    # Germanà, Lega: two open adhesions at dati.senato.it
    df = _memberships([
        ["s/1116", "20221018", "20221107"],
        ["s/1116", "20221108", None],
        ["s/1116", "20250225", None],
    ])
    out = _close_superseded_memberships(df, "senatore", "gruppoStart", "gruppoEnd")
    assert list(out["gruppoEnd"].fillna("")) == ["20221107", "20250224", ""]


def test_other_people_untouched():
    df = _memberships([["s/1", "20221018", None], ["s/2", "20230101", None]])
    out = _close_superseded_memberships(df, "senatore", "gruppoStart", "gruppoEnd")
    assert out["gruppoEnd"].isna().all()


def test_current_group_name_and_aliases(monkeypatch):
    fi = "http://dati.senato.it/gruppo/fi"
    names = [
        {"gruppo": fi, "titolo": "Forza Italia", "breve": "FI", "inizio": "2001-05-30", "fine": "2008-04-28"},
        {"gruppo": fi, "titolo": "Forza Italia Berlusconi Presidente", "breve": "FIBP", "inizio": "2022-10-13", "fine": "2023-11-20"},
        {"gruppo": fi, "titolo": "Forza Italia - Berlusconi Presidente - PPE", "breve": "FI-BP-PPE", "inizio": "2023-11-21"},
    ]
    monkeypatch.setattr(dsc, "sparql_query", lambda q: names)
    # Lotito joined under the old name and never changed adhesion
    rows = [{"senatore": "s/lotito", "gruppoUri": fi, "gruppoStart": "20221018",
             "gruppoLabel": "Forza Italia Berlusconi Presidente"}]
    dsc._add_current_group_names(rows, 19)
    assert rows[0]["gruppoAttuale"] == "Forza Italia - Berlusconi Presidente - PPE"
    assert rows[0]["gruppoAttualeBreve"] == "FI-BP-PPE"
    # "Forza Italia" (2001-2008) is the same URI in an older legislature
    assert rows[0]["gruppoAlias"].split("|") == [
        "Forza Italia Berlusconi Presidente",
        "Forza Italia - Berlusconi Presidente - PPE",
    ]
