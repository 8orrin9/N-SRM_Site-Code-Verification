# -*- coding: utf-8 -*-
"""Phase 2: 표준화 라우터."""

import deps  # noqa: F401

from fastapi import APIRouter
from pydantic import BaseModel

from schema import OUT_COLUMNS
from services.verify_service import standardize_rows

router = APIRouter(prefix="/api/standardize", tags=["standardize"])


class StandardizeBody(BaseModel):
    rows: list[dict]


@router.post("")
def post_standardize(body: StandardizeBody):
    """입력 행들을 표준화·실재검증한다.

    Args:
        body (StandardizeBody): 표준화 대상 rows를 담은 요청 본문.

    Returns:
        dict: {"columns": OUT_COLUMNS, "rows": [...]} 형식의 결과.
    """
    out_rows = standardize_rows(body.rows)
    return {"columns": OUT_COLUMNS, "rows": out_rows}
