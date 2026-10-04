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
    """쿼리 행 각각에 대해 기준 행 중 상위 유사 후보를 검색한다.

    Args:
        body (SimilarityBody): query_rows, reference_rows, top_k를 담은 요청 본문.

    Returns:
        dict: {"results": [...]} 형식. 각 쿼리별 유사 후보 목록.
    """
    results = search(body.query_rows, body.reference_rows, top_k=body.top_k)
    return {"results": results}
