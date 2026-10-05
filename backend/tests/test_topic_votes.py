import asyncio

from app.services.timeline_service import search_topic_votes


class _FakeNeo4j:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, cypher, params):
        self.calls.append(params)
        return self.rows


def _row(**overrides):
    row = {
        "id": "leg19_sed209_vot_5",
        "number": 6,
        "subject": "Votazione Emendamento 1.1003 PDL n. 1275",
        "description": "Emendamento 1.1003 NISINI TIZIANA (LEGA)",
        "final_vote": None,
        "outcome": "approved",
        "in_favor": 150,
        "against": 100,
        "abstained": 5,
        "date": "2023-12-05",
        "session_number": 209,
        "act_title": "Disposizioni per l'istituzione del salario minimo (1275)",
    }
    row.update(overrides)
    return row


def test_no_topic_and_no_acts_skips_the_query():
    neo4j = _FakeNeo4j([_row()])
    assert asyncio.run(search_topic_votes(neo4j, None, [])) == []
    assert neo4j.calls == []


def test_topic_is_lowercased_and_rows_are_mapped():
    neo4j = _FakeNeo4j([_row()])
    votes = asyncio.run(search_topic_votes(neo4j, "  Salario Minimo ", ["1275"]))
    assert neo4j.calls[0]["topic"] == "salario minimo"
    assert neo4j.calls[0]["acts"] == ["1275"]
    assert votes[0].id == "leg19_sed209_vot_5"
    assert votes[0].final_vote is False
    assert votes[0].session_number == 209


class _ScriptedNeo4j:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def query(self, cypher, params):
        self.calls.append(params)
        return self.responses.pop(0)


def test_empty_phrase_falls_back_to_the_rarest_word():
    neo4j = _ScriptedNeo4j([], [{"w": "ucraina"}], [_row(id="leg19_sed1_vot_1")])
    votes = asyncio.run(search_topic_votes(neo4j, "Conflitto in Ucraina", []))
    assert neo4j.calls[1]["words"] == ["conflitto", "ucraina"]
    assert neo4j.calls[2]["topic"] == "ucraina"
    assert [v.id for v in votes] == ["leg19_sed1_vot_1"]


def test_single_word_topic_does_not_fall_back():
    neo4j = _ScriptedNeo4j([])
    assert asyncio.run(search_topic_votes(neo4j, "PNRR", [])) == []
    assert len(neo4j.calls) == 1


def test_evidence_votes_merge_title_matches_without_duplicates():
    from app.services.timeline_service import search_evidence_votes

    evidence = [dict(_row(id="leg19_sed100_vot_1", date="2023-05-10"), support=4)]
    neo4j = _ScriptedNeo4j(
        evidence,
        [_row(id="leg19_sed100_vot_1", date="2023-05-10"), _row(id="leg19_sed90_vot_2", date="2023-01-02")],
    )
    votes = asyncio.run(search_evidence_votes(neo4j, ["s1", "s2"], "sanità", []))
    assert [v.id for v in votes] == ["leg19_sed90_vot_2", "leg19_sed100_vot_1"]
    assert neo4j.calls[0]["speech_ids"] == ["s1", "s2"]


def test_evidence_votes_fall_back_to_same_session():
    from app.services.timeline_service import search_evidence_votes

    neo4j = _ScriptedNeo4j([], [], [_row(id="leg19_sed5_vot_9", date="2023-02-01")])
    votes = asyncio.run(search_evidence_votes(neo4j, ["s1"], "remigrazione", []))
    assert [(v.id, v.relation) for v in votes] == [("leg19_sed5_vot_9", "session")]
