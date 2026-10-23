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


def test_new_component_from_legend():
    """A component born after the table was written comes from the legend alone."""
    row = """<tr class="tab2"><td valign="top">
 <a href="/composizione/senatori/elenco-alfabetico/scheda-attivita?did=1227">
 GUIDI Antonio
 </a>
 <span>
 Civici Marche
 dal 22 ottobre 2026
 </span>
 </td><td valign="top"><span>Entra nel gruppo il 21 ottobre 2026<br></span></td></tr>
"""
    legend = """<li>
 <strong>Civici Marche (Civici Marche)</strong>
 <span>costituita il 22 ottobre 2026</span>
 </li>
 <li>
 <strong>NOI DI CENTRO E UDC (APM)</strong>
 <span>costituita il 23 ottobre 2026</span>
 </li>
 <li>
 <strong>Azione (Az)</strong>"""
    page = PAGE.replace('<tr class="tab2">', row + '<tr class="tab2">', 1)
    page = page.replace("<li>\n <strong>Azione (Az)</strong>", legend, 1)
    assert "Civici Marche" in ims.parse_legend(page)
    rows = {r["name"]: r for r in ims.memberships(page)}
    guidi = rows["GUIDI Antonio"]
    assert guidi["comp_name"] == "Civici Marche" and guidi["comp_short"] == "Civici Marche"
    assert guidi["comp_uri"].endswith("#Civici-Marche")
    assert guidi["start_date"] == "2026-10-22" and guidi["comp_start"] == "2026-10-22"
    assert ims.component_for("APM", ims.parse_legend(page))["name"] == "Noi di Centro e UDC"


def test_renamed_sigla_keeps_the_component():
    legend = {"Avanti PSI": {"name": "Avanti PSI", "constituted": "2026-10-09", "base": "Avanti PSI"},
              "Avanti PSI-Proget. Civ. Italia": {"name": None, "constituted": None, "base": "Avanti PSI"},
              "Nuova": {"name": "Nuova componente", "constituted": "2026-11-01", "base": "Nuova"},
              "NC": {"name": None, "constituted": None, "base": "Nuova"}}
    assert ims.component_for("Avanti PSI-Proget. Civ. Italia", legend)["key"] == "Avanti-PSI"
    assert ims.component_for("Nuova", legend) == ims.component_for("NC", legend)
    assert ims.component_for("NC", legend) == {"key": "Nuova", "name": "Nuova componente", "short_name": "NC"}
    assert ims.component_for("XYZ", legend) is None
