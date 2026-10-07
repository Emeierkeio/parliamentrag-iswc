"""
Multi-View RAG API for Italian Parliamentary Data.

FastAPI application entry point.
"""
import os
import sys
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .log_context import query_id_var

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routers import query_router, evidence_router, config_router, chat_router, history_router
from .routers.graph import router as graph_router
from .routers.search import router as search_router
from .routers.survey import router as survey_router
from .routers.evaluation import router as evaluation_router
from .routers.feedback import router as feedback_router
from .routers.newsletter import router as newsletter_router
from .routers.authority import router as authority_router
from .routers.compass import router as compass_router
from .routers.timeline import router as timeline_router
from .routers.data import router as data_router
from .config import MAINTENANCE_MODE, get_config, get_settings
from .services.api_keys import api_key_middleware


class _ContextEnricher(logging.Filter):
    """Enrich every record with:

    - qid: correlation id of the current query ("-" outside a query)
    - shortname: logger name without the app.services./app.routers./app.
      prefixes, so lines stay aligned and readable (third-party logger
      names pass through unchanged: langsmith.client, uvicorn.access, ...)
    """
    _PREFIXES = ("app.services.", "app.routers.", "app.")

    def filter(self, record: logging.LogRecord) -> bool:
        record.qid = query_id_var.get()
        name = record.name
        for prefix in self._PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        record.shortname = name
        return True


class _RepeatSuppressFilter(logging.Filter):
    """Suppress repetitions of the same message within a time window.

    The first occurrence passes; identical replicas are counted and
    summarised on the next pass. Built for langsmith.client, which on an
    invalid key repeats the same 403 for every trace batch.
    """
    def __init__(self, window_seconds: float = 300.0):
        super().__init__()
        self.window = window_seconds
        self._seen: dict = {}  # (levelno, msg[:100]) -> [last_pass, suppressed_count]

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.levelno, record.getMessage()[:100])
        now = time.monotonic()
        entry = self._seen.get(key)
        if entry is None or now - entry[0] >= self.window:
            suppressed = entry[1] if entry else 0
            self._seen[key] = [now, 0]
            if suppressed:
                record.msg = (
                    f"{record.getMessage()} "
                    f"[+{suppressed} identical repetitions suppressed]"
                )
                record.args = ()
            return True
        entry[1] += 1
        return False


def setup_logging():
    """Configure logging to the console and two rotating log files.

    - logs/app_TIMESTAMP.log   : INFO+  — clean operational log, no library noise
    - logs/debug_TIMESTAMP.log : DEBUG+ — full trace for investigation

    Line format: timestamp.millis [LEVEL] [qid] module - message,
    where qid is the query correlation id ("-" for startup/infra logs).

    Noisy libraries (httpx, urllib3, ...) are silenced to WARNING; uvicorn is
    redirected to our handlers so the whole process logs in one format.
    Modules under active investigation are raised to DEBUG explicitly so
    their detail ends up in the debug file.
    """
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    app_log_file   = log_dir / f"app_{timestamp}.log"
    debug_log_file = log_dir / f"debug_{timestamp}.log"

    # Milliseconds via %(msecs)03d: datefmt does not support %f
    fmt = "%(asctime)s.%(msecs)03d [%(levelname)-8s] [%(qid)s] %(shortname)-30s %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    enricher = _ContextEnricher()

    # The root logger must stay at DEBUG: individual handlers/loggers filter the rest
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console: INFO+ (visible during development)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(enricher)

    # App log: INFO+, 20 MB rotating, 10 backups
    app_handler = RotatingFileHandler(
        app_log_file,
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)
    app_handler.addFilter(enricher)

    # Debug log: DEBUG+, 50 MB rotating, 5 backups
    debug_handler = RotatingFileHandler(
        debug_log_file,
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)
    debug_handler.addFilter(enricher)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(debug_handler)

    # Silence noisy third-party libraries at the logger level, so the
    # filter applies uniformly to every handler.
    _NOISY_LIBS = (
        "httpx",
        "httpcore",
        "urllib3",
        "openai",
        "neo4j.notifications",
    )
    for lib in _NOISY_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)
    # 01N42 notifications (missing properties/relationships) are expected
    # noise while the backend is dual-compat v1/v2: each DB ignores the
    # other's branches.
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    # langsmith retries trace uploads on every batch: with an invalid key it
    # repeats the same 403 dozens of times per query. The first warning passes,
    # replicas are counted and summarised every 5 minutes.
    logging.getLogger("langsmith.client").addFilter(_RepeatSuppressFilter())

    # Uvicorn: drop its handlers and let records propagate to root, so the
    # server, access log and app all log in the same format.
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    # Modules under active investigation → explicit DEBUG: their detail goes
    # to the debug file without spamming the operational log (which stays at INFO).
    _DEBUG_MODULES = (
        "app.services.generation.integrator",       # corrupt citations context
        "app.services.generation.coherence_validator",  # embedding scores raw
    )
    for mod in _DEBUG_MODULES:
        logging.getLogger(mod).setLevel(logging.DEBUG)

    return app_log_file, debug_log_file


_app_log, _debug_log = setup_logging()
logger = logging.getLogger(__name__)
logger.info(f"[STARTUP] App log  : {_app_log}")
logger.info(f"[STARTUP] Debug log: {_debug_log}")

