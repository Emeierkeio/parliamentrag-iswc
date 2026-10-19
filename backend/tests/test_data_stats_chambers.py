"""/api/data/stats splits the counts into Camera and Senato."""

from app.routers import data as data_router

SENATE = {
    ("Speech", "sen_"): 20,
    ("Chunk", "sen_"): 80,
    ("IndividualVote", "iv_senato_"): 1000,
    ("ParliamentaryAct", "http://dati.senato.it/"): 7,
    ("ParliamentaryAct", "senato:"): 3,
}
GROUPED = {
    "MATCH (s:Session) RETURN": [{"chamber": "camera", "c": 70}, {"chamber": "senato", "c": 40}],
    "MATCH (s:Session)-[:HAS_VOTE]": [{"chamber": "camera", "c": 300}, {"chamber": "senato", "c": 90}],
    "MATCH (p:Person)": [{"chamber": "camera", "c": 430}, {"chamber": "senato", "c": 210}],
    "MATCH (:Person)": [{"chamber": "camera", "c": 12}],
    "MATCH (a:Amendment)": [{"chamber": "camera", "c": 150}, {"chamber": "senato", "c": 60}],
}


PEOPLE = [
    {"chamber": "camera", "in_office": 398, "former": 16, "life_in_office": 0, "life_former": 0},
    {"chamber": "senato", "in_office": 205, "former": 7, "life_in_office": 5, "life_former": 1},
]


class FakeClient:
    def query(self, cypher, params=None):
        if params and "life" in params:
            return PEOPLE
        if params:
            label = cypher.split("`")[1]
            return [{"c": SENATE[(label, params["p"])]}]
        for start, rows in GROUPED.items():
            if cypher.startswith(start):
                return rows
        raise AssertionError(cypher)


def test_camera_is_total_minus_senate():
    totals = {"speeches": 120, "chunks": 500, "individual_votes": 9000, "acts": 50}
    out = data_router._chamber_stats(FakeClient(), totals)
    assert out["senato"]["speeches"] == 20
    assert out["camera"]["speeches"] == 100
    assert out["senato"]["acts"] == 10
    assert out["camera"]["acts"] == 40
    assert out["camera"]["individual_votes"] == 8000


def test_grouped_counts_and_missing_chamber():
    out = data_router._chamber_stats(FakeClient(), {"speeches": None})
    assert out["camera"]["speeches"] is None
    assert out["camera"]["sessions"] == 70 and out["senato"]["sessions"] == 40
    assert out["senato"]["votes"] == 90
    assert out["senato"]["people"] == 210
    assert out["senato"]["groups"] == 0
    assert out["camera"]["amendments"] == 150 and out["senato"]["amendments"] == 60


def test_people_in_office_former_and_life_senators():
    out = data_router._chamber_stats(FakeClient(), {})
    assert out["camera"]["people_in_office"] == 398
    assert out["camera"]["people_former"] == 16
    assert "life_senators_in_office" not in out["camera"]
    assert out["senato"]["people_in_office"] == 205
    assert out["senato"]["life_senators_in_office"] == 5
    assert out["senato"]["life_senators_former"] == 1
