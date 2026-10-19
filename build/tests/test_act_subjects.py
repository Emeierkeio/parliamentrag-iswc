"""Subjects of motions and resolutions from debate titles and vote labels."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from act_subjects import choose_subject, fallback_subject, topic_from_label, topic_from_title  # noqa: E402


def test_camera_motion_titles():
    assert topic_from_title(
        "Discussione delle mozioni Aiello ed altri n. 1-00052, Cattaneo ed altri n. 1-00096, Scotto "
        "ed altri n. 1-00152 e Mari ed altri n. 1-00153 concernenti iniziative a favore "
        "dell'adeguatezza dei trattamenti previdenziali, con particolare riferimento all'importo "
        "delle pensioni minime.") == (
        "Iniziative a favore dell'adeguatezza dei trattamenti previdenziali, con particolare "
        "riferimento all'importo delle pensioni minime", True)
    assert topic_from_title("Discussione delle mozioni Molinari ed altri n. 1-00479 e Cerreto ed "
                            "altri n. 1-00494 in materia di politica agricola comune (ore 12). "
                            "(ore 12) (ore 12)") == ("Politica agricola comune", True)
    assert topic_from_title("Rinvio del seguito della discussione delle mozioni Richetti ed altri "
                            "n. 1-00582 in materia di superamento del diritto di veto.") == (
        "Superamento del diritto di veto", True)
    assert topic_from_title("Discussione della mozione Francesco Silvestri ed altri n. 1-00164 "
                            "presentata a norma dell'articolo 115, comma 3, del Regolamento, nei "
                            "confronti del Ministro del Turismo, Daniela Garnero Santanche'.") == (
        "Sfiducia nei confronti del Ministro del Turismo, Daniela Garnero Santanche'", True)


def test_senate_motion_titles():
    assert topic_from_title("Discussione e approvazione della mozione n. 47 sul contrasto "
                            "all'omofobia") == ("Contrasto all'omofobia", True)
    assert topic_from_title("Discussione delle mozioni nn. 136 e 148 sulla riforma della legge di "
                            "contabilità (Procedimento abbreviato, ai sensi dell'articolo 157, "
                            "comma 3, del Regolamento)") == ("Riforma della legge di contabilità", True)
    assert topic_from_title("Discussione e reiezione della mozione di sfiducia individuale n. 62 "
                            "nei confronti del Ministro del turismo") == (
        "Sfiducia individuale nei confronti del Ministro del turismo", True)
    assert topic_from_title("Discussione e approvazione delle mozioni nn. 39 e 44") == (None, True)


def test_procedural_and_unrelated_titles():
    assert topic_from_title("Si riprende la discussione.") == (None, False)
    assert topic_from_title("Per un richiamo al Regolamento.") == (None, False)
    assert topic_from_title("Sulla votazione della mozione n. 1-00392 effettuata nella seduta "
                            "precedente.") == (None, False)


def test_communications_and_documents():
    assert topic_from_title("Discussione sulle comunicazioni del Presidente del Consiglio dei "
                            "ministri in vista del Consiglio europeo del 27 e 28 giugno 2024")[0] == (
        "Comunicazioni del Presidente del Consiglio dei ministri in vista del Consiglio europeo "
        "del 27 e 28 giugno 2024")
    assert topic_from_title("Comunicazioni del Ministro della Giustizia sull'amministrazione della "
                            "giustizia, ai sensi dell'articolo 86 del regio decreto 30 gennaio "
                            "1941, n. 12.")[0] == (
        "Comunicazioni del Ministro della Giustizia sull'amministrazione della giustizia")
    assert topic_from_title("Comunicazioni del Ministro della difesa ai sensi dell'articolo 1 del "
                            "decreto-legge 2 dicembre 2022, n. 185, recante «Disposizioni urgenti», "
                            "e conseguente discussione")[0] == (
        "Comunicazioni del Ministro della difesa: «Disposizioni urgenti»")
    assert topic_from_title("Discussione del Documento di economia e finanza 2023 (Doc. LVII, n. 1 "
                            "e Annesso-bis).")[0] == "Documento di economia e finanza 2023"
    assert topic_from_title("Ripresa della discussione del documento: (Doc. LVII, n. 2) - DEF "
                            "2024")[0] == "DEF 2024"
    assert topic_from_title("Ripresa della discussione sulle comunicazioni del Governo")[0] == (
        "Comunicazioni del Governo")


def test_senate_labels():
    assert topic_from_label("Mozione n. 45, Speranzon e altri, sul riconoscimento dello  Holodomor "
                            "come genocidio", "mozione") == "Riconoscimento dello Holodomor come genocidio"
    assert topic_from_label("Mozione n. 66, sui profili critici nel processo attuazione  autonomia "
                            "differenziata. ODG G1 (t2), Malan e altri", "mozione") == (
        "Profili critici nel processo attuazione autonomia differenziata")
    assert topic_from_label("Mozione 1-00039, Boccia e altri. Votazione finale", "mozione") is None
    assert topic_from_label("Comunicazioni Ministro difesa. Proposta di risoluzione n. 2 (testo 2), "
                            "Paita e altri", "risoluzione_assemblea") == "Comunicazioni Ministro difesa"
    assert topic_from_label("Proposta di risoluzione n.3, Liris e altri", "risoluzione_assemblea") is None
    assert topic_from_label("Docc.LXXXVI, n.1 e LXXXVII, n.1. Proposta di risoluzione n.2Terzi",
                            "risoluzione_assemblea") is None


def test_choose_subject_order():
    act = {"kind": "risoluzione_assemblea", "number": "6/00207", "surname": "Barcaiuolo", "cosigners": 3,
           "debates": [
               {"title": "Ripresa della discussione sulle comunicazioni del Governo",
                "date": "2026-03-05", "order": 15},
               {"title": "Comunicazioni del Governo in esito alla richiesta di aiuti dai Paesi del "
                         "Golfo e conseguente discussione", "date": "2026-03-05", "order": 12}],
           "labels": ["Comunicazioni Governo in esito a richiesta aiuti Paesi Golfo. Proposta di "
                      "risoluzione n. 1, Barcaiuolo e altri"]}
    assert choose_subject(act) == (
        "Comunicazioni del Governo in esito alla richiesta di aiuti dai Paesi del Golfo", "debate")
    act["debates"] = []
    assert choose_subject(act) == ("Comunicazioni Governo in esito a richiesta aiuti Paesi Golfo", "vote")
    act["labels"] = []
    assert choose_subject(act) == ("Risoluzione 6-00207, Barcaiuolo e altri", "fallback")


def test_fallback_subject():
    assert fallback_subject("mozione", "1/00039", "Boccia", 5) == "Mozione 1-00039, Boccia e altri"
    assert fallback_subject("mozione", "1/00002", "D'ALESSIO", 0) == "Mozione 1-00002, D'Alessio"
    assert fallback_subject("risoluzione_assemblea", "6/00045", None, 0) == "Risoluzione 6-00045"
