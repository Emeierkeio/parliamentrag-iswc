"""
Unit tests for xml_parser.StenograficoParser and classify_phase_type.
"""

import sys
import os

# Allow imports from build/ directory when running tests from within build/tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import xml.etree.ElementTree as ET
import pytest

from xml_parser import StenograficoParser, classify_phase_type


# ---------------------------------------------------------------------------
# parse_xml_file — structural tests
# ---------------------------------------------------------------------------

def test_parse_xml_returns_all_keys(tmp_xml_file):
    """parse_xml_file must return dict with all six required top-level keys."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    assert set(result.keys()) >= {'session', 'debates', 'phases', 'speeches', 'votes', 'act_references'}


def test_session_properties_camelcase(tmp_xml_file):
    """Session dict must use camelCase/correct English property names."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    session = result['session']
    assert 'id' in session
    assert 'legislature' in session
    assert 'number' in session
    assert 'year' in session
    assert 'month' in session
    assert 'day' in session
    assert 'chamber' in session
    assert 'date' in session
    # Must NOT have Italian or legacy property names
    assert 'legislatura' not in session
    assert 'numero' not in session
    assert 'anno' not in session
    assert 'mese' not in session
    assert 'giorno' not in session
    assert 'ramo' not in session
    assert 'completeDate' not in session


def test_session_no_complete_date(tmp_xml_file):
    """Session dict must NOT contain completeDate (removed property)."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    assert 'completeDate' not in result['session']


def test_speech_no_preprocessed_text(tmp_xml_file):
    """Speech dicts must NOT contain preprocessedText key (removed duplicate)."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    for speech in result['speeches']:
        assert 'preprocessedText' not in speech
        assert 'preprocessed_text' not in speech


# ---------------------------------------------------------------------------
# Vote parsing tests
# ---------------------------------------------------------------------------

def test_vote_parsing(tmp_xml_file):
    """parse_xml_file must return votes with all 12 required properties."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    assert len(result['votes']) > 0, "Expected at least one vote in sample XML"
    vote = result['votes'][0]
    required_keys = {'id', 'number', 'type', 'subject', 'present', 'voters',
                     'abstained', 'majority', 'inFavor', 'against', 'onMission', 'outcome'}
    assert required_keys.issubset(set(vote.keys())), f"Missing keys: {required_keys - set(vote.keys())}"


def test_vote_not_inside_dibattito(tmp_xml_file):
    """Votes must be parsed from raccoltaVotazioni (session level), not dibattito."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    # The sample XML places raccoltaVotazioni at resoconto level — must be found
    assert len(result['votes']) >= 1, "Regression: votes not found at raccoltaVotazioni level"


def test_parse_vote_standalone(sample_vote_xml):
    """parse_vote must return dict with all required camelCase keys."""
    parser = StenograficoParser()
    elem = ET.fromstring(sample_vote_xml)
    vote = parser.parse_vote(elem, session_id="leg19_sed250", vot_index=0)
    assert vote['id'] == 'leg19_sed250_vot_0'
    assert vote['number'] == 42
    assert vote['type'] == 'Nominale'
    assert vote['present'] == 450
    assert vote['inFavor'] == 250
    # Raw XML esito 'Appr.' is normalized to the SPARQL-ingester vocabulary
    assert vote['outcome'] == 'approved'


# ---------------------------------------------------------------------------
# Argomenti / act references tests
# ---------------------------------------------------------------------------

