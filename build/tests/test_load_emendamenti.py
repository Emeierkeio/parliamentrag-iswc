"""Amendments loader: outcomes, vote labels, signatories, sub-amendments, chunks, idempotence."""

import datetime as dt
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import load_emendamenti as L  # noqa: E402


# ------------------------------------------------------------------ outcomes

def test_outcomes_case_insensitive():
    assert L.normalize_outcome("Respinto") == "rejected"
    assert L.normalize_outcome("RESPINTA (*)") == "rejected"
    assert L.normalize_outcome("approvato") == "approved"
    assert L.normalize_outcome("Ritirato e trasformato nell'odg n. 18") == "withdrawn"
    assert L.normalize_outcome("Dichiarato inammissibile") == "inadmissible"
    assert L.normalize_outcome("irricevibile") == "inadmissible"
    assert L.normalize_outcome("Precluso dall'approvazione dell'em. 1.6") == "precluded"
    assert L.normalize_outcome("Improponibile") == "improponibile"
    assert L.normalize_outcome("Decaduto") == "lapsed"
    assert L.normalize_outcome("V. testo 2") == "superseded"
    assert L.normalize_outcome("v.testo 2") == "superseded"
    assert L.normalize_outcome("Id. em. 1.1") == "identical"
    assert L.normalize_outcome("Non posto in votazione (*)") == "not_voted"


def test_outcomes_accepted_and_not_accepted():
    assert L.normalize_outcome("Accolto") == "accepted"
    assert L.normalize_outcome("Accolto come raccomandazione") == "accepted_as_recommendation"
    assert L.normalize_outcome("Non accolto") == "not_accepted"


def test_outcome_rest_of_partial_inadmissibility():
    raw = "Dichiarato inammissibile limitatamente al comma 2, respinto per la parte restante"
    assert L.normalize_outcome(raw) == "rejected"
    assert L.normalize_outcome("Parte precluso, parte ritirato") == "mixed"
    assert L.normalize_outcome("Votato per parti separate. Respinta la parte evidenziata") == "mixed"
    assert L.normalize_outcome("Sost id. em. 1.6") == "identical"


def test_outcome_empty_and_unknown():
    assert L.normalize_outcome(None) is None
    assert L.normalize_outcome("  ") is None
    assert L.normalize_outcome("qualcosa di nuovo") == "other"


# --------------------------------------------------------------- vote labels

def test_camera_subject_with_bill():
    assert L.parse_vote_refs("camera", "Votazione Emendamento 9.1 DDL n. 0005",
                             "Emendamento 9.1 ZANELLA LUANA (AVS)") == ("5", [("9.1", None)])
    assert L.parse_vote_refs("camera", "Votazione Emendamento 4.100, PDL n. 0849",
                             "Emendamento 4.100, da votare ai sensi dell'articolo 86, comma 4-bis") \
        == ("849", [("4.100", None)])


def test_camera_identical_amendments_from_description():
    bill, refs = L.parse_vote_refs(
        "camera", "Votazione Emendamento 42.2 DDL n. 0005",
        "Identici emendamenti 42.2 PAGANO UBALDO (PD-IDP) e 42.3 DELL'OLIO GIANMAURO (M5S)")
    assert bill == "5" and refs == [("42.2", None), ("42.3", None)]


def test_camera_generic_subject_and_old_format():
    assert L.parse_vote_refs("camera", "Votazione", "EM 21.2, 21.3") == (None, [("21.2", None), ("21.3", None)])
    assert L.parse_vote_refs("camera", "Votazione", "ART AGG 1-BIS.022") == (None, [("1-bis.022", None)])
    assert L.parse_vote_refs("camera", "Votazione", "SUBEM 0.1.1077.5") == (None, [("0.1.1077.5", None)])
    assert L.parse_vote_refs("camera", "Votazione", "DDL 2128 - EM 1.2") == ("2128", [("1.2", None)])


def test_camera_non_amendment_votes():
    assert L.parse_vote_refs("camera", "Votazione Ordine del giorno 9/1759/9 DDL n. 1759", "x")[1] == []
    assert L.parse_vote_refs("camera", "Votazione", "MOZ 1-358 PREMESSE")[1] == []
    assert L.parse_vote_refs("camera", "Votazione Articolo 3 DDL n. 0831", "Articolo 3")[1] == []
    # "Dis.1.1" is an amendment to the provisions table, not article 1
    assert L.parse_vote_refs("camera", "Votazione Emendamento Dis.1.1 DDL n. 1666", "")[1] == []


