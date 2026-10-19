"""
Speech text kept in the Postgres text archive instead of Neo4j.

Since 2026-10-13 the Senate XIX transcripts live only in the archive
(build/pg_archive.py strip removes Speech.text from the graph once archived),
and amendment texts were never in the graph (build/load_emendamenti.py), so
the dataset exports read the missing text from here. Shared by
export_rdf.py (Zenodo) and export_hf.py (Hugging Face).
"""
import os


def load_speech_texts(archive_url: str | None) -> dict[str, str]:
    """Return {speech_id: text} for every speech in the archive ({} without a URL)."""
    if not archive_url:
        return {}
    import psycopg  # only needed when the archive is used

    with psycopg.connect(archive_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, text FROM speech")
        texts = dict(cur.fetchall())
    print(f"  archive: {len(texts):,} speech texts loaded")
    return texts


def load_amendment_texts(archive_url: str | None) -> dict[str, str]:
    """Return {amendment_id: text} from the archive's amendment table ({} without a URL)."""
    if not archive_url:
        return {}
    import psycopg

    with psycopg.connect(archive_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, text FROM amendment WHERE text IS NOT NULL")
        texts = dict(cur.fetchall())
    print(f"  archive: {len(texts):,} amendment texts loaded")
    return texts


def archive_url_from_env(cli_value: str | None) -> str | None:
    """Pick --archive-url, else ARCHIVE_URL (same variable as the backend)."""
    return cli_value or os.environ.get("ARCHIVE_URL") or None


class TextCoverage:
    """Count speeches (or amendments) with and without text, per chamber, during an export."""

    # Above this share of speeches without text the dump is considered broken.
    # On staging (2026-10-14) Camera XIX had no speech without text and Senate
    # XIX none once the archive is read, so 5% only trips when a chamber lost
    # its text (archive not configured, failed load) and tolerates a few gaps.
    MAX_MISSING_SHARE = 0.05

    def __init__(self, unit: str = "speeches"):
        self.unit = unit
        self.total = {}
        self.missing = {}

    def add(self, chamber: str | None, has_text: bool):
        key = chamber or "unknown"
        self.total[key] = self.total.get(key, 0) + 1
        if not has_text:
            self.missing[key] = self.missing.get(key, 0) + 1

    def broken_chambers(self) -> list[str]:
        """Chambers whose share of speeches without text exceeds the threshold."""
        return sorted(
            chamber for chamber, n in self.total.items()
            if n and self.missing.get(chamber, 0) / n > self.MAX_MISSING_SHARE
        )

    def as_dict(self) -> dict:
        return {chamber: {self.unit: n, "without_text": self.missing.get(chamber, 0)}
                for chamber, n in sorted(self.total.items())}
