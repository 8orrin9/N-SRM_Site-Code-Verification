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
    """저장된 테이블 메타 목록을 반환한다.

    Args:
        menu (str | None): 필터링할 메뉴. None이면 전체.

    Returns:
        dict: {"tables": [메타 dict, ...]}.
    """
    return {"tables": storage.list_tables(menu)}


@router.get("/{menu}/{name}")
def get_table(menu: str, name: str):
    """특정 테이블을 로드한다.

    Args:
        menu (str): 메뉴 이름.
        name (str): 테이블 이름.

    Returns:
        dict: 테이블 전체({name, menu, columns, rows, saved_at}).

    Raises:
        HTTPException: 테이블이 없으면 404.
    """
    table = storage.load_table(menu, name)
    if table is None:
        raise HTTPException(status_code=404, detail="테이블을 찾을 수 없습니다.")
    return table


@router.post("/{menu}")
def post_table(menu: str, body: SaveTableBody):
    """테이블을 저장한다.

    Args:
        menu (str): 메뉴 이름.
        body (SaveTableBody): name, columns, rows, overwrite를 담은 요청 본문.

    Returns:
        dict: {"meta": 저장된 테이블 메타}.

    Raises:
        HTTPException: 이름이 비면 400, 중복이면 409, 메뉴 오류면 400.
    """
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
    """테이블을 삭제한다.

    Args:
        menu (str): 메뉴 이름.
        name (str): 테이블 이름.

    Returns:
        dict: {"ok": 삭제 전 파일 존재 여부(bool)}.
    """
    return {"ok": storage.delete_table(menu, name)}