def test_senate_subjects():
    assert L.parse_vote_refs("senato", "Em. 3.215, Zampa e altri", None) == (None, [("3.215", None)])
    assert L.parse_vote_refs("senato", "Emm. 1.85, 1.86 e 1.87", None)[1] == \
        [("1.85", None), ("1.86", None), ("1.87", None)]
    assert L.parse_vote_refs("senato", "Em. 2.100 (testo 2), Silvestro", None)[1] == [("2.100", "testo 2")]
    assert L.parse_vote_refs("senato", "Em. 1.66 (1a parte), Scalfarotto", None)[1] == [("1.66", None)]
    assert L.parse_vote_refs("senato", "Em. 7.0.100/10, Valente e altri", None)[1] == [("7.0.100/10", None)]
    assert L.parse_vote_refs("senato", "ODG G1.10, Nicita e altri", None)[1] == [("g1.10", None)]
    assert L.parse_vote_refs("senato", "DDL n. 924-bis. Em. 1.236, Pirondini e altri", None) == \
        ("924-bis", [("1.236", None)])
    assert L.parse_vote_refs("senato", "Articolo 6", None)[1] == []
    assert L.parse_vote_refs("senato", "Votazione finale", None)[1] == []


def _cand(id_, date, atto="S.1"):
    return {"id": id_, "_date": date, "atto": atto}


def test_pick_candidate():
    d = dt.date
    assert L.pick_candidate([], d(2024, 1, 1)) == (None, "missing")
    # one candidate is taken even if dated a few months after the vote
    assert L.pick_candidate([_cand("a", d(2024, 6, 1))], d(2024, 1, 1))[0]["id"] == "a"
    two = [_cand("old", d(2023, 1, 1)), _cand("new", d(2024, 3, 1))]
    assert L.pick_candidate(two, d(2024, 3, 5))[0]["id"] == "new"
    assert L.pick_candidate(two, d(2023, 6, 1))[0]["id"] == "old"
    assert L.pick_candidate(two, d(2022, 1, 1)) == (None, "future")
    tie = [_cand("x", d(2024, 1, 1)), _cand("y", d(2024, 1, 1))]
    assert L.pick_candidate(tie, d(2024, 2, 1)) == (None, "ambiguous")
    bills = [_cand("x", d(2024, 1, 1), "C.1"), _cand("y", d(2023, 1, 1), "C.2")]
    assert L.pick_candidate(bills, d(2024, 2, 1)) == (None, "ambiguous")


# -------------------------------------------------------------- sub-amendments

def test_sub_parent():
    assert L.sub_parent("senato", "emendamento", "7.0.100/10") == ("7.0.100", None)
    assert L.sub_parent("senato", "emendamento", "1.1 (testo 2)/3") == ("1.1", "testo 2")
    assert L.sub_parent("senato", "emendamento", "13.0.400 testo 2/1") == ("13.0.400", "testo 2")
    assert L.sub_parent("senato", "emendamento", "7.9 (testo 3) e identici/12") == ("7.9", "testo 3")
    assert L.sub_parent("senato", "emendamento", "4.1/5ª Commissione") is None
    assert L.sub_parent("senato", "ordine_del_giorno", "G/2036/1/6") is None
    assert L.sub_parent("camera", "subEmendamento", "0.15.800.10") == ("15.800", None)
    assert L.sub_parent("camera", "emendamento", "15.800") is None


# ------------------------------------------------------------------- chunks

def test_short_text_is_one_chunk():
    assert L.chunk_text("Sopprimere l'articolo.") == ["Sopprimere l'articolo."]
    assert L.chunk_text("   ") == []


def test_long_text_chunks_bounded_and_complete():
    lines = [f"{chr(97 + i % 26)}) al comma {i}, sostituire le parole: «uno» con le seguenti: «due»;"
             for i in range(120)]
    text = "\n".join(lines)
    chunks = L.chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= L.CHUNK_SIZE for c in chunks)
    joined = "\n".join(chunks)
    assert all(line in joined for line in lines)
    # consecutive chunks share their boundary lines
    assert chunks[0].split("\n")[-1] in chunks[1]


def test_table_without_punctuation_is_cut():
    text = " ".join(["cella"] * 2000)
    chunks = L.chunk_text(text)
    assert len(chunks) > 1 and all(len(c) <= L.CHUNK_SIZE for c in chunks)


# --------------------------------------------------- signatories and relations

def _row(id_, chamber="senato", atto="S.10", sede="assemblea", numero="1.1", firmatari=(), **kw):
    row = {"id": id_, "ramo": "S" if chamber == "senato" else "C", "atto": atto, "atti_congiunti": [],
           "id_ddl": "1", "sede": sede, "numero": numero, "versione": None, "tipo": "emendamento",
           "esito": "Respinto", "firmatari": list(firmatari), "testo": "t", "testo_hash": "h",
           "gruppo_id": id_, "seduta_data": None, "data_presentazione": "2024-01-10"}
    row.update(kw)
    row["_hash"] = L.row_hash(row)
    row["_chamber"] = chamber
    row["_number_key"] = L.number_key(row["numero"])
    row["_version"] = L.normalize_version(row.get("versione"))
    row["_date"] = L.parse_date(row.get("seduta_data")) or L.parse_date(row.get("data_presentazione"))
    return row


