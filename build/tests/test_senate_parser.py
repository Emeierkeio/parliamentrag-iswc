"""
test_senate_parser.py — Unit tests for SenateStenograficoParser.

Uses the sample_session.akn fixture in build/fixtures/.
"""

import os
import sys

import pytest

# Add build/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "sample_session.akn"
)


@pytest.fixture(scope="module")
def parsed():
    """Parse the sample AKN fixture once for all tests."""
    from senate_parser import SenateStenograficoParser

    parser = SenateStenograficoParser()
    return parser.parse_xml_file(FIXTURE_PATH)


def test_parse_returns_correct_keys(parsed):
    """Returned dict must have exactly the 6 top-level keys."""
    assert set(parsed.keys()) == {
        "session",
        "debates",
        "phases",
        "speeches",
        "votes",
        "act_references",
    }


def test_session_metadata(parsed):
    """Session metadata must be extracted correctly from FRBRWork."""
    s = parsed["session"]
    assert s["id"] == "sen_leg19_sed5"
    assert s["chamber"] == "senato"
    assert s["legislature"] == 19
    assert s["number"] == 5
    assert s["year"] == 2022
    assert s["month"] == 11
    assert s["day"] == 15
    assert s["date"] == "2022-11-15"


def test_presidente_filtered(parsed):
    """No speech must have a speakingRole containing 'Presidente'."""
    for speech in parsed["speeches"]:
        role = speech.get("speakingRole") or ""
        assert "Presidente" not in role, (
            f"Speech {speech['id']} has Presidente role: {role!r}"
        )


def test_speeches_structure(parsed):
    """Every speech must have all required keys and correct deputatoId prefix."""
    required_keys = {
        "id",
        "text",
        "deputatoId",
        "cognome_nome",
        "sessionId",
        "debateId",
        "phaseId",
        "parentType",
        "parentId",
        "order",
    }
    assert len(parsed["speeches"]) > 0, "Expected at least one speech after filtering"
    for speech in parsed["speeches"]:
        missing = required_keys - set(speech.keys())
        assert not missing, f"Speech missing keys: {missing}"
        assert speech["deputatoId"].startswith("http://dati.senato.it/senatore/"), (
            f"deputatoId {speech['deputatoId']!r} must be a full senatore URI "
            "(matches Deputy.id loaded from senatori CSV)"
        )


def test_debates_and_phases(parsed):
    """InizioSeduta section must be skipped; one debate from DiscussioneArgomento."""
    # InizioSeduta should be skipped, only DiscussioneArgomento creates a debate
    assert len(parsed["debates"]) == 1
    debate = parsed["debates"][0]
    assert "sen_leg19_sed5" in debate["id"]
    # Each debate has a corresponding phase
    assert len(parsed["phases"]) == len(parsed["debates"])
    phase = parsed["phases"][0]
    assert phase["debateId"] == debate["id"]


def test_votes_and_acts_empty(parsed):
    """votes must be empty list; act_references must be empty dict."""
    assert parsed["votes"] == []
    assert parsed["act_references"] == {}


def _variant(tmp_path, body_edit):
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        xml = f.read()
    path = tmp_path / "variant.akn"
    path.write_text(body_edit(xml), encoding="utf-8")
    from senate_parser import SenateStenograficoParser
    return SenateStenograficoParser().parse_xml_file(str(path))


def test_repeated_speaker_in_debate_gets_distinct_ids(tmp_path):
    """A second speech by the same senator in one debate must not overwrite the first."""
    second = (
        '<an:speech by="#p12345" as="#d1e27a9999">'
        '<an:from refersTo="#p12345">ROSSI</an:from>'
        "<an:p>Intervengo nuovamente per dichiarazione di voto favorevole sul provvedimento "
        "in esame, che riteniamo equilibrato.</an:p></an:speech>"
    )
    parsed = _variant(tmp_path, lambda x: x.replace(
        "</an:debateSection>\n    </an:debateBody>",
        second + "</an:debateSection>\n    </an:debateBody>",
    ))
    ids = [s["id"] for s in parsed["speeches"]]
    assert len(ids) == len(set(ids)) == 3


def test_repeated_section_name_gets_distinct_debate_ids(tmp_path):
    def duplicate_section(xml):
        start = xml.index('<an:debateSection name="DiscussioneArgomento">')
        end = xml.index("</an:debateBody>")
        return xml[:end] + xml[start:end] + xml[end:]

    parsed = _variant(tmp_path, duplicate_section)
    debate_ids = [d["id"] for d in parsed["debates"]]
    assert len(debate_ids) == len(set(debate_ids)) == 2


def test_group_label_does_not_leave_leading_punctuation(tmp_path):
    parsed = _variant(tmp_path, lambda x: x.replace(
        "<an:p>Signor Presidente, desidero",
        "<an:p><an:i>(Misto-AVS)</an:i>. Signor Presidente, desidero",
    ))
    rossi = next(s for s in parsed["speeches"] if s["deputatoId"].endswith("/12345"))
    assert rossi["text"].startswith("Signor Presidente")