# LangSmith tracing must be initialised before any OpenAI client is created.
from .tracing import init_tracing  # noqa: E402
init_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Multi-View RAG API...")

    # Default executor that propagates contextvars: logs emitted in
    # run_in_executor threads (retrieval, authority, compass) keep the
    # query id instead of showing "-"
    import asyncio
    from .log_context import ContextPropagatingExecutor
    asyncio.get_running_loop().set_default_executor(ContextPropagatingExecutor())

    # Validate configuration
    try:
        config = get_config()
        settings = get_settings()
        logger.info(f"Configuration loaded from: {config.config_dir}")
        logger.info(f"Neo4j URI: {settings.neo4j_uri}")
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        raise

    # Warm up Neo4j vector index to avoid cold start latency
    await _warmup_neo4j_index(settings)

    from .routers.history import ensure_constraint
    ensure_constraint()
    from .routers.survey import ensure_survey_constraint
    ensure_survey_constraint()

    from .routers.history import _get_client
    from .services import retention
    purger = asyncio.create_task(retention.run_daily(_get_client))

    yield

    logger.info("Shutting down Multi-View RAG API...")
    await retention.stop(purger)


async def _warmup_neo4j_index(settings):
    """
    Warm up Neo4j vector index by running a dummy query.

    This forces Neo4j to load the vector index into memory,
    eliminating the 15-18s cold start penalty on first real query.
    """
    from .services.neo4j_client import Neo4jClient

    logger.info("[WARMUP] Starting Neo4j vector index warmup...")
    start_time = time.time()

    try:
        client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        # Create a dummy embedding with positive L2 norm (Neo4j requires non-zero vectors)
        # Using a normalized vector: [1/sqrt(1536), 1/sqrt(1536), ...]
        import math
        norm_value = 1.0 / math.sqrt(1536)
        dummy_embedding = [norm_value] * 1536

        # Run a minimal vector query to force index loading
        warmup_query = """
        CALL db.index.vector.queryNodes('chunk_embedding_index', 1, $embedding)
        YIELD node, score
        RETURN count(node) as cnt
        """

        client.query(warmup_query, {"embedding": dummy_embedding})

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[WARMUP] Neo4j vector index loaded in {elapsed:.1f}ms")

        client.close()

    except Exception as e:
        logger.warning(f"[WARMUP] Neo4j warmup failed (non-critical): {e}")


app = FastAPI(
    title="Multi-View RAG API",
    description="""
    Multi-View Retrieval-Augmented Generation system for Italian Parliamentary Data.

    ## Features
    - Dual-channel retrieval (dense + graph)
    - Query-dependent authority scoring
    - Ideological compass for multi-view coverage
    - 4-stage generation pipeline with exact citations

    ## Endpoints
    - `POST /api/chat` - Main chat endpoint (SSE streaming, frontend-compatible)
    - `POST /api/query` - Alternative query endpoint
    - `GET /api/evidence/{id}` - Get full evidence details
    - `GET /api/config` - Get system configuration

    ## Citation Integrity
    All citations are extracted via exact offset-based extraction;
    no fuzzy matching is used.
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# The site calls the backend through its own Next.js proxy (server to
# server), so CORS only matters for direct browser calls during development.
# CORS_EXTRA_ORIGINS adds comma-separated origins without a code change.
_CORS_ORIGINS = [
    "https://parliamentrag.it",
    "https://www.parliamentrag.it",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
] + [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    # Railway service and PR preview domains of this project
    allow_origin_regex=r"^https://parliamentrag[a-z0-9-]*\.up\.railway\.app$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def maintenance_middleware(request: Request, call_next):
    """Block all requests with 503 when MAINTENANCE_MODE is True."""
    if MAINTENANCE_MODE:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Sistema in manutenzione. Torneremo presto.",
                "maintenance": True,
            },
            headers={"Retry-After": "3600"},
        )
    return await call_next(request)


# Admin-only endpoints need an admin X-API-Key; denied when none is configured
app.middleware("http")(api_key_middleware)


app.include_router(query_router)
app.include_router(evidence_router)
app.include_router(config_router)
app.include_router(chat_router)  # Frontend-compatible chat endpoint
app.include_router(history_router)  # Conversation history
app.include_router(graph_router)  # Graph exploration
app.include_router(search_router)  # Parliamentary record search
app.include_router(survey_router)  # User surveys/evaluations
app.include_router(evaluation_router)  # Evaluation dashboard
app.include_router(authority_router)  # Authority ranking by topic
app.include_router(compass_router)  # Standalone ideological compass
app.include_router(timeline_router)  # Parliamentary timeline (sessions/debates)
app.include_router(data_router)  # Open data (RDF dump downloads)
app.include_router(feedback_router)  # In-app tool feedback (issue #21)
app.include_router(newsletter_router)  # Opt-in mailing list, kept apart from usage data


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Multi-View RAG API",
        "version": "1.0.0",
        "description": "Multi-View RAG for Italian Parliamentary Data",
        "docs": "/docs",
        "endpoints": {
            "query": "POST /api/query",
            "evidence": "GET /api/evidence/{id}",
            "config": "GET /api/config",
            "health": "GET /api/health",
        }
    }


if __name__ == "__main__":
    import os
    import uvicorn
    workers = int(os.environ.get("WORKERS", 4))
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=workers)
