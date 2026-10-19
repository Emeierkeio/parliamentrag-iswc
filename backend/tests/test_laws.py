"""The published law of an act: label, links and the shared lookup."""

from app.models.timeline import ActInfo, VoteActRef
from app.services.laws import italian_date, law_ref, laws_for_acts

C2822B = "http://dati.camera.it/ocd/attocamera.rdf/ac19_2822-B"
ROW = {
    "uri": C2822B,
    "kind": "legge",
    "number": 180,
    "date": "2026-10-09",
    "eli": "https://www.normattiva.it/eli/id/2026/10/09/26G00201/ORIGINAL",
    "normattiva_url": "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2026;180",
    "gu_number": 235,
    "gu_date": "2026-10-09",
    "title": "Disposizioni in materia di elezioni",
}


class FakeNeo4j:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, cypher, params):
        self.calls.append(params)
        return [r for r in self.rows if r["uri"] in params["uris"]]


def test_label_and_links():
    law = law_ref(ROW)
    assert law.label == "Legge n. 180 del 9 ottobre 2026"
    assert law.eli.startswith("https://www.normattiva.it/eli/")
    assert law.gu_number == 235 and law.gu_date == "2026-10-09"


def test_constitutional_law_label():
    law = law_ref({**ROW, "kind": "legge_costituzionale", "number": 1, "date": "2025-01-01"})
    assert law.label == "Legge costituzionale n. 1 del 1 gennaio 2025"


def test_italian_date_rejects_garbage():
    assert italian_date(None) is None
    assert italian_date("2026-13-01") is None
    assert italian_date("2026-10-09T00:00:00") == "9 ottobre 2026"


def test_lookup_keeps_only_acts_that_became_law():
    db = FakeNeo4j([ROW])
    laws = laws_for_acts(db, [C2822B, "http://dati.senato.it/ddl/99999", None, C2822B])
    assert list(laws) == [C2822B]
    assert db.calls == [{"uris": [C2822B, "http://dati.senato.it/ddl/99999"]}]


def test_lookup_skips_the_query_without_uris():
    db = FakeNeo4j([ROW])
    assert laws_for_acts(db, [None, ""]) == {}
    assert db.calls == []


def test_law_is_optional_in_the_act_models():
    assert VoteActRef(title="x").law is None
    assert ActInfo(id=C2822B, law=law_ref(ROW)).model_dump()["law"]["number"] == 180
