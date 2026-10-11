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