def test_argomenti_parsing(tmp_xml_file):
    """act_references must be a dict mapping debate IDs to lists of {type, code}."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    act_refs = result['act_references']
    assert isinstance(act_refs, dict)
    # The sample XML has one argomento with idDibattito="tit00050"
    assert 'tit00050' in act_refs
    refs = act_refs['tit00050']
    assert len(refs) >= 1
    ref = refs[0]
    assert 'type' in ref and 'code' in ref
    assert ref['type'] == 'pdl'
    assert ref['code'] == '5-A'


# ---------------------------------------------------------------------------
# Speaker role extraction tests
# ---------------------------------------------------------------------------

def test_speaker_role_extraction(sample_speech_with_role_xml):
    """_extract_speaking_role must return role string from emphasis after nominativo."""
    parser = StenograficoParser()
    elem = ET.fromstring(sample_speech_with_role_xml)
    role = parser._extract_speaking_role(elem)
    assert role == "Ministro dell'Interno"


def test_speaker_no_role(sample_speech_no_role_xml):
    """_extract_speaking_role must return None when no emphasis tag present."""
    parser = StenograficoParser()
    elem = ET.fromstring(sample_speech_no_role_xml)
    role = parser._extract_speaking_role(elem)
    assert role is None


def test_speaker_role_in_parsed_speech(tmp_xml_file):
    """Speeches parsed from XML with emphasis role must have speakingRole populated."""
    parser = StenograficoParser()
    result = parser.parse_xml_file(tmp_xml_file)
    speeches_with_role = [s for s in result['speeches'] if s.get('speakingRole')]
    assert len(speeches_with_role) >= 1, "Expected at least one speech with speakingRole"
    assert speeches_with_role[0]['speakingRole'] == "Ministro dell'Interno"


# ---------------------------------------------------------------------------
# Phase type classification tests
# ---------------------------------------------------------------------------

def test_phase_type_classification():
    """classify_phase_type must map Italian titles to correct English enum values."""
    assert classify_phase_type("Dichiarazioni di voto") == "vote_declaration"
    assert classify_phase_type("Votazioni nominali") == "vote"
    assert classify_phase_type("Discussione sulle linee generali") == "general_discussion"
    assert classify_phase_type("Parere del Governo") == "government_opinion"
    assert classify_phase_type("Un titolo qualsiasi") == "other"


def test_phase_type_all_patterns():
    """classify_phase_type must handle all documented pattern types."""
    assert classify_phase_type("Votazione finale") == "vote"
    assert classify_phase_type("Annunzio di risoluzioni") == "resolution_announcement"
    assert classify_phase_type("Esame degli ordini del giorno") == "order_of_business"
    assert classify_phase_type("Esame degli articoli") == "article_examination"
    assert classify_phase_type("Discussione generale") == "discussion"
    assert classify_phase_type("Interventi di fine seduta") == "interventions"
    assert classify_phase_type("Svolgimento di scrutinio") == "ballot"
    assert classify_phase_type("Replica del relatore") == "reply"


def test_phase_type_case_insensitive():
    """classify_phase_type must work case-insensitively."""
    assert classify_phase_type("dichiarazioni di voto") == "vote_declaration"
    assert classify_phase_type("VOTAZIONI") == "vote"


# ---------------------------------------------------------------------------
# Continuation merge tests
# ---------------------------------------------------------------------------

def test_continuation_merge():
    """merge_continuation_interventions must merge ellipsis-continued speeches from same speaker."""
    parser = StenograficoParser()
    interventions = [
        {
            'id': 'ses1_int1',
            'original_id': 'int1',
            'deputato_id': '300001',
            'cognome_nome': 'ROSSI Mario',
            'testo_raw': 'Prima parte del discorso.',
            'testo': 'Prima parte del discorso.',
            'speakingRole': None,
        },
        {
            'id': 'ses1_int2',
            'original_id': 'int2',
            'deputato_id': '300001',
            'cognome_nome': 'ROSSI Mario',
            'testo_raw': '...continuazione del discorso.',
            'testo': '...continuazione del discorso.',
            'speakingRole': None,
        },
        {
            'id': 'ses1_int3',
            'original_id': 'int3',
            'deputato_id': '300002',
            'cognome_nome': 'BIANCHI Anna',
            'testo_raw': 'Intervento di un altro oratore.',
            'testo': 'Intervento di un altro oratore.',
            'speakingRole': None,
        },
    ]
    merged = parser.merge_continuation_interventions(interventions)
    # First two should be merged, third kept separate
    assert len(merged) == 2
    assert '...continuazione' in merged[0]['testo_raw']
    assert merged[1]['deputato_id'] == '300002'


def test_continuation_merge_no_ellipsis():
    """merge_continuation_interventions must NOT merge when no ellipsis."""
    parser = StenograficoParser()
    interventions = [
        {
            'id': 'ses1_int1',
            'original_id': 'int1',
            'deputato_id': '300001',
            'cognome_nome': 'ROSSI Mario',
            'testo_raw': 'Prima parte.',
            'testo': 'Prima parte.',
            'speakingRole': None,
        },
        {
            'id': 'ses1_int2',
            'original_id': 'int2',
            'deputato_id': '300001',
            'cognome_nome': 'ROSSI Mario',
            'testo_raw': 'Seconda parte senza ellissi.',
            'testo': 'Seconda parte senza ellissi.',
            'speakingRole': None,
        },
    ]
    merged = parser.merge_continuation_interventions(interventions)
    assert len(merged) == 2


class TestOpeningVocative:
    def _clean(self, text):
        from xml_parser import StenograficoParser
        return StenograficoParser().preprocess_text(text)

    def test_vocative_removed_rest_of_sentence_kept(self):
        text = ("Signor Presidente, rappresentanti del Governo, colleghi, oggi siamo in Aula "
                "per discutere la produzione nucleare di energia. Seconda frase.")
        assert self._clean(text).startswith("rappresentanti del Governo, colleghi, oggi siamo in Aula")

    def test_bare_presidente(self):
        assert self._clean("Presidente, non sono numerati.") == "non sono numerati."

    def test_text_without_vocative_untouched(self):
        assert self._clean("Grazie, Presidente. Il decreto va ritirato.") == "Grazie, Presidente. Il decreto va ritirato."
