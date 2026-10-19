"""Unit tests for the planning step of repair_senate_speakers.py (no Neo4j)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from repair_senate_speakers import plan_changes  # noqa: E402

SALVINI = "http://dati.senato.it/senatore/25407"
SALVITTI = "http://dati.senato.it/senatore/36443"
SPEECH = "sen_leg19_sed413_p25407_deb2_6"


def test_speech_moves_to_the_senator_the_record_prints():
    parsed = {SPEECH: (SALVITTI, "Salvitti")}
    current = [{"id": SPEECH, "dep": SALVINI, "name": "Salvini", "people": ["gov_salvini_matteo"]}]
    rows, manual = plan_changes(parsed, current, {SALVITTI: [SALVITTI]})
    assert manual == []
    assert rows == [{"id": SPEECH, "dep": SALVITTI, "name": "Salvitti", "old_dep": SALVINI,
                     "old_name": "Salvini", "old": "gov_salvini_matteo", "new": SALVITTI}]


def test_unchanged_speech_is_left_alone():
    parsed = {SPEECH: (SALVITTI, "Salvitti")}
    current = [{"id": SPEECH, "dep": SALVITTI, "name": "Salvitti", "people": [SALVITTI]}]
    assert plan_changes(parsed, current, {SALVITTI: [SALVITTI]}) == ([], [])


def test_speaker_without_a_unique_person_goes_to_manual_review():
    parsed = {SPEECH: (None, "ALBANO")}
    current = [{"id": SPEECH, "dep": SALVINI, "name": "Salvini", "people": ["gov_salvini_matteo"]}]
    rows, manual = plan_changes(parsed, current, {})
    assert rows == [] and len(manual) == 1
