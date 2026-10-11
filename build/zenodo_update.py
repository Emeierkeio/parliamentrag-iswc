"""
Create a new version of the ParliamentRAG Zenodo record and upload fresh dumps.

How the Zenodo archive relates to the rest of the system
--------------------------------------------------------
The live site (www.parliamentrag.it) serves the *current* graph, updated by
`make update-data`. Zenodo instead holds citable, frozen snapshots of the RDF
export: it is NOT kept in sync daily — you cut a new version only at moments
that matter (camera-ready, conference, end of legislature). Reviewers and
citations rely on a snapshot staying exactly as it was.

Zenodo DOIs: every published version gets its own DOI, plus one *concept DOI*
(10.5281/zenodo.21560331) that always resolves to the latest version. The
site links the concept DOI; the paper cites the version DOI it was written
against.

What this script does
---------------------
1. Finds the current deposition for the concept record (CONCEPT_RECID).
2. If the latest version is published, opens a new-version draft; if a draft
   already exists (e.g. the very first deposit before you press Publish, or a
   previous run of this script), it reuses that draft.
3. Replaces the dump files in the draft with the ones in dumps/rdf/
   (parliamentrag_kg.ttl always; parliamentrag_votes.nt if present locally).
   Run `make export-rdf` (add EXPORT_RDF_FLAGS="--votes" for the votes file)
   first, otherwise you would re-upload stale dumps.
4. Sets the publication_date of the draft to today.
5. Leaves the draft UNPUBLISHED and prints its URL: you review it in the
   browser and press Publish yourself — a published DOI is permanent.
   With --publish it publishes the draft right away instead (used by the
   unattended `make zenodo-release`, which sanity-checks the dumps first).

Auth: ZENODO_TOKEN in the repo-root .env (personal token with scopes
deposit:write + deposit:actions, from zenodo.org/account/settings/applications).

Usage:
    python build/zenodo_update.py [--dry-run] [--skip-votes] [--publish]
"""
import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
RDF_DIR = REPO_ROOT / "dumps" / "rdf"
API = "https://zenodo.org/api"
CONCEPT_RECID = "21560331"  # fixed forever; concept DOI 10.5281/zenodo.21560331
DUMP_FILES = ["parliamentrag_kg.ttl", "parliamentrag_votes.nt"]


def die(msg: str):
    sys.exit(f"ERROR: {msg}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen without touching Zenodo")
    parser.add_argument("--skip-votes", action="store_true",
                        help="do not upload parliamentrag_votes.nt (3.8 GB)")
    parser.add_argument("--publish", action="store_true",
                        help="publish the draft after upload (permanent DOI)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        die("ZENODO_TOKEN not set (checked environment and repo-root .env)")
    auth = {"access_token": token}

    wanted = DUMP_FILES[:1] if args.skip_votes else DUMP_FILES
    to_upload = [RDF_DIR / name for name in wanted if (RDF_DIR / name).is_file()]
    if not to_upload:
        die(f"no dump files in {RDF_DIR} — run `make export-rdf` first")
    print("Files to upload:")
    for p in to_upload:
        print(f"  {p.name}  ({p.stat().st_size / 1e6:,.0f} MB)")

    # 1-2. Locate the deposition for our concept record; reuse or open a draft.
    r = requests.get(f"{API}/deposit/depositions",
                     params={**auth, "q": f"conceptrecid:{CONCEPT_RECID}",
                             "all_versions": "true", "size": "50"})
    r.raise_for_status()
    depositions = r.json()
    if not depositions:
        die(f"no deposition found for concept {CONCEPT_RECID} — wrong account/token?")

    draft = next((d for d in depositions if not d["submitted"]), None)
    if draft is not None:
        print(f"Reusing existing draft {draft['id']} ({draft['links']['html']})")
    else:
        latest = max(depositions, key=lambda d: d["id"])
        print(f"Latest published version: {latest['id']} — opening a new-version draft")
        if args.dry_run:
            print("[dry-run] would POST actions/newversion, upload files, set today's date")
            return
        r = requests.post(
            f"{API}/deposit/depositions/{latest['id']}/actions/newversion", params=auth)
        r.raise_for_status()
        draft_url = r.json()["links"]["latest_draft"]
        draft = requests.get(draft_url, params=auth).json()

    if args.dry_run:
        print("[dry-run] would upload the files above into the draft and set today's date")
        return

    # 3. Replace files: drop same-named leftovers (new-version drafts inherit
    # the previous version's files), then stream the fresh dumps to the bucket.
    existing = requests.get(draft["links"]["files"], params=auth).json()
    for f in existing:
        if f["filename"] in {p.name for p in to_upload}:
            print(f"  removing old {f['filename']} from draft")
            requests.delete(f["links"]["self"], params=auth).raise_for_status()

    bucket = draft["links"]["bucket"]
    for path in to_upload:
        print(f"  uploading {path.name}...")
        with open(path, "rb") as fh:
            r = requests.put(f"{bucket}/{path.name}", params=auth, data=fh)
        r.raise_for_status()
        print(f"    done ({r.json()['size'] / 1e6:,.0f} MB on Zenodo)")

    # 4. Stamp today's date on the new version.
    today = date.today().isoformat()
    meta = draft["metadata"]
    meta["publication_date"] = today
    meta.pop("doi", None)  # the draft gets its own DOI on publish
    r = requests.put(draft["links"]["self"], params=auth, json={"metadata": meta})
    r.raise_for_status()

    # 5. Reflect the archive date on the /data page (the "aggiornato al ..."
    #    next to the Zenodo DOI). Kept in the frontend, not in the live graph,
    #    so it tracks the Zenodo publish and not make update-data.
    _stamp_data_page(today)

    # 6. Publish only on explicit request: a published DOI cannot be undone.
    if not args.publish:
        print(f"\nDraft ready — review and press Publish here:\n  {draft['links']['html']}")
        return
    r = requests.post(f"{draft['links']['self']}/actions/publish", params=auth)
    r.raise_for_status()
    published = r.json()
    print(f"\nPublished: DOI {published['doi']}\n  https://doi.org/{published['doi']}")


def _stamp_data_page(iso_date: str) -> None:
    page = REPO_ROOT / "frontend" / "src" / "app" / "data" / "page.tsx"
    try:
        text = page.read_text(encoding="utf-8")
        new, n = re.subn(
            r'const ZENODO_UPDATED = "\d{4}-\d{2}-\d{2}";',
            f'const ZENODO_UPDATED = "{iso_date}";', text,
        )
        if n == 1:
            page.write_text(new, encoding="utf-8")
            print(f"Stamped ZENODO_UPDATED = {iso_date} in data/page.tsx (commit + deploy the frontend).")
        else:
            print(f"WARNING: ZENODO_UPDATED constant not found in {page} — update it by hand.")
    except OSError as e:
        print(f"WARNING: could not stamp data/page.tsx: {e}")


if __name__ == "__main__":
    main()
