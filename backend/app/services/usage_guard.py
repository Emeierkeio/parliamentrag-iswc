"""Per-IP query rate limiting and OpenAI quota kill-switch.

Protects the monthly OpenAI budget behind two layers:
  1. Per-IP limits on the expensive /api/query pipeline (hourly + daily).
  2. A global kill-switch that trips when OpenAI reports the quota/budget
     as exhausted (insufficient_quota); it auto-retries after a cooldown so
     the service resumes without a redeploy.

Every block is surfaced to the end user as an SSE error event with a clear,
localized explanation: why the request was blocked, when to retry, and that
the rest of the site keeps working. Limits are env-tunable:

    QUERY_LIMIT_PER_HOUR  (default 6)
    QUERY_LIMIT_PER_DAY   (default 20)
    QUOTA_RETRY_SECONDS   (default 1800)
    QUERY_EVENT           "2026-10-24..2026-10-30:60:300" raises the hourly
                          and daily limits on those days (Europe/Rome), for
                          a live demo where everyone shares the venue's IP

Counters are in-memory per worker: they reset on redeploy, which is fine —
this is abuse protection, not accounting.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

QUERY_LIMIT_PER_HOUR = int(os.environ.get("QUERY_LIMIT_PER_HOUR", "6"))
QUERY_LIMIT_PER_DAY = int(os.environ.get("QUERY_LIMIT_PER_DAY", "20"))
QUOTA_RETRY_SECONDS = int(os.environ.get("QUOTA_RETRY_SECONDS", "1800"))


def _parse_event(raw: str) -> Optional[tuple[date, date, int, int]]:
    try:
        days, per_hour, per_day = raw.strip().split(":")
        first, last = days.split("..")
        return date.fromisoformat(first), date.fromisoformat(last), int(per_hour), int(per_day)
    except ValueError:
        return None


_EVENT = _parse_event(os.environ.get("QUERY_EVENT", ""))


def limits(today: Optional[date] = None) -> tuple[int, int]:
    """(per hour, per day): the event limits on the event days, else the usual ones."""
    today = today or datetime.now(ZoneInfo("Europe/Rome")).date()
    if _EVENT and _EVENT[0] <= today <= _EVENT[1]:
        return _EVENT[2], _EVENT[3]
    return QUERY_LIMIT_PER_HOUR, QUERY_LIMIT_PER_DAY

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}
_quota_exhausted_at: Optional[float] = None


def client_ip(request) -> str:
    """Real client IP: first X-Forwarded-For entry (Railway / Next proxy),
    falling back to the direct peer address."""
    if request is None:
        return "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_and_register(ip: str) -> tuple[bool, str, int]:
    """Check the per-IP limits and register the hit if allowed.

    Returns (allowed, scope, retry_minutes) where scope is "hourly" or
    "daily" when blocked.
    """
    now = time.time()
    per_hour, per_day = limits()
    with _lock:
        hits = [t for t in _hits.get(ip, []) if now - t < 86400]
        hour_hits = [t for t in hits if now - t < 3600]
        if len(hits) >= per_day:
            retry_min = int((86400 - (now - min(hits))) // 60) + 1 if hits else 1440
            _hits[ip] = hits
            return False, "daily", retry_min
        if len(hour_hits) >= per_hour:
            retry_min = int((3600 - (now - min(hour_hits))) // 60) + 1 if hour_hits else 60
            _hits[ip] = hits
            return False, "hourly", retry_min
        hits.append(now)
        _hits[ip] = hits
        return True, "", 0


def quota_exhausted() -> bool:
    """True while the kill-switch is tripped. After the cooldown the flag
    clears so the next query probes OpenAI again."""
    global _quota_exhausted_at
    with _lock:
        if _quota_exhausted_at is None:
            return False
        if time.time() - _quota_exhausted_at > QUOTA_RETRY_SECONDS:
            _quota_exhausted_at = None
            return False
        return True


def mark_quota_exhausted() -> None:
    global _quota_exhausted_at
    with _lock:
        _quota_exhausted_at = time.time()


def looks_like_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "insufficient_quota" in text
        or "exceeded your current quota" in text
        or ("rate limit" in text and "billing" in text)
    )


# ---------------------------------------------------------------------------
# Localized user-facing explanations. Every block must tell the user WHY it
# happened, WHEN they can retry, and that the rest of the site still works.
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, dict[str, str]] = {
    "hourly": {
        "it": "Hai raggiunto il limite di {n} domande per ora previsto per ogni utente. Potrai porre una nuova domanda tra circa {m} minuti. Nel frattempo tutti gli altri strumenti del sito — ricerca negli atti, autorevolezza, bussola ideologica e Lavori d'Aula — restano disponibili.",
        "en": "You have reached the limit of {n} questions per hour per user. You can ask a new question in about {m} minutes. In the meantime, all the other tools on the site — acts search, authority rankings, ideological compass and chamber proceedings — remain available.",
        "fr": "Vous avez atteint la limite de {n} questions par heure et par utilisateur. Vous pourrez poser une nouvelle question dans environ {m} minutes. En attendant, tous les autres outils du site restent disponibles.",
        "de": "Sie haben das Limit von {n} Fragen pro Stunde und Nutzer erreicht. In etwa {m} Minuten können Sie eine neue Frage stellen. Alle anderen Werkzeuge der Website bleiben in der Zwischenzeit verfügbar.",
        "es": "Has alcanzado el límite de {n} preguntas por hora por usuario. Podrás hacer una nueva pregunta en unos {m} minutos. Mientras tanto, todas las demás herramientas del sitio siguen disponibles.",
        "pt": "Você atingiu o limite de {n} perguntas por hora por usuário. Poderá fazer uma nova pergunta em cerca de {m} minutos. Enquanto isso, todas as outras ferramentas do site continuam disponíveis.",
    },
    "daily": {
        "it": "Hai raggiunto il limite giornaliero di {n} domande previsto per ogni utente. Potrai porre nuove domande domani. Tutti gli altri strumenti del sito — ricerca negli atti, autorevolezza, bussola ideologica e Lavori d'Aula — restano disponibili.",
        "en": "You have reached the daily limit of {n} questions per user. You can ask new questions tomorrow. All the other tools on the site — acts search, authority rankings, ideological compass and chamber proceedings — remain available.",
        "fr": "Vous avez atteint la limite quotidienne de {n} questions par utilisateur. Vous pourrez poser de nouvelles questions demain. Tous les autres outils du site restent disponibles.",
        "de": "Sie haben das Tageslimit von {n} Fragen pro Nutzer erreicht. Morgen können Sie neue Fragen stellen. Alle anderen Werkzeuge der Website bleiben verfügbar.",
        "es": "Has alcanzado el límite diario de {n} preguntas por usuario. Podrás hacer nuevas preguntas mañana. Todas las demás herramientas del sitio siguen disponibles.",
        "pt": "Você atingiu o limite diário de {n} perguntas por usuário. Poderá fazer novas perguntas amanhã. Todas as outras ferramentas do site continuam disponíveis.",
    },
    "quota": {
        "it": "Il sistema ha temporaneamente raggiunto il proprio limite mensile di utilizzo dell'intelligenza artificiale. La consultazione riprenderà automaticamente appena possibile — riprova più tardi. Tutti gli altri strumenti del sito — ricerca negli atti, autorevolezza, bussola ideologica e Lavori d'Aula — restano pienamente disponibili.",
        "en": "The system has temporarily reached its monthly AI usage limit. The consultation will resume automatically as soon as possible — please try again later. All the other tools on the site — acts search, authority rankings, ideological compass and chamber proceedings — remain fully available.",
        "fr": "Le système a temporairement atteint sa limite mensuelle d'utilisation de l'IA. La consultation reprendra automatiquement dès que possible — réessayez plus tard. Tous les autres outils du site restent entièrement disponibles.",
        "de": "Das System hat vorübergehend sein monatliches KI-Nutzungslimit erreicht. Die Konsultation wird so bald wie möglich automatisch fortgesetzt — bitte versuchen Sie es später erneut. Alle anderen Werkzeuge der Website bleiben voll verfügbar.",
        "es": "El sistema ha alcanzado temporalmente su límite mensual de uso de IA. La consulta se reanudará automáticamente lo antes posible — inténtalo de nuevo más tarde. Todas las demás herramientas del sitio siguen plenamente disponibles.",
        "pt": "O sistema atingiu temporariamente seu limite mensal de uso de IA. A consulta será retomada automaticamente assim que possível — tente novamente mais tarde. Todas as outras ferramentas do site continuam totalmente disponíveis.",
    },
}


def block_message(kind: str, locale: str, retry_minutes: int = 0) -> str:
    msgs = _MESSAGES[kind]
    text = msgs.get(locale, msgs["en"])
    n = limits()[0] if kind == "hourly" else limits()[1]
    return text.format(n=n, m=max(1, retry_minutes))
