# -*- coding: utf-8 -*-
"""Phase 3: 중복 식별 라우터."""

import deps  # noqa: F401

from fastapi import APIRouter
from pydantic import BaseModel

from services.dedup_service import run_dedup

router = APIRouter(prefix="/api/dedup", tags=["dedup"])


class Thresholds(BaseModel):
    name_threshold: float | None = None   # 업체명 SIM (0~1)
    addr_jaccard: float | None = None      # 주소 하위 레벨 Jaccard (0~1)
    coord_m: float | None = None           # 좌표 동일 판정 거리(m)
    code_max_edits: int | None = None      # 코드/Duns 유사 최대 편집거리


class DedupBody(BaseModel):
    rows: list[dict]
    thresholds: Thresholds | None = None


@router.post("")
def post_dedup(body: DedupBody):
    """중복 식별을 수행한다.

    Args:
        body (DedupBody): rows와 선택적 임계치(thresholds)를 담은 요청 본문.

    Returns:
        dict: 코어 dedup 결과(클러스터, 의심 엣지 등).
    """
    thr = body.thresholds.model_dump(exclude_none=True) if body.thresholds else None
    result = run_dedup(body.rows, thr)
    return result
