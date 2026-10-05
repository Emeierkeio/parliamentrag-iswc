"""
download_senate.py — AKN XML download utilities for Senate stenografici.

Downloads stenographic AKN files from senato.it.

Discovery strategy:
1. Obtain an AWS WAF token via headless Playwright (senato.it sits behind an
   AWS WAF JavaScript challenge — plain HTTP clients get HTTP 202 with an
   empty challenge page).
2. Enumerate BGT IDs for every year of the legislature via the listing page
   `?year=YYYY` filter (the unfiltered page only shows the most recent
   sessions).
3. For each BGT ID not already downloaded (tracked in bgt_index.json),
   fetch the .akn file and name it by the FRBRnumber session number.

No Neo4j dependency. No database writes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

logger = logging.getLogger(__name__)

__all__ = ["download_senate_xmls"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURRENT_LEGISLATURE = 19

# Current legislature listing; past legislatures live under /legislature/{leg}/
SENATE_LISTING_URL = (
    "https://www.senato.it/lavori/assemblea/resoconti-elenco-cronologico"
)
SENATE_LISTING_URL_PAST = (
    "https://www.senato.it/legislature/{leg}"
    "/lavori/assemblea/resoconti-elenco-cronologico"
)

SENATE_AKN_URL = "https://www.senato.it/leg/{leg}/BGT/Testi/Resaula/{bgt_id:08d}.akn"
# Full record as a web page, for sittings listed without an AKN file.
SENATE_HTML_URL = "https://www.senato.it/show-doc?leg={leg}&tipodoc=Resaula&id={bgt_id}&part=doc_dc"

# Calendar-year span of each legislature (end None = still running)
LEGISLATURE_YEARS: dict[int, tuple[int, int | None]] = {
    17: (2013, 2018),
    18: (2018, 2022),
    19: (2022, None),
}

# A real browser UA — the WAF token is bound to browser-like requests
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03"


def _bgt_id_pattern(legislature: int) -> re.Pattern[str]:
    return re.compile(
        rf'show-doc\?leg={legislature}&(?:amp;)?tipodoc=Resaula&(?:amp;)?id=(\d+)'
    )

# Tracks which BGT IDs have already been downloaded (bgt_id -> filename).
# Needed because files are named by session number, which is only known
# after downloading — without this index every run would refetch everything.
BGT_INDEX_FILENAME = "bgt_index.json"

REQUEST_DELAY_SECONDS = 1.0

# ---------------------------------------------------------------------------
# WAF token acquisition (Playwright)
# ---------------------------------------------------------------------------


def _get_waf_token() -> str | None:
    """Solve the AWS WAF challenge with headless Chromium and return the token.

    Returns None if Playwright is unavailable or the challenge fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "playwright not installed — run: pip install playwright && playwright install chromium"
        )
        return None

    logger.info("Solving AWS WAF challenge via headless browser...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(locale="it-IT")
            page = ctx.new_page()
            page.goto(SENATE_LISTING_URL, wait_until="domcontentloaded", timeout=60_000)
            # The challenge page auto-solves and reloads into the real page
            page.wait_for_selector("a[href*='tipodoc=Resaula']", timeout=45_000)
            token = next(
                (c["value"] for c in ctx.cookies() if c["name"] == "aws-waf-token"),
                None,
            )
            browser.close()
        if token:
            logger.info("WAF token obtained")
        else:
            logger.warning("Challenge page loaded but no aws-waf-token cookie found")
        return token
    except Exception as exc:
        logger.error("WAF challenge failed: %s", exc)
        return None


def _make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    })
    session.cookies.set("aws-waf-token", token, domain=".senato.it")
    return session


def _is_challenge(response: requests.Response) -> bool:
    """True when the WAF served its JS challenge instead of real content."""
    if response.status_code == 202:
        return True
    return "awswaf" in response.text[:3000].lower() and len(response.text) < 10_000


# ---------------------------------------------------------------------------
# BGT ID discovery
# ---------------------------------------------------------------------------


def _discover_bgt_ids(session: requests.Session, legislature: int) -> list[int]:
    """Enumerate all Resaula BGT IDs for the legislature, year by year."""
    start_year, end_year = LEGISLATURE_YEARS.get(
        legislature, (2022, None)
    )
    if end_year is None:
        end_year = date.today().year
    base_url = (
        SENATE_LISTING_URL
        if legislature == CURRENT_LEGISLATURE
        else SENATE_LISTING_URL_PAST.format(leg=legislature)
    )
    pattern = _bgt_id_pattern(legislature)
    all_ids: set[int] = set()
    for year in range(start_year, end_year + 1):
        url = f"{base_url}?year={year}"
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch listing for %d: %s", year, exc)
            continue
        if _is_challenge(response):
            logger.warning("WAF challenge on listing for %d — token may have expired", year)
            continue
        year_ids = {int(m) for m in pattern.findall(response.text)}
        logger.info("Year %d: %d resoconti", year, len(year_ids))
        all_ids |= year_ids
        time.sleep(REQUEST_DELAY_SECONDS)
    return sorted(all_ids)


# ---------------------------------------------------------------------------
# BGT index (bgt_id -> filename) persistence
# ---------------------------------------------------------------------------


