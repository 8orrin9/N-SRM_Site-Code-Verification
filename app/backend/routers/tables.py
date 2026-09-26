# -*- coding: utf-8 -*-
"""공통 테이블 CRUD 라우터 (메뉴별 저장/불러오기)."""

import deps  # noqa: F401

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import storage

router = APIRouter(prefix="/api/tables", tags=["tables"])


class SaveTableBody(BaseModel):
    name: str
    columns: list[str]
    rows: list[dict]
    overwrite: bool = False


@router.get("")
def get_tables(menu: str | None = None):
    return {"tables": storage.list_tables(menu)}


@router.get("/{menu}/{name}")
def get_table(menu: str, name: str):
    table = storage.load_table(menu, name)
    if table is None:
        raise HTTPException(status_code=404, detail="테이블을 찾을 수 없습니다.")
    return table


@router.post("/{menu}")
def post_table(menu: str, body: SaveTableBody):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="테이블 이름이 비어 있습니다.")
    try:
        meta = storage.save_table(menu, body.name.strip(), body.columns,
                                  body.rows, overwrite=body.overwrite)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="같은 이름의 테이블이 이미 있습니다.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"meta": meta}


@router.delete("/{menu}/{name}")
def remove_table(menu: str, name: str):
    return {"ok": storage.delete_table(menu, name)}
