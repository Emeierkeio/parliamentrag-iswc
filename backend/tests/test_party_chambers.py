"""Senate groups map onto the Camera parties; chamber-only groups are expected
in answers only when their chamber is loaded."""

import copy

import pytest

from app.config import get_config
from app.models.evidence import normalize_party_name

NOI_MODERATI = "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare"
AUTONOMIE = "Per le Autonomie (SVP-PATT, Campobase)"


@pytest.mark.parametrize("senate, camera", [
    ("Fratelli d'Italia", "FRATELLI D'ITALIA"),
    ("MoVimento 5 Stelle", "MOVIMENTO 5 STELLE"),
    ("Lega Salvini Premier - Partito Sardo d'Azione", "LEGA - SALVINI PREMIER"),
    ("Italia Viva - Casa Riformista", "ITALIA VIVA-CASA RIFORMISTA (IV-CR)"),
    ("Civici d'Italia-UDC-Noi Moderati (Noi con l'Italia, Coraggio Italia, Italia al Centro)-MAIE-Centro Popolare",
     "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE"),
])
def test_senate_group_is_the_camera_party(senate, camera):
    assert normalize_party_name(senate) == normalize_party_name(camera)


def test_display_name_maps_to_itself():
    assert normalize_party_name("Fratelli d'Italia") == "Fratelli d'Italia"
    assert normalize_party_name(NOI_MODERATI) == NOI_MODERATI


def test_senate_groups_get_a_coalition():
    config = get_config()
    assert config.get_coalition("Lega Salvini Premier - Partito Sardo d'Azione") == "maggioranza"
    assert config.get_coalition(AUTONOMIE) == "opposizione"


def test_senate_only_group_expected_only_with_the_senate():
    config = get_config()
    original = config.load_config()
    assert AUTONOMIE not in config.get_all_parties()
    try:
        with_senate = copy.deepcopy(original)
        with_senate["chambers"] = ["camera", "senato"]
        config.save_config(with_senate)
        assert AUTONOMIE in config.get_all_parties()
    finally:
        config.save_config(original)


def test_government_is_majority_in_both_coalition_functions():
    from app.services.authority.coalition_logic import CoalitionLogic
    for name in ("GOVERNO", "Governo"):
        assert get_config().get_coalition(name) == "maggioranza"
        assert CoalitionLogic().get_coalition(name) == "maggioranza"
