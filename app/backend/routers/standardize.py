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
    out_rows = standardize_rows(body.rows)
    return {"columns": OUT_COLUMNS, "rows": out_rows}
