"""Vote -> bill attribution for the Senate (labels of osr:Votazione vs transcript)."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from link_senate_acts import bill_index, link_sitting_votes, vote_act, vote_keys


def _sitting(*events):
    return {"sections": {}, "events": [(vote_keys(text), bills) for text, bills in events]}


SITTING_300 = _sitting(
    ("Indìco la votazione dell'articolo unico del disegno di legge n. 1468", ["1468"]),
    ("Indìco la votazione nominale con scrutinio simultaneo della proposta della Giunta", []),
    ("Indìco la votazione nominale con scrutinio simultaneo dell'emendamento 1.3, presentato dal senatore Parrini", ["1192"]),
    ("Indìco la votazione nominale con scrutinio simultaneo dell'articolo 21, nel testo emendato.", ["1192"]),
    ("Indìco la votazione finale.", ["1192"]),
)


def test_explicit_bill_number_in_label():
    assert vote_act("Disegno di legge n. 1272.  Votazione questione di fiducia.", SITTING_300) == "1272"


def test_amendment_matched_through_transcript():
    assert link_sitting_votes([("v", "Em. 1.3, Parrini e altri")], SITTING_300) == {"v": "1192"}


def test_article_and_final_vote():
    votes = [("a", "Articolo 21"), ("f", "Votazione finale")]
    assert link_sitting_votes(votes, SITTING_300) == {"a": "1192", "f": "1192"}


def test_giunta_proposal_not_attributed():
    label = "Proposta Giunta elezioni ed immunità contraria all'autorizzazione"
    assert vote_act(label, SITTING_300) is None


def test_single_bill_rule_skips_sittings_with_other_votes():
    sitting = _sitting(("Indìco la votazione della mozione 1-00123", []),
                       ("Indìco la votazione dell'emendamento 2.1", ["900"]))
    assert vote_act("Mozione n. 123", sitting) is None
    only_bill = _sitting(("Indìco la votazione dell'emendamento 2.1", ["900"]))
    assert vote_act("Em. 2.1, Rossi", only_bill) == "900"
    assert vote_act("Em. 2.1, Rossi", sitting) is None


def test_joint_bill_reachable_from_each_number():
    ddl = pd.DataFrame({
        "ddl": ["u/joint", "u/c", "u/1"],
        "numero": ["93-338-353-B", "93", "1"],
        "ramo": ["S", "C", "S"],
    })
    index = bill_index(ddl)
    assert index["338"] == "u/joint"
    assert index["93"] == "u/joint"   # C.93 is a Camera number, not indexed
    assert index["1"] == "u/1"


def test_forward_scan_separates_two_bills():
    sitting = _sitting(
        ("Indìco la votazione dell'articolo 6.", ["100"]),
        ("Indìco la votazione finale.", ["100"]),
        ("Indìco la votazione dell'articolo 6.", ["200"]),
        ("Indìco la votazione finale.", ["200"]),
    )
    votes = [("v1", "Articolo 6"), ("v2", "Votazione finale"),
             ("v3", "Controprova"), ("v4", "Articolo 6"), ("v5", "Votazione finale")]
    assert link_sitting_votes(votes, sitting) == {
        "v1": "100", "v2": "100", "v3": "100", "v4": "200", "v5": "200",
    }


def test_unannounced_vote_does_not_shift_the_rest():
    # sitting 85: the final vote on bill 614 is not announced with "Indìco"
    sitting = _sitting(
        ("Indìco la votazione dell'articolo 1.", ["614"]),
        ("Indìco la votazione degli emendamenti 1.1 e 1.2", ["693", "364"]),
        ("Indìco la votazione dell'emendamento 1.100", ["693", "364"]),
        ("Indìco la votazione finale.", ["693", "364"]),
    )
    votes = [("v1", "Votazione finale"), ("v2", "Emm. 1.1 e 1.2"),
             ("v3", "Em. 1.100, Lopreiato e altri"), ("v4", "Votazione finale")]
    assert link_sitting_votes(votes, sitting) == {"v2": "693", "v3": "693", "v4": "693"}


def test_three_part_and_sub_amendment_keys():
    assert vote_keys("Em. 18.0.6, Patton e altri") == {"item:18.0.6"}
    assert vote_keys("Em. 5.0.100/102, Cataldi") == {"item:5.0.100/102"}
    assert vote_keys("dell'emendamento 3-bis.0.106, presentato") == {"item:3-bis.0.106"}


# --- initiative and presenters (decision D3) ---

from link_senate_acts import deputy_persona, government_on, initiative_of, match_minister  # noqa: E402

MELONI_I = [
    {"id": "gov_nordio_carlo", "first_name": "CARLO", "last_name": "NORDIO"},
    {"id": "p_meloni", "first_name": "GIORGIA", "last_name": "MELONI"},
    {"id": "p_pichetto", "first_name": "GILBERTO", "last_name": "PICHETTO FRATIN"},
    {"id": "p_santanche", "first_name": "DANIELA", "last_name": "GARNERO SANTANCHE'"},
]


def test_initiative_of():
    assert initiative_of({"Governativa"}) == "governo"
    assert initiative_of({"Parlamentare", "Governativa"}) == "mista"
    assert initiative_of({"CNEL"}) == "cnel"
    assert initiative_of(set()) is None


def test_minister_matched_by_name_in_presenter_string():
    assert match_minister("Ministro della giustizia Carlo Nordio (Gov. Meloni-I)", MELONI_I) == "gov_nordio_carlo"
    assert match_minister("Pres. Consiglio Giorgia Meloni (Gov. Meloni-I)", MELONI_I) == "p_meloni"
    assert match_minister("Ministro dell'ambiente e sicurezza energetica Gilberto Pichetto Fratin "
                          "(Gov. Meloni-I)", MELONI_I) == "p_pichetto"
    assert match_minister("Ministro del turismo Daniela Garnero Santanchè (Gov. Meloni-I)", MELONI_I) == "p_santanche"


def test_minister_not_in_government_is_none():
    assert match_minister("Ministro dell'interno Matteo Piantedosi (Gov. Meloni-I)", MELONI_I) is None


def test_deputy_persona_and_government_on():
    assert deputy_persona("http://dati.camera.it/ocd/deputato.rdf/d302838_19") == \
        "http://dati.camera.it/ocd/persona.rdf/p302838"
    assert deputy_persona("") is None
    govs = [{"id": "draghi_1", "start": "2021-02-12", "end": "2022-10-21"},
            {"id": "meloni_1", "start": "2022-10-21", "end": None}]
    assert government_on(govs, "2022-10-20")["id"] == "draghi_1"
    assert government_on(govs, "2022-10-21")["id"] == "meloni_1"


def test_official_vote_acts_keeps_senate_bills_only():
    from link_senate_acts import official_vote_acts
    rows = pd.DataFrame({
        "votazione": ["http://dati.senato.it/votazione/19-27-5", "http://dati.senato.it/votazione/19-27-5",
                      "http://dati.senato.it/votazione/19-213-140"],
        "atto": ["http://dati.senato.it/ddl/1", "http://dati.senato.it/documento/9",
                 "http://dati.senato.it/ddl/2"],
    })
    out = official_vote_acts(rows, {"http://dati.senato.it/ddl/1", "http://dati.senato.it/ddl/2"})
    assert out == {"senato_leg19_sed027_v005": ["http://dati.senato.it/ddl/1"],
                   "senato_leg19_sed213_v140": ["http://dati.senato.it/ddl/2"]}


def test_later_reading_inherits_signatories_of_the_first():
    from link_senate_acts import inherit_from_first_reading
    ddl = pd.DataFrame({
        "ddl": ["s/17", "s/17-B", "s/90", "c/741"],
        "idDdl": ["50878", "50878", "60000", "60000"],
        "ramo": ["S", "S", "S", "C"],
    })
    signers = pd.DataFrame({"ddl": ["s/17", "s/17", "s/90"], "senatore": ["a", "b", "c"],
                            "primoFirmatario": ["1", "0", "1"], "tipo": ["Parlamentare"] * 3})
    orphans = set(ddl.loc[ddl["ramo"] == "S", "ddl"]) - set(signers["ddl"])
    out = inherit_from_first_reading(ddl, signers, orphans)
    assert sorted(out.loc[out["ddl"] == "s/17-B", "senatore"]) == ["a", "b"]
    assert "c/741" not in set(out["ddl"])  # a Chamber reading stays as it is


def test_minister_known_by_nickname():
    from link_senate_acts import match_minister
    members = [{"id": "gov_musumeci", "first_name": "Sebastiano", "last_name": "Musumeci"}]
    text = "Ministro senza portafoglio per la protezione civile e politiche mare Nello Musumeci (Gov. Meloni-I)"
    assert match_minister(text, members) == "gov_musumeci"
