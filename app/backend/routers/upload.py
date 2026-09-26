# -*- coding: utf-8 -*-
"""Phase 1: xlsx 업로드 파싱 라우터.

업로드된 xlsx를 pandas로 읽어 컬럼명 기준으로 BASE_COLUMNS에 매핑하고,
No.를 부여한 rows를 반환한다. 값은 모두 문자열(dtype=str, 결측은 "").
"""

import io

import deps  # noqa: F401

from fastapi import APIRouter, File, HTTPException, UploadFile

from schema import BASE_COLUMNS

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/parse")
async def parse_upload(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="xlsx/xls 파일만 지원합니다.")

    content = await file.read()
    try:
        import pandas as pd

        df = pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없습니다: {e}")

    df.columns = [str(c).strip() for c in df.columns]
    known = [c for c in BASE_COLUMNS if c in df.columns]
    extra = [c for c in df.columns if c not in BASE_COLUMNS and c != "No."]
    columns = known + extra

    rows = []
    for i, rec in enumerate(df.to_dict("records"), start=1):
        row = {c: str(rec.get(c, "")).strip() for c in columns}
        row["No."] = str(i)
        rows.append(row)

    return {"columns": ["No."] + columns, "rows": rows}
