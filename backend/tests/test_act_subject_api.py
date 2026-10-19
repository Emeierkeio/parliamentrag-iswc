"""The subject of a voted motion or resolution reaches the vote API."""

import asyncio

from app.models.timeline import ActInfo, VoteInfo
from app.services.timeline_service import get_vote_detail

META = {
    "id": "senato_leg19_sed017_v001", "number": 1,
    "subject": "Comunicazioni Ministro difesa. Proposta di risoluzione n. 2 (testo 2), Paita e altri",
    "description": None,
    "acts": [{"uri": "senato:19:aic:6/00008", "title": "RISOLUZIONE IN ASSEMBLEA 6/00008",
              "subject": "Comunicazioni del Ministro della difesa", "text_pdf": None}],
    "secret_vote": False, "outcome": "approved", "vote_type": None, "in_favor": 1, "against": 0,
    "abstained": 0, "present": 1, "voters": 1, "majority": 1, "on_mission": 0,
    "session_date": "2022-12-13", "session_number": 17, "legislature": 19, "chamber": "senato",
}


class FakeNeo4j:
    def query_single(self, cypher, params):
        return META

    def query(self, cypher, params):
        return []


def test_vote_detail_carries_the_act_subject():
    detail = asyncio.run(get_vote_detail(FakeNeo4j(), META["id"]))
    assert [a.subject for a in detail.acts] == ["Comunicazioni del Ministro della difesa"]
    assert detail.acts[0].title == "RISOLUZIONE IN ASSEMBLEA 6/00008"


def test_subject_is_optional_in_the_models():
    assert VoteInfo(id="v", number=1).act_subject is None
    assert ActInfo(id="a").subject is None
