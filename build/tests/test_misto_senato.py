"""Senate Misto components parsed from the senato.it «Composizione storica» page."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ingest_misto_senato as ims

PAGE = open(os.path.join(os.path.dirname(__file__), "..", "fixtures", "senato_misto_storica.html"),
            encoding="utf-8").read()


def _by_name():
    return {r["name"]: r for r in ims.memberships(PAGE)}


def test_italian_dates():
    assert ims.parse_it_date("dal 24 ottobre 2022") == "2022-10-24"
    assert ims.parse_it_date("Entra nel gruppo l'8 ottobre 2026") == "2026-10-08"
    assert ims.parse_it_date("1º marzo 2023") == "2023-03-01"
    assert ims.parse_it_date("nessuna data") is None


def test_components_and_spans():
    rows = _by_name()
    assert rows["CUCCHI Ilaria"]["comp_name"] == "Alleanza Verdi e Sinistra"
    assert rows["CUCCHI Ilaria"]["start_date"] == "2022-10-24" and rows["CUCCHI Ilaria"]["end_date"] is None
    # «Az» with no date: from the day the senator joined the group
    assert rows["CALENDA Carlo"]["comp_short"] == "Az-RE"
    assert rows["CALENDA Carlo"]["start_date"] == "2023-11-09"
    # «fino al» closes the component before the senator leaves the group
    assert rows["GELMINI Mariastella"]["end_date"] == "2024-09-17"
    # Office holders only (Floridia, vice president) are read too
    assert rows["FLORIDIA Aurora"]["end_date"] == "2025-02-18"
    assert rows["NAVE Luigi"]["comp_name"] == "Avanti PSI"
    assert rows["NAVE Luigi"]["start_date"] == "2026-10-09"
    assert rows["NAVE Luigi"]["senato_id"] == "http://dati.senato.it/senatore/36410"


def test_senators_without_component_are_listed_not_linked():
    rows = _by_name()
    assert "MONTI Mario" not in rows and "SEGRE Liliana" not in rows
    assert "http://dati.senato.it/senatore/28543" in ims.page_senators(PAGE)


def test_one_uri_per_component_across_renames():
    uris = {r["comp_short"]: r["comp_uri"] for r in ims.memberships(PAGE)}
    assert uris["Az-RE"].endswith("#Az")
    assert len(set(uris.values())) == 3