def _load_bgt_index(xml_dir: str) -> dict[str, str]:
    path = os.path.join(xml_dir, BGT_INDEX_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt %s — starting fresh", BGT_INDEX_FILENAME)
        return {}


def _save_bgt_index(xml_dir: str, index: dict[str, str]) -> None:
    path = os.path.join(xml_dir, BGT_INDEX_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def download_senate_xmls(
    xml_dir: str,
    limit: int | None = None,
    legislature: int = CURRENT_LEGISLATURE,
) -> int:
    """Download Senate AKN stenographic files from senato.it.

    Args:
        xml_dir: Target directory for downloaded AKN files.
        limit: If set, stop after downloading this many new files (for testing).
        legislature: Legislature number (default 19).

    Returns:
        Number of new files downloaded in this run.
    """
    os.makedirs(xml_dir, exist_ok=True)

    token = _get_waf_token()
    if not token:
        logger.error("Cannot proceed without a WAF token")
        return 0
    session = _make_session(token)

    bgt_ids = _discover_bgt_ids(session, legislature)
    if not bgt_ids:
        logger.warning("No BGT IDs found — listing page may have changed")
        return 0
    logger.info("Discovered %d total BGT IDs", len(bgt_ids))

    bgt_index = _load_bgt_index(xml_dir)
    existing_files = set(os.listdir(xml_dir))

    # Only fetch IDs we have not downloaded yet (or whose file went missing)
    pending = [
        b for b in bgt_ids
        if str(b) not in bgt_index or bgt_index[str(b)] not in existing_files
    ]
    logger.info("%d already downloaded, %d to fetch", len(bgt_ids) - len(pending), len(pending))

    downloaded = 0
    token_refreshes = 0
    for i, bgt_id in enumerate(pending, 1):
        if limit is not None and downloaded >= limit:
            logger.info("Download limit (%d) reached — stopping", limit)
            break
        akn_url = SENATE_AKN_URL.format(leg=legislature, bgt_id=bgt_id)
        logger.info("[%d/%d] Fetching %s", i, len(pending), akn_url)

        content: str | None = None
        for attempt in range(3):
            try:
                response = session.get(akn_url, timeout=60)
                if _is_challenge(response):
                    # Token expired mid-run: solve the challenge again (max 3 per run)
                    if token_refreshes >= 3:
                        logger.error("WAF token expired too many times — aborting run")
                        _save_bgt_index(xml_dir, bgt_index)
                        return downloaded
                    token_refreshes += 1
                    logger.info("WAF token expired — refreshing (%d/3)", token_refreshes)
                    new_token = _get_waf_token()
                    if not new_token:
                        _save_bgt_index(xml_dir, bgt_index)
                        return downloaded
                    session = _make_session(new_token)
                    continue
                response.raise_for_status()
                content = response.text
                break
            except Exception as exc:
                logger.warning("Attempt %d failed for %s: %s", attempt + 1, akn_url, exc)
                time.sleep(5 * (attempt + 1))

        if content is None:
            html_name = _download_html_record(session, xml_dir, legislature, bgt_id)
            if html_name:
                bgt_index[str(bgt_id)] = html_name
                existing_files.add(html_name)
                downloaded += 1
                logger.info("Downloaded web record: %s (BGT ID %d, no AKN)", html_name, bgt_id)
            else:
                logger.warning("Giving up on BGT %d", bgt_id)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        session_num = _extract_session_number(content)
        if session_num is None:
            logger.warning("Could not parse session number from BGT %d — skipping", bgt_id)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        filename = f"resaula_leg{legislature}_{session_num:04d}.akn"
        filepath = os.path.join(xml_dir, filename)
        if filename in existing_files:
            # File already on disk from a pre-index run — just record the mapping
            bgt_index[str(bgt_id)] = filename
            logger.debug("Already on disk: %s", filename)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            bgt_index[str(bgt_id)] = filename
            existing_files.add(filename)
            downloaded += 1
            logger.info("Downloaded: %s (BGT ID %d)", filename, bgt_id)
        except OSError as exc:
            logger.error("Failed to write %s: %s", filepath, exc)

        # Persist the index as we go so an interrupted run loses nothing
        if downloaded % 10 == 0:
            _save_bgt_index(xml_dir, bgt_index)

        time.sleep(REQUEST_DELAY_SECONDS)

    _save_bgt_index(xml_dir, bgt_index)
    logger.info("Senate download complete. New files: %d", downloaded)
    return downloaded


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _download_html_record(session: requests.Session, xml_dir: str, legislature: int, bgt_id: int) -> str | None:
    """Save the web version of a record whose AKN file is missing.

    Returns the file name, or None when the page is not a sitting record.
    """
    from senate_html_parser import parse_title

    url = SENATE_HTML_URL.format(leg=legislature, bgt_id=bgt_id)
    try:
        response = session.get(url, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Web record unavailable for BGT %d: %s", bgt_id, exc)
        return None
    if _is_challenge(response) or 'class="bgt"' not in response.text:
        logger.warning("Web record for BGT %d has no record body", bgt_id)
        return None
    title = parse_title(response.text)
    if title is None:
        return None
    filename = f"resaula_leg{legislature}_{title[0]:04d}.html"
    with open(os.path.join(xml_dir, filename), "w", encoding="utf-8") as f:
        f.write(response.text)
    return filename


def _extract_session_number(akn_content: str) -> int | None:
    """Parse FRBRnumber value from AKN XML content string.

    Returns the session number integer, or None if not parseable.
    """
    try:
        root = ET.fromstring(akn_content)
    except ET.ParseError:
        return None

    # Try namespaced search first
    frbrnum = root.find(
        f".//{{{AKN_NS}}}FRBRnumber"
    )
    if frbrnum is None:
        # Fallback: search without namespace
        frbrnum = root.find(".//FRBRnumber")

    if frbrnum is None:
        return None

    value = frbrnum.get("value", "")
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    download_senate_xmls(os.path.join(base, "data", "senate_xml"))
