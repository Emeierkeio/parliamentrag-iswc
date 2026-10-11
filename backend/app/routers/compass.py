"""
Standalone compass endpoint.

Returns only the ideological compass analysis for a given query,
without authority scoring or text generation.
"""
import time
import logging
import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .query import get_services
from ..services.translation import translate_compass_axes
from ..services.retrieval.scope import ScopeItem, resolve_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Compass"])


class CompassRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(default=200, ge=10, le=500)
    scope: Optional[List[ScopeItem]] = Field(default=None)


@router.post("/compass")
async def compass_endpoint(request: CompassRequest, http_request: Request):
    """Compute ideological compass for all parties on a given topic."""
    services = get_services()
    start = time.time()
    locale = (http_request.headers.get("accept-language", "it") or "it").strip()[:2].lower()

    try:
        # Non-Italian queries are translated by the rewriter before embedding.
        retrieval_result = await services["retrieval"].retrieve(
            query=request.query,
            top_k=request.top_k,
            locale=locale,
            scope=resolve_scope(request.scope, request.query),
        )
        evidence_list = retrieval_result["evidence"]

        # Include embeddings for PCA
        evidence_dicts = []
        for e in evidence_list:
            d = e.model_dump()
            if e.embedding is not None:
                d["embedding"] = e.embedding
            evidence_dicts.append(d)

        compass_result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: services["ideology"].compute_2d_text_positions(
                evidence_dicts, query=request.query),
        )

        # Axis poles are always generated in Italian so the anchored vectors
        # stay identical across UI languages; only the labels get translated.
        if locale != "it":
            compass_result = await translate_compass_axes(
                compass_result, target_lang=locale)

        elapsed_ms = round((time.time() - start) * 1000)

        return {
            "meta": compass_result.get("meta", {}),
            "axes": compass_result.get("axes", {}),
            "groups": compass_result.get("groups", []),
            "scatter_sample": compass_result.get("scatter_sample", []),
            "computation_time_ms": elapsed_ms,
        }

    except Exception as e:
        logger.error(f"Compass endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
