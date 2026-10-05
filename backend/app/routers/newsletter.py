"""Opt-in mailing list for project news and evaluation surveys, held by Brevo.

The address goes straight to Brevo's double opt-in flow and is never written
to our database or logs. The request carries no chat id, query or feedback
id: linking an address to parliamentary questions would reveal political
interests (GDPR art. 9). Brevo stores the confirmation date and IP as proof
of consent and adds the unsubscribe link to every campaign.
"""
import hashlib
import logging
import re
import time
from collections import defaultdict, deque
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import get_settings
from ..services.usage_guard import client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/newsletter", tags=["Newsletter"])

BREVO_DOI_URL = "https://api.brevo.com/v3/contacts/doubleOptinConfirmation"

# Deliberately loose: valid addresses defeat strict regexes, and the
# confirmation email is the real check.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# Every accepted request makes Brevo email a confirmation link, so an open
# endpoint could flood a third party's inbox. In-memory windows are enough for
# one backend instance; addresses are kept only as hashes.
_IP_LIMIT = (5, 3600)
_EMAIL_LIMIT = (2, 86400)
_hits: dict[str, deque] = defaultdict(deque)


def _over_limit(key: str, limit: tuple[int, int]) -> bool:
    count, window = limit
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= count:
        return True
    q.append(now)
    return False


def _configured() -> bool:
    s = get_settings()
    return bool(s.brevo_api_key and s.brevo_list_id and s.brevo_doi_template_id)


# Where the form was shown. Logged without the address, to see which placement
# brings sign-ups; it says nothing about what the person asked.
Source = Literal[
    "landing", "footer", "sidebar", "mobile_menu", "feedback", "valutazione", "survey_done",
    "home", "dossier", "menu",
]


class SubscribeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    consent: Literal[True]
    source: Source | None = None


@router.get("")
async def newsletter_status():
    return {"enabled": _configured()}


@router.post("/subscribe")
async def subscribe(payload: SubscribeRequest, request: Request):
    if not _configured():
        raise HTTPException(status_code=503, detail="newsletter disabled")
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="invalid email")
    if _over_limit(f"ip:{client_ip(request)}", _IP_LIMIT):
        raise HTTPException(status_code=429, detail="too many requests")
    email_key = "email:" + hashlib.sha256(email.encode()).hexdigest()
    if _over_limit(email_key, _EMAIL_LIMIT):
        # Same answer as a fresh request: the endpoint must not reveal who
        # asked recently, and the first confirmation email is still valid.
        return {"ok": True}

    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            BREVO_DOI_URL,
            headers={"api-key": s.brevo_api_key, "accept": "application/json"},
            json={
                "email": email,
                "includeListIds": [int(s.brevo_list_id)],
                "templateId": int(s.brevo_doi_template_id),
                "redirectionUrl": f"{s.public_site_url}/newsletter/confirmed",
            },
        )
    # An address already on the list gets the same answer as a new one: the
    # endpoint must not reveal who is subscribed.
    if res.status_code >= 400 and "duplicate" not in res.text.lower():
        logger.warning(f"[NEWSLETTER] brevo {res.status_code}: {res.text[:200]}")
        raise HTTPException(status_code=502, detail="subscription failed")
    logger.info(f"[NEWSLETTER] confirmation requested source={payload.source or 'unknown'}")
    return {"ok": True}
