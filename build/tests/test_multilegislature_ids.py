"""Identifier scoping for multi-legislature, multi-chamber graphs."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_builder import placeholder_act_uri
from sparql_ingester import individual_vote_id, sparql_dep_uri_to_neo4j_id


class TestIndividualVoteId:
    def test_camera_xix_keeps_legacy_form(self):
        assert individual_vote_id("camera", 19, "308849", 38, 45) == "iv_camera_308849_38_45"

    def test_camera_xviii_is_scoped(self):
        assert individual_vote_id("camera", 18, "308849", 38, 45) == "iv_camera_leg18_308849_38_45"

    def test_same_sitting_and_vote_differ_across_legislatures(self):
        assert individual_vote_id("camera", 18, "1", 2, 3) != individual_vote_id("camera", 19, "1", 2, 3)

    def test_senato_is_always_scoped(self):
        assert individual_vote_id("senato", 19, "17542", 167, 42) == "iv_senato_leg19_17542_167_42"


class TestPlaceholderActUri:
    def test_camera_xix_keeps_legacy_form(self):
        assert placeholder_act_uri("camera", 19, "pdl", "C. 1234") == "placeholder:pdl:C. 1234"

    def test_other_legislatures_and_chambers_are_scoped(self):
        assert placeholder_act_uri("camera", 18, "pdl", "C. 1234") == "placeholder:camera:leg18:pdl:C. 1234"
        assert placeholder_act_uri("senato", 19, "ddl", "S. 12") == "placeholder:senato:leg19:ddl:S. 12"


class TestDeputatoUri:
    def test_any_legislature_maps_to_persona(self):
        uri = "http://dati.camera.it/ocd/deputato.rdf/d308908_18"
        assert sparql_dep_uri_to_neo4j_id(uri) == "http://dati.camera.it/ocd/persona.rdf/p308908"


from db_builder import DatabaseBuilder, match_legacy_government_node, normalize_body_name

P = "http://dati.camera.it/ocd/persona.rdf/p"
OFFICIAL = [
    {"persona": P + "200012", "nome": "MARIA ELISABETTA", "cognome": "ALBERTI"},
    {"persona": P + "304860", "nome": "SEBASTIANO", "cognome": "MUSUMECI"},
    {"persona": P + "300639", "nome": "DANIELA", "cognome": "GARNERO SANTANCHE'"},
    {"persona": P + "32530", "nome": "ROBERTO", "cognome": "CALDEROLI"},
    {"persona": P + "309044", "nome": "MARINA ELVIRA", "cognome": "CALDERONE"},
    {"persona": P + "307426", "nome": "MARIA TERESA", "cognome": "BELLUCCI"},
]


class TestLegacyGovernmentMatch:
    def test_badly_split_compound_name(self):
        assert match_legacy_government_node("ELISABETTA", "ALBERTI CASELLATI MARIA", None, OFFICIAL) == P + "200012"

    def test_common_first_name_falls_back_to_unique_surname(self):
        assert match_legacy_government_node("NELLO", "MUSUMECI", None, OFFICIAL) == P + "304860"

    def test_double_surname_and_apostrophe(self):
        assert match_legacy_government_node("DANIELA", "SANTANCHE'", None, OFFICIAL) == P + "300639"

    def test_similar_surnames_do_not_collide(self):
        assert match_legacy_government_node("ELVIRA", "CALDERONE MARINA", None, OFFICIAL) == P + "309044"

    def test_deputy_card_wins(self):
        assert match_legacy_government_node("X", "Y", "307426", OFFICIAL) == P + "307426"

    def test_no_match(self):
        assert match_legacy_government_node("MARIO", "ROSSI", None, OFFICIAL) is None


class TestGovernmentIds:
    def test_ids_from_camera_labels(self):
        assert DatabaseBuilder.government_id("I Governo Conte") == "conte_1"
        assert DatabaseBuilder.government_id("II Governo Conte") == "conte_2"
        assert DatabaseBuilder.government_id("I Governo Meloni") == "meloni_1"


class TestBodyNames:
    def test_bicameral_labels_match_across_spelling(self):
        assert normalize_body_name("COMMISSIONE PARLAMENTARE PER L'INFANZIA E L'ADOLESCENZA") == \
            normalize_body_name("Commissione parlamentare per l'infanzia e l'adolescenza")
        assert normalize_body_name("COMUNITA'") == normalize_body_name("comunità")