def test_prime_minister_is_a_speaker_not_the_chair(tmp_path):
    """Roles containing "Presidente" (Presidente del Consiglio) must not be dropped as chair."""
    def add_pm(xml):
        role = ('<an:TLCRole id="rolePM" href="http://dati.senato.it/osr/Incarico" '
                'showAs="Presidente del Consiglio dei ministri"/>')
        speech = ('<an:speech by="#p12345" as="#rolePM"><an:from refersTo="#p12345">ROSSI</an:from>'
                  "<an:p>Signor Presidente, onorevoli senatori, il Governo riferisce oggi in Aula "
                  "sulle comunicazioni in vista del Consiglio europeo.</an:p></an:speech>")
        xml = xml.replace("</an:references>", role + "</an:references>", 1)
        return xml.replace("</an:debateSection>\n    </an:debateBody>",
                           speech + "</an:debateSection>\n    </an:debateBody>")
    parsed = _variant(tmp_path, add_pm)
    roles = [s["speakingRole"] for s in parsed["speeches"]]
    assert "Presidente del Consiglio dei ministri" in roles
    assert all(r != "PRESIDENTE" for r in roles)


def _continuation(text):
    return f'<an:speech by="#p" as=""><an:from refersTo="#p"/><an:p>{text}</an:p></an:speech>'


def test_continuation_block_joins_the_previous_speaker(tmp_path):
    """by="#p" blocks continue the last speaker: no speech without a speaker."""
    tail = "Concludo ricordando che il gruppo voterà a favore del provvedimento in esame."
    parsed = _variant(tmp_path, lambda x: x.replace(
        '<an:speech by="#p32600" as="#d1e27a5678">',
        _continuation(tail) + '<an:speech by="#p32600" as="#d1e27a5678">',
        1,
    ))
    assert all(s["deputatoId"] for s in parsed["speeches"])
    rossi = next(s for s in parsed["speeches"] if s["deputatoId"].endswith("/12345"))
    assert rossi["text"].endswith(tail)


def test_continuation_of_the_chair_is_dropped(tmp_path):
    parsed = _variant(tmp_path, lambda x: x.replace(
        '<an:speech by="#p12345" as="#d1e27a1234">',
        _continuation("Passiamo alla votazione finale del disegno di legge nel suo complesso.")
        + '<an:speech by="#p12345" as="#d1e27a1234">',
        1,
    ))
    assert not any("Passiamo alla votazione" in s["text"] for s in parsed["speeches"])
    assert all(s["deputatoId"] for s in parsed["speeches"])


# ---------------------------------------------------------------------------
# Debate titles
# ---------------------------------------------------------------------------

def _heading(xml: str):
    import xml.etree.ElementTree as ET

    from senate_parser import AKN_NS

    return ET.fromstring(f'<heading xmlns="{AKN_NS}">{xml}</heading>')


def test_debate_title_line_break_is_a_space():
    from senate_parser import debate_title

    h = _heading("<span><b>Discussione dalla sede redigente<eol/>del disegno di legge sul turismo</b></span><eol/>")
    assert debate_title(h, "Altro") == "Discussione dalla sede redigente del disegno di legge sul turismo"


def test_debate_title_cut_before_the_numbers_uses_the_name():
    from senate_parser import debate_title

    name = "Ripresa della discussione dei disegni di legge costituzionale: (13 e connessi) - Modifica all'articolo 33"
    h = _heading("<span><b>Ripresa della discussione dei disegni di legge costituzionale<eol/>nn.</b></span>")
    assert debate_title(h, name) == name
    h = _heading("<b>Ripresa della discussione del disegno di legge n.</b>")
    assert debate_title(h, "Ripresa della discussione del disegno di legge: (311) - PNRR") == (
        "Ripresa della discussione del disegno di legge: (311) - PNRR"
    )


def test_debate_title_prefix_of_the_name_uses_the_name():
    from senate_parser import debate_title

    name = "Discussione e approvazione del disegno di legge: (311) - Politica energetica"
    assert debate_title(_heading("<b>Discussione e approvazione del disegno di legge:</b>"), name) == name
    assert debate_title(_heading("<b>Discussione congiunta del</b>"), "Discussione congiunta del documento LVII") == (
        "Discussione congiunta del documento LVII"
    )


def test_debate_title_keeps_a_complete_heading():
    from senate_parser import debate_title

    h = _heading("<b>Svolgimento di interrogazioni a risposta immediata</b>")
    assert debate_title(h, "(3-00039) - Question time su Milano-Cortina") == (
        "Svolgimento di interrogazioni a risposta immediata"
    )
    assert debate_title(None, "Nome") == "Nome"
    assert debate_title(_heading("  <eol/> "), "Nome") == "Nome"


