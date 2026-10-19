"""Acts of a debate: v2 acts have a uri and no id, so the list must not come
back empty. Card #136."""
import asyncio

from app.services.timeline_service import get_debate_detail

ACT = "http://dati.camera.it/ocd/attocamera.rdf/ac19_2789"


class GraphV2:
    """Answers the debate queries like the v2 graph: acts carry only a uri."""

    def query_single(self, cypher, params=None):
        return {"id": "leg19_sed727_tit00030", "title": "Caregiver familiari", "recap": None}

    def query(self, cypher, params=None):
        if "DISCUSSES" not in cypher or "HAS_VOTE" in cypher:
            return []
        act_id = ACT if "a.uri" in cypher else None
        return [{"id": act_id, "title": "Riconoscimento e tutela dei caregiver", "type": "Progetto di Legge", "subject": None}]


def test_debate_lists_its_acts():
    detail = asyncio.run(get_debate_detail(GraphV2(), "leg19_sed727_tit00030", "it"))
    assert [a.id for a in detail.acts] == [ACT]
