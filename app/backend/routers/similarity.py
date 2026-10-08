# -*- coding: utf-8 -*-
"""Phase 4: 유사 검색 라우터."""

import deps  # noqa: F401

from fastapi import APIRouter
from pydantic import BaseModel

from services.similarity_service import search

router = APIRouter(prefix="/api/similarity", tags=["similarity"])


class GateWeights(BaseModel):
    """"필터별 가중치" — 식별자/주소/좌표 게이트별 신뢰도 가중치."""
    duns: float | None = None
    code: float | None = None
    addr: float | None = None
    coord: float | None = None


class SimilarityWeights(BaseModel):
    """Similarity Search 종합 점수 산출에 쓰이는 조절 가능한 가중치.

    find_similar.score_pair/_WEIGHT_DEFAULTS와 키를 맞춘다. 모두 선택 값이며,
    없는 값은 코어 모듈의 기본값을 그대로 쓴다.
    """
    gate_weights: GateWeights | None = None     # 필터별 가중치
    g_strong_equal: float | None = None          # 고유성 우대(+) · Equal
    g_strong_similar: float | None = None        # 고유성 우대(+) · Similar
    veto_factor: float | None = None             # 고유성 우대(-)
    name_diff_threshold: float | None = None     # 업체명 상이 판단 임계
    weak_name_factor: float | None = None        # 업체명 상이함에 따른 감쇄도
    f_weight: float | None = None                # Base: F 가중치
    n_weight: float | None = None                # Base: N 가중치


class SimilarityBody(BaseModel):
    query_rows: list[dict]
    reference_rows: list[dict]
    top_k: int = 8
    weights: SimilarityWeights | None = None


@router.post("")
def post_similarity(body: SimilarityBody):
    """쿼리 행 각각에 대해 기준 행 중 상위 유사 후보를 검색한다.

    Args:
        body (SimilarityBody): query_rows, reference_rows, top_k,
            선택적 weights(가중치 오버라이드)를 담은 요청 본문.

    Returns:
        dict: {"results": [...]} 형식. 각 쿼리별 유사 후보 목록.
    """
    weights = body.weights.model_dump(exclude_none=True) if body.weights else None
    results = search(body.query_rows, body.reference_rows, top_k=body.top_k, weights=weights)
    return {"results": results}
