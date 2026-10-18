"""Field parsing of the Senate oversight acts from the Chamber's SPARQL."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from download_senate_aic import iso, signer


def test_signer_drops_group():
    assert signer("PAROLI ADRIANO ( FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE)") == "PAROLI ADRIANO"


def test_signer_drops_group_across_lines():
    assert signer("BASSO LORENZO (\n      )") == "BASSO LORENZO"


def test_iso_date():
    assert iso("20260304") == "2026-03-04"
    assert iso(None) is None
