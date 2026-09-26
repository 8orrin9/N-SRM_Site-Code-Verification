# -*- coding: utf-8 -*-
"""Phase 4: 유사 검색 라우터."""

import deps  # noqa: F401

from fastapi import APIRouter
from pydantic import BaseModel

from services.similarity_service import search

router = APIRouter(prefix="/api/similarity", tags=["similarity"])


class SimilarityBody(BaseModel):
    query_rows: list[dict]
    reference_rows: list[dict]
    top_k: int = 8


@router.post("")
def post_similarity(body: SimilarityBody):
    results = search(body.query_rows, body.reference_rows, top_k=body.top_k)
    return {"results": results}