class _Date:
    def __init__(self, d):
        self.d = d

    def to_native(self):
        return self.d


def _index(votes=()):
    gi = L.GraphIndex.__new__(L.GraphIndex)
    gi.leg = 19
    gi.person_by_key = {
        L.SENATO_PERSON + "1": "http://dati.senato.it/senatore/1",
        # senator-minister merged into its government node: matched by senato_id
        L.SENATO_PERSON + "2": "gov_rossi_mario",
        L.CAMERA_PERSON + "300": L.CAMERA_PERSON + "300",
        L.CAMERA_PERSON + "301": None,  # two persons claim this id
    }
    gi.deputy_by_name = {"zingaretti": L.CAMERA_PERSON + "302", "nicola zingaretti": L.CAMERA_PERSON + "302",
                         "rossi": None}
    gi.camera_acts = {L.CAMERA_ACT.format(leg=19) + "5"}
    gi.senate_act_by_number = {"10": "http://dati.senato.it/ddl/100"}
    gi.senate_number_by_uri = {"http://dati.senato.it/ddl/100": "10"}
    gi.votes = list(votes)
    gi.session_acts = {}
    return gi


def test_signatories_matched_by_source_id():
    rows = [
        _row("S|1", firmatari=[
            {"id": "S:1", "nome": "A", "tipo": "senatore", "primo": True},
            {"id": "S:2", "nome": "Rossi", "tipo": "senatore", "primo": False},
            {"id": "S:9", "nome": "Ignoto", "tipo": "senatore", "primo": False},
            {"id": None, "nome": "Il Relatore", "tipo": "relatore", "primo": False},
        ]),
        _row("C|1", chamber="camera", atto="C.5", firmatari=[
            {"id": "C:300", "nome": "B", "tipo": "deputato", "primo": True},
            {"id": "C:301", "nome": "Doppio", "tipo": "deputato", "primo": False},
            {"id": "C:XXX", "nome": "Zingaretti", "tipo": "deputato", "primo": False},
            {"id": "C:XXX", "nome": "Rossi", "tipo": "deputato", "primo": False},
        ]),
    ]
    stats, unlinked = Counter(), {}
    rels = L.derive_relations(rows, _index(), stats, unlinked)
    assert rels["SIGNED_AMENDMENT"] == {
        ("S|1", "http://dati.senato.it/senatore/1", True),
        ("S|1", "gov_rossi_mario", False),
        ("C|1", L.CAMERA_PERSON + "300", True),
        ("C|1", L.CAMERA_PERSON + "302", False),
    }
    assert stats["camera.sign_by_name"] == 1
    assert stats["senato.sign_total"] == 3 and stats["senato.sign_not_member"] == 1
    reasons = sorted(r[2].split(" (")[0] for r in unlinked["camera.sign"] + unlinked["senato.sign"])
    assert reasons == ["id non valido 'C:XXX'", "persona ambigua", "persona assente nel grafo"]
    assert rels["AMENDS"] == {("S|1", "http://dati.senato.it/ddl/100", False),
                              ("C|1", L.CAMERA_ACT.format(leg=19) + "5", False)}


def test_votes_linked_by_bill_and_number():
    rows = [_row("S|1", numero="2.1"), _row("S|2", numero="2.2"),
            _row("S|3", numero="2.1", sede="commissione")]
    votes = [
        {"id": "v1", "session": "s", "chamber": "senato", "date": _Date(dt.date(2024, 1, 12)),
         "subject": "Emm. 2.1 e 2.2", "description": None, "acts": ["http://dati.senato.it/ddl/100"]},
        {"id": "v2", "session": "s", "chamber": "senato", "date": _Date(dt.date(2024, 1, 12)),
         "subject": "Em. 9.9, Bianchi", "description": None, "acts": ["http://dati.senato.it/ddl/100"]},
    ]
    stats, unlinked = Counter(), {}
    rels = L.derive_relations(rows, _index(votes), stats, unlinked)
    assert rels["ON_AMENDMENT"] == {("S|1", "v1", "act"), ("S|2", "v1", "act")}
    assert stats["senato.vote_total"] == 2 and stats["senato.vote_linked"] == 1
    assert unlinked["senato.vote"][0][0] == "v2"


def test_sub_of_and_resubmits():
    rows = [_row("S|1", numero="7.0.100", sede="commissione"),
            _row("S|2", numero="7.0.100/3", sede="commissione"),
            _row("S|3", numero="7.0.100", sede="assemblea", gruppo_id="S|1")]
    rels = L.derive_relations(rows, _index(), Counter(), {})
    assert rels["SUB_OF"] == {("S|2", "S|1", None)}
    assert rels["RESUBMITS"] == {("S|3", "S|1", None)}


