"""Family and kind of acts whose writer does not know them (decision D1)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from act_kinds import act_kind, senate_bill_kind, valid


def test_senate_bill_by_nature_and_initiative():
    assert senate_bill_kind("di conversione di decreto-legge", "governo") == ("Bill", "ddl_conversione_dl")
    assert senate_bill_kind("costituzionale", "governo") == ("Bill", "ddl_costituzionale")
    assert senate_bill_kind("costituzionale", "parlamentare") == ("Bill", "pdl_costituzionale")
    assert senate_bill_kind("ordinaria", "regionale") == ("Bill", "pdl_ordinaria")


def test_agenda_order_known_only_by_uri():
    assert act_kind("http://dati.camera.it/ocd/aic.rdf/aic9_00005_009_19", None) == ("AgendaOrder", "odg_assemblea")


def test_placeholders():
    assert act_kind("placeholder:doc:Doc. CCXL, n. 1", "doc") == ("ParliamentaryDocument", "doc")
    assert act_kind("placeholder:pdl:547", "pdl") == ("Bill", "pdl_ordinaria")


def test_senate_oversight_wordings():
    assert act_kind("senato:19:aic:9/01689/059", "ODG IN ASSEMBLEA SU P.D.L. DI BILANCIO") == ("AgendaOrder", "odg_bilancio")
    assert act_kind("senato:19:aic:3/1", "INTERROGAZIONE A RISPOSTA ORALE") == ("OversightAct", "interrogazione_orale")


def test_unknown_type_has_no_family():
    assert act_kind("x", "strano") is None
    assert not valid("Bill", "mozione")
