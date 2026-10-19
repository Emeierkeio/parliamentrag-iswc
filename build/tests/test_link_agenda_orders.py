"""Agenda orders linked to their bill, with the outcome (card 132)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from link_agenda_orders import (bill_of_camera_uri, bill_of_number, match_senate_outcomes,
                                outcome_from_votes, senate_outcome)

AIC = "http://dati.camera.it/ocd/aic.rdf/"


@pytest.mark.parametrize("number, expected", [
    ("9/02911-A/028", ("2911", "A")),
    ("9/02355/020", ("2355", None)),
    ("9/00889-AR/041", ("889", "AR")),
    ("9/00643-bis-AR/185", ("643-bis", "AR")),
    ("9/01532-ter-A/005", ("1532-ter", "A")),
    ("9/00384-B/002", ("384-B", None)),
    ("0/01980/001/07", ("1980", None)),
    ("0/00643-bis/001/09", ("643-bis", None)),
    ("9/00924-BIS/002", ("924-bis", None)),
    ("0/01891-B/003/06", ("1891-B", None)),
    ("9/DOC.VIII,N.6/031", None),
    ("9/DOC.XXIV,NN.45-46-47-48/682", None),
    ("9/1-00121/001", None),
    (None, None),
])
def test_bill_of_number(number, expected):
    assert bill_of_number(number) == expected


@pytest.mark.parametrize("uri, expected", [
    ("aic9_02753_001_19", ("2753", None)),
    ("aic9_02911_A_028_19", ("2911", "A")),
    ("aic9_01532_bis_003_19", ("1532-bis", None)),
    ("aic9_00643_BIS_173_19", ("643-bis", None)),
    ("aic9_00889_R_007_19", ("889", "AR")),
    ("aic9_01928_A_R_002_19", ("1928", "AR")),
    ("aic9_1633A_119_19", ("1633", "A")),
    ("aic0_01980_001_07_19", ("1980", None)),
    ("aic0_00643_bis_001_09_19", ("643-bis", None)),
    ("aic9_00384_B_002_19", ("384-B", None)),
    ("aic9_DocVIII,n2_015_19", None),
    ("aic9_I,n31_A_001_19", None),
    ("aic9_02029_002_19_S", None),
])
def test_bill_of_camera_uri(uri, expected):
    assert bill_of_camera_uri(AIC + uri) == expected


def test_outcome_from_votes():
    assert outcome_from_votes(["rejected"]) == "respinto"
    assert outcome_from_votes(["approved", "approved"]) == "approvato"
    assert outcome_from_votes(["approved", "rejected"]) == "approvato_in_parte"
    assert outcome_from_votes([None]) is None


@pytest.mark.parametrize("raw, expected", [
    ("Respinto", "respinto"),
    ("Accolto", "accolto"),
    ("accolto dal Governo", "accolto"),
    ("Accoto come raccomandazione", "accolto_come_raccomandazione"),
    ("Accolto con raccomandazione", "accolto_come_raccomandazione"),
    ("Non accolto", "non_accolto"),
    ("V. testo 2", "riformulato"),
    ("Ritirato. Vedi testo 2", "riformulato"),
    ("Ritirato", "ritirato"),
    ("Precluso", "precluso"),
    ("Non posto in votazione (*)", "non_posto_in_votazione"),
    ("Improponibile", "inammissibile"),
    ("Improponibile limitatamente all'ultima premessa e al secondo impegno", "altro"),
    ("Id. odg G11.4", "assorbito"),
    ("Votato per parti separate. Respinta la parte evidenziata in neretto; accolta la restante parte", "altro"),
    (None, None),
])
def test_senate_outcome(raw, expected):
    assert senate_outcome(raw) == expected


def _g(numero, sede, testo, esito, atto="S.1484-B"):
    return {"numero": numero, "sede": sede, "testo": testo, "esito": esito, "atto": atto,
            "atti_congiunti": [], "fonte": f"https://www.senato.it/{numero}"}


def test_senate_outcome_matched_by_text_within_bill_and_venue():
    orders = [
        {"uri": "o1", "number": "9/01484-B/001", "text": "impegna il governo agevolazioni fiscali reti imprese beni usati"},
        {"uri": "o2", "number": "9/01484-B/002", "text": "impegna il governo false recensioni online regolamento servizi digitali"},
        {"uri": "o3", "number": "0/01484-B/001/10", "text": "impegna il governo agevolazioni fiscali reti imprese beni usati"},
    ]
    g = [_g("G1.100", "assemblea", "agevolazioni fiscali reti imprese beni usati governo impegna", "Ritirato"),
         _g("G1.101", "assemblea", "false recensioni online regolamento servizi digitali impegna governo", "Accolto")]
    out, stats = match_senate_outcomes(orders, g)
    assert out["o1"]["outcome"] == "ritirato" and out["o2"]["outcome"] == "accolto"
    assert out["o2"]["url"] == "https://www.senato.it/G1.101"
    assert "o3" not in out and stats["senato_no_candidates"] == 1


def test_senate_near_identical_texts_with_different_outcomes_are_skipped():
    text = "impegna il governo a valutare misure sostegno famiglie numerose"
    orders = [{"uri": "o1", "number": "9/01484-B/001", "text": text}]
    g = [_g("G1.100", "assemblea", text, "V. testo 2"), _g("G1.100 (testo 2)", "assemblea", text, "Accolto")]
    out, stats = match_senate_outcomes(orders, g)
    assert out == {} and stats["senato_ambiguous"] == 1
