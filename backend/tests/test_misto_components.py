"""A speaker of the Gruppo Misto counts for their political component:
+Europa and Futuro Nazionale Vannacci are parties of their own, the Senate
AVS and Azione components count for those groups."""

import copy

from app.config import get_config
from app.models.evidence import misto_components_of, normalize_party_name, speaking_party
from app.services.authority.coalition_logic import CoalitionLogic
from app.services.retrieval.dense_channel import DenseChannel

AVS = "Alleanza Verdi e Sinistra"
AZIONE = "Azione - Popolari Europeisti Riformatori - Renew Europe"
EUROPA = "+Europa - Stati Uniti d'Europa"
FN = "Futuro Nazionale Vannacci - Free"


def test_misto_speaker_counts_for_the_component():
    assert normalize_party_name(speaking_party("Misto", "Alleanza Verdi e Sinistra")) == AVS
    assert normalize_party_name(speaking_party("Misto", "Azione-Renew Europe")) == AZIONE
    assert normalize_party_name(speaking_party("MISTO", "+Europa - Stati Uniti d'Europa")) == EUROPA
    assert normalize_party_name(speaking_party("MISTO", "Futuro Nazionale Vannacci - Free")) == FN
    assert normalize_party_name(speaking_party("Misto", "Avanti PSI")) == "Avanti PSI"
    # No component: the Misto; another group: the component is ignored
    assert normalize_party_name(speaking_party("Misto", None)) == "Misto"
    assert speaking_party("FRATELLI D'ITALIA", "Avanti PSI") == "FRATELLI D'ITALIA"


def test_components_of_a_party():
    assert misto_components_of(AVS) == ["alleanza verdi e sinistra"]
    assert misto_components_of(AZIONE) == ["azione-renew europe"]
    assert misto_components_of("Misto") == []
    assert misto_components_of("Fratelli d'Italia") == []


def test_components_coalition_and_expected_parties():
    config = get_config()
    for name in (EUROPA, FN, "Sud chiama Nord", "Avanti PSI"):
        assert config.get_coalition(name) == "misto"
        assert CoalitionLogic().get_coalition(name) == "misto"
    assert config.get_coalition(speaking_party("Misto", "Alleanza Verdi e Sinistra")) == "opposizione"
    original = config.load_config()
    try:
        camera = copy.deepcopy(original)
        camera["chambers"] = ["camera"]
        config.save_config(camera)
        parties = config.get_all_parties()
        assert EUROPA in parties and FN in parties and "Avanti PSI" not in parties
        both = copy.deepcopy(original)
        both["chambers"] = ["camera", "senato"]
        config.save_config(both)
        assert "Avanti PSI" in config.get_all_parties()
    finally:
        config.save_config(original)


def _row(**kw):
    row = {"chunk_id": "c1", "chunk_text": "testo dell'intervento", "text": "testo dell'intervento",
           "speech_id": "s1", "speaker_id": "p1", "speaker_first_name": "Ilaria",
           "speaker_last_name": "Cucchi", "speaker_type": "Deputy", "party": "Misto",
           "current_party": "Misto", "session_date": "2024-05-07", "similarity": 0.8}
    row.update(kw)
    return row


def test_dense_row_of_a_misto_senator_goes_to_avs():
    out = DenseChannel(None)._process_results([_row(misto_component="Alleanza Verdi e Sinistra")])
    assert out[0]["party"] == AVS
    assert out[0]["coalition"] == "opposizione"
    # Still in the Misto today: not a group change
    assert not out[0]["party_changed"]
    out = DenseChannel(None)._process_results([_row()])
    assert out[0]["party"] == "Misto"


def test_expected_parties_follow_the_chambers_of_the_question():
    import contextvars
    from app.services.retrieval.scope import set_answer_scope

    config = get_config()
    original = config.load_config()
    try:
        both = copy.deepcopy(original)
        both["chambers"] = ["camera", "senato"]
        config.save_config(both)

        def senate_only():
            set_answer_scope([("senato", 19)])
            return config.get_all_parties()

        parties = contextvars.copy_context().run(senate_only)
        assert "Avanti PSI" in parties and EUROPA not in parties and FN not in parties
        # Groups of both chambers stay
        assert "Misto" in parties and AVS in parties and "Fratelli d'Italia" in parties
        assert EUROPA in config.get_all_parties(["camera"])
        # Outside an answer: every loaded chamber
        assert EUROPA in config.get_all_parties() and "Avanti PSI" in config.get_all_parties()
    finally:
        config.save_config(original)