# ---------------------------------------------------------------------------
# Speaker named by the by attribute vs the surname printed in <from>
# ---------------------------------------------------------------------------

_PEOPLE = (
    '<an:TLCPerson id="p25407" href="http://dati.senato.it/osr/Persona/25407" showAs="Salvini"/>'
    '<an:TLCPerson id="p36443" href="http://dati.senato.it/osr/Persona/36443" showAs="Salvitti"/>'
    '<an:TLCPerson id="p36399" href="http://dati.senato.it/osr/Persona/36399" showAs="FLORIDIA"/>'
    '<an:TLCPerson id="p32634" href="http://dati.senato.it/osr/Persona/32634" showAs="FLORIDIA"/>'
    '<an:TLCPerson id="p32" href="http://dati.senato.it/osr/Persona/32" showAs="Alberti"/>'
)
_TEXT = ("Signora Presidente, esprimo parere contrario su tutti gli emendamenti tranne "
         "che sul 4.100, su cui il parere è favorevole.")


def _with_speech(tmp_path, by, printed):
    speech = (f'<an:speech by="#{by}" as="#d1e136a1074"><an:from refersTo="#{by}">{printed}'
              f'</an:from><an:p>. {_TEXT}</an:p></an:speech>')

    def edit(xml):
        xml = xml.replace("</an:references>", _PEOPLE + "</an:references>", 1)
        return xml.replace("</an:debateSection>\n    </an:debateBody>",
                           speech + "</an:debateSection>\n    </an:debateBody>")
    parsed = _variant(tmp_path, edit)
    return next(s for s in parsed["speeches"] if s["text"] == _TEXT)


def test_printed_surname_wins_over_a_by_naming_someone_else(tmp_path):
    """Seduta 413 of the XIX: by="#p25407" (Salvini) on "SALVITTI, relatore"."""
    sp = _with_speech(tmp_path, "p25407", "SALVITTI, <an:i>relatore</an:i>")
    assert sp["deputatoId"] == "http://dati.senato.it/senatore/36443"
    assert sp["cognome_nome"] == "Salvitti"
    assert "_p25407_" in sp["id"]


def test_printed_surname_without_a_person_in_the_document_drops_the_id(tmp_path):
    """Seduta 56 of the XIX: by="#p29570" (Savino) on "ALBANO", absent from TLCPerson here."""
    sp = _with_speech(tmp_path, "p25407", "ALBANO, <an:i>sottosegretario di Stato</an:i>")
    assert sp["deputatoId"] is None
    assert sp["cognome_nome"] == "ALBANO"


def test_homonym_given_name_keeps_the_by_attribute(tmp_path):
    sp = _with_speech(tmp_path, "p32634", "FLORIDIA Barbara")
    assert sp["deputatoId"] == "http://dati.senato.it/senatore/32634"


def test_double_surname_matches_its_first_word(tmp_path):
    sp = _with_speech(tmp_path, "p32", "ALBERTI CASELLATI, <an:i>ministro per le riforme</an:i>")
    assert sp["deputatoId"] == "http://dati.senato.it/senatore/32"


def test_vice_president_in_the_chair_keeps_his_id(tmp_path):
    """XVIII seduta 402: by="#p422" (Calderoli) printed "PRESIDENTE."."""
    sp = _with_speech(tmp_path, "p32", "PRESIDENTE.")
    assert sp["deputatoId"] == "http://dati.senato.it/senatore/32"


def test_matching_speaker_is_unchanged(tmp_path):
    sp = _with_speech(tmp_path, "p25407", "SALVINI, <an:i>ministro delle infrastrutture</an:i>")
    assert sp["deputatoId"] == "http://dati.senato.it/senatore/25407"
    assert sp["cognome_nome"] == "Salvini"


@pytest.mark.parametrize("a,b,same", [
    ("SALVITTI", "Salvini", False),
    ("SALVI", "Salvini", False),
    ("ALBANO", "SAVINO", False),
    ("MARSILIO", "VERDUCCI", False),
    ("ALBERTI CASELLATI", "Alberti", True),
    ("GARNERO SANTANCHÈ", "Garnero Santanche'", True),
    ("D'ERAMO", "D'Eramo", True),
    ("DE PRIAMO", "De Priamo", True),
    ("DE PRIAMO", "PRIAMO", False),
])
def test_same_surname(a, b, same):
    from senate_parser import same_surname
    assert same_surname(a, b) is same


@pytest.mark.parametrize("printed,surname", [
    ("SALVITTI, relatore", "SALVITTI"),
    ("FLORIDIA Aurora", "FLORIDIA"),
    ("BORGHI Claudio,", "BORGHI"),
    ("ALBERTI CASELLATI,", "ALBERTI CASELLATI"),
    ("D'ERAMO, sottosegretario", "D'ERAMO"),
    ("", ""),
])
def test_printed_surname(printed, surname):
    from senate_parser import printed_surname
    assert printed_surname(printed) == surname
