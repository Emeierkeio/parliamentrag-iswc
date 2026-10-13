"""Text archive: which scopes it covers and how it overwrites Neo4j rows."""
from app.services import archive
from app.services.archive import RETRIEVAL_ROW, TextArchive, archive_scopes, fill_rows


def test_archive_off_without_url(monkeypatch):
    monkeypatch.delenv("ARCHIVE_URL", raising=False)
    monkeypatch.setenv("ARCHIVE_SCOPES", "senato_19")
    assert archive_scopes() == ()
    rows = [{"chunk_id": "c1", "chunk_text": "neo4j"}]
    assert fill_rows(rows, **RETRIEVAL_ROW) == [{"chunk_id": "c1", "chunk_text": "neo4j"}]


def test_archive_scopes_from_env(monkeypatch):
    monkeypatch.setenv("ARCHIVE_URL", "postgresql://x")
    monkeypatch.setenv("ARCHIVE_SCOPES", "senato_19, camera_18,bad")
    assert archive_scopes() == (("senato", 19), ("camera", 18))


class _FakeArchive(TextArchive):
    def __init__(self):
        self.scopes = (("senato", 19),)

    def chunks(self, ids):
        data = {"s1": {"text": "testo senato", "embedding": [0.1, 0.2], "speech_id": "sp1"}}
        return {i: data[i] for i in ids if i in data}

    def speeches(self, ids):
        return {i: "intervento intero" for i in ids if i == "sp1"}


def test_fill_overwrites_archived_rows_only():
    rows = [
        {"chunk_id": "s1", "speech_id": "sp1", "chunk_text": None, "embedding": None, "text": None},
        {"chunk_id": "c1", "speech_id": "cp1", "chunk_text": "camera", "embedding": [1.0], "text": "tutto"},
    ]
    _FakeArchive().fill(rows, **RETRIEVAL_ROW)
    assert rows[0] == {"chunk_id": "s1", "speech_id": "sp1", "chunk_text": "testo senato",
                       "embedding": [0.1, 0.2], "text": "intervento intero"}
    assert rows[1]["chunk_text"] == "camera" and rows[1]["text"] == "tutto"


def test_fill_neighbor_keys(monkeypatch):
    monkeypatch.setattr(archive, "get_archive", lambda: _FakeArchive())
    rows = fill_rows(
        [{"prev_id": "s1", "prev_text": None, "next_id": None, "speech_id": "sp1", "speech_text": None}],
        chunk_fields={"prev_id": {"prev_text": "text"}, "next_id": {"next_text": "text"}},
        speech_fields={"speech_id": "speech_text"},
    )
    assert rows[0]["prev_text"] == "testo senato"
    assert rows[0]["speech_text"] == "intervento intero"
    assert "next_text" not in rows[0]
