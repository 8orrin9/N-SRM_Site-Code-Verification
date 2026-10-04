# -*- coding: utf-8 -*-
"""표준화·실재검증 서비스 (process_row 얇은 래핑).

어댑터는 모듈 로드 시 1회 생성해 재사용한다. real/mock은 환경변수로만 전환.
"""

import os

import deps  # noqa: F401

from STD_VLD_260917_maps_adapter import make_adapter
from STD_VLD_260917_run_verification import process_row
from STD_VLD_260929_juso_adapter import make_juso_client

_ADAPTER = None
_JUSO = None
_JUSO_INIT = False


def _get_adapter():
    """지연 생성 + 캐시. real 모드에서 키 없으면 mock으로 폴백.

    환경변수 MAPS_ADAPTER_MODE(기본 "real")와 GOOGLE_MAPS_API_KEY를 참조한다.

    Returns:
        MapsAdapter: 생성/캐시된 Maps 어댑터(real 또는 mock).
    """
    global _ADAPTER
    if _ADAPTER is None:
        mode = os.getenv("MAPS_ADAPTER_MODE", "real")
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if mode == "real" and not key:
            mode = "mock"
        _ADAPTER = make_adapter(mode, api_key=key)
    return _ADAPTER


def _get_juso_client():
    """지연 생성 + 캐시. JUSO_CONFM_KEY 없으면 None(도로명 변환 비활성).

    Returns:
        JusoClient | None: 생성/캐시된 행안부 클라이언트. 키가 없으면 None.
    """
    global _JUSO, _JUSO_INIT
    if not _JUSO_INIT:
        _JUSO = make_juso_client(os.getenv("JUSO_CONFM_KEY"))
        _JUSO_INIT = True
    return _JUSO


def standardize_rows(rows: list) -> list:
    """rows(한국어 컬럼 dict 리스트)를 표준화·검증한 출력 행 리스트로.

    Args:
        rows (list): 한국어 컬럼 dict 행 목록.

    Returns:
        list: process_row로 산출 컬럼이 채워진 출력 행 목록.
    """
    adapter = _get_adapter()
    juso = _get_juso_client()
    return [process_row(row, adapter, juso) for row in rows]
