# -*- coding: utf-8 -*-
"""중복 식별 서비스 (dedup 얇은 래핑 + 임계치 오버라이드).

코어(SIM_260926_dedup, std_company)는 임계값을 모듈 전역 상수로 참조하므로,
요청 파라미터가 오면 실행 동안만 상수를 임시 오버라이드하고 원복한다.
코어 코드 자체는 수정하지 않는다.
"""

import contextlib

import deps  # noqa: F401

import SIM_260926_dedup as dd
import STD_VLD_260917_std_company as stdc


@contextlib.contextmanager
def _override(thresholds: dict | None):
    """임계치 임시 오버라이드. 없으면 그대로.

    코어 모듈의 전역 상수를 실행 동안만 바꾸고 finally에서 원복한다.

    Args:
        thresholds (dict | None): name_threshold/addr_jaccard/coord_m/
            code_max_edits 키를 가질 수 있는 dict. None이면 오버라이드 없음.

    Yields:
        None: with 블록 실행용.
    """
    if not thresholds:
        yield
        return
    saved = {}
    mapping = {
        "name_threshold": (stdc, "SIM_THRESHOLD"),
        "addr_jaccard": (dd, "ADDR_LOWER_JACCARD"),
        "coord_m": (dd, "COORD_EQUAL_M"),
        "code_max_edits": (dd, "CODE_SIMILAR_MAX_EDITS"),
    }
    try:
        for key, (mod, attr) in mapping.items():
            if thresholds.get(key) is not None:
                saved[(mod, attr)] = getattr(mod, attr)
                setattr(mod, attr, thresholds[key])
        yield
    finally:
        for (mod, attr), val in saved.items():
            setattr(mod, attr, val)


def run_dedup(rows: list, thresholds: dict | None = None) -> dict:
    """제출된 rows(한국어 컬럼 dict) 기준으로 중복 식별.

    반환 인덱스는 제출 rows의 순서를 그대로 가리킨다(프론트가 매핑).

    Args:
        rows (list): 한국어 컬럼 dict 행 목록.
        thresholds (dict | None, optional): 임시 오버라이드할 임계치. 기본 None.

    Returns:
        dict: 코어 dedup 결과(클러스터, 의심 엣지 등).
    """
    with _override(thresholds):
        internal = dd._to_rows(rows)
        result = dd.dedup(internal)
    return result
