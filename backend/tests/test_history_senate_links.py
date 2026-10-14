"""Saved chats get the senato.it link of their Senate speeches."""
from app.routers.history import _add_senate_links

URL = ("https://www.senato.it/show-doc?leg=19&tipodoc=Resaula&id=1523863&idoggetto=0"
       "&part=doc_dc-ressten_rs-gentit_vdnl-intervento_pirondinim5s")


class _Client:
    def __init__(self):
        self.ids = None

    def query(self, cypher, params):
        self.ids = sorted(params["ids"])
        return [{"id": "sen_leg19_sed463_p36417_deb2_0", "url": URL}]


def test_senate_citations_and_interventions_get_the_stored_url():
    citations = [
        {"intervention_id": "sen_leg19_sed463_p36417_deb2_0"},
        {"intervention_id": "leg19_sed510_tit00040.int00080"},
        {"intervention_id": "sen_leg19_sed1_p1_deb0_0", "url": "https://kept"},
    ]
    stats = {"interventions_detail": [{"speech_id": "sen_leg19_sed463_p36417_deb2_0"}]}
    client = _Client()
    _add_senate_links(client, citations, stats)
    assert client.ids == ["sen_leg19_sed463_p36417_deb2_0"]
    assert citations[0]["url"] == URL
    assert "url" not in citations[1]
    assert citations[2]["url"] == "https://kept"
    assert stats["interventions_detail"][0]["url"] == URL


def test_no_lookup_without_senate_items():
    client = _Client()
    _add_senate_links(client, [{"intervention_id": "leg19_sed1_tit1"}], None)
    assert client.ids is None