# ---------------------------------------------------------------- idempotence

class _FakeGraph:
    """In-memory stand-in for the relation queries of apply_relations."""

    def __init__(self):
        self.rels = {k: set() for k in L.REL_QUERIES}
        self.writes = 0
        self.ops = {}
        for rtype, (read_q, create_q, delete_q) in L.REL_QUERIES.items():
            self.ops[read_q] = (rtype, "read")
            self.ops[create_q] = (rtype, "create")
            self.ops[delete_q] = (rtype, "delete")

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, rows=None, **_):
        rtype, op = self.ops[query]
        if op == "read":
            return [{"a": a, "b": b, "p": p} for a, b, p in self.rels[rtype]]
        self.writes += 1
        for r in rows:
            key = (r["a"], r["b"], r["p"])
            if op == "create":
                self.rels[rtype] = {e for e in self.rels[rtype] if e[:2] != key[:2]} | {key}
            else:
                self.rels[rtype] = {e for e in self.rels[rtype] if e[:2] != key[:2]}
        return self

    def consume(self):
        return None

    def execute_write(self, fn):
        return fn(self)


def _apply(graph, rows):
    stats = Counter()
    rels = L.derive_relations(rows, _index(), Counter(), {})
    L.apply_relations(graph, 19, rels, 2, False, None, stats)
    return stats


def test_apply_relations_is_idempotent():
    signers = [{"id": "S:1", "nome": "A", "tipo": "senatore", "primo": True},
               {"id": "S:2", "nome": "B", "tipo": "senatore", "primo": False}]
    rows = [_row("S|1", firmatari=signers), _row("S|2", numero="1.1/1", firmatari=signers[:1])]
    graph = _FakeGraph()
    first = _apply(graph, rows)
    assert first["rel.SIGNED_AMENDMENT.created"] == 3 and first["rel.SUB_OF.created"] == 1
    writes = graph.writes
    again = _apply(graph, rows)
    assert graph.writes == writes
    assert all(v == 0 for k, v in again.items() if k.endswith((".created", ".deleted")))

    # one signatory withdrawn and the first signatory changed at the source
    rows[0] = _row("S|1", firmatari=[dict(signers[1], primo=True)])
    third = _apply(graph, rows)
    assert third["rel.SIGNED_AMENDMENT.deleted"] == 2 and third["rel.SIGNED_AMENDMENT.created"] == 1
    assert ("S|1", "gov_rossi_mario", True) in graph.rels["SIGNED_AMENDMENT"]


def test_row_hash_tracks_content():
    a = _row("S|1")
    b = json.loads(json.dumps({k: v for k, v in a.items() if not k.startswith("_")}))
    assert L.row_hash(b) == a["_hash"]
    b["testo"] = "altro"
    assert L.row_hash(b) != a["_hash"]


def test_outcome_from_floor_votes():
    rows = [_row("S|1", numero="2.1", esito=None), _row("S|2", numero="2.2", esito=None),
            _row("S|3", numero="2.3")]
    d = _Date(dt.date(2024, 1, 12))
    act = ["http://dati.senato.it/ddl/100"]
    votes = [
        {"id": "v1", "session": "s", "chamber": "senato", "date": d, "subject": "Em. 2.1, Bianchi",
         "description": None, "acts": act, "outcome": "rejected"},
        {"id": "v2", "session": "s", "chamber": "senato", "date": d, "subject": "Em. 2.2 (prima parte)",
         "description": None, "acts": act, "outcome": "approved"},
        {"id": "v3", "session": "s", "chamber": "senato", "date": d, "subject": "Em. 2.2 (seconda parte)",
         "description": None, "acts": act, "outcome": "rejected"},
        {"id": "v4", "session": "s", "chamber": "senato", "date": d, "subject": "Em. 2.3, Verdi",
         "description": None, "acts": act, "outcome": "approved"},
    ]
    gi = _index(votes)
    voted = L.vote_outcomes(L.derive_relations(rows, gi, Counter(), {}), gi)
    assert voted == {"S|1": "rejected", "S|2": "mixed", "S|3": "approved"}
    p1 = L.node_props(rows[0], 19, voted["S|1"])
    assert (p1["outcome"], p1["outcome_source"]) == ("rejected", "floor_vote")
    assert p1["row_hash"] != rows[0]["_hash"]
    # the source outcome ("Respinto") wins over the vote
    p3 = L.node_props(rows[2], 19, voted["S|3"])
    assert (p3["outcome"], p3["outcome_source"]) == ("rejected", "source")
    p0 = L.node_props(rows[0], 19)
    assert "outcome" not in p0 and p0["row_hash"] == rows[0]["_hash"]
