# -*- coding: utf-8 -*-
"""유사 검색 서비스 (find_similar 래핑 + 가중치 오버라이드).

업체명 상이 판단 임계(name_diff_threshold)는 `score_pair`가 아니라 `SIM()`이
참조하는 STD_VLD_260917_std_company.SIM_THRESHOLD 전역 상수에서 결정된다.
dedup_service._override와 동일한 방식으로, 실행 동안만 임시로 바꾸고 원복한다.
코어 코드 자체는 수정하지 않는다.
"""

import contextlib

import deps  # noqa: F401

import STD_VLD_260917_std_company as stdc
from find_similar import find_similar


@contextlib.contextmanager
def _override_name_threshold(weights: dict | None):
    """weights에 name_diff_threshold가 있으면 SIM_THRESHOLD를 임시 오버라이드.

    Args:
        weights (dict | None): find_similar에 전달할 가중치 오버라이드.
            name_diff_threshold 키가 있으면 사용, 없으면 오버라이드 없음.

    Yields:
        None: with 블록 실행용.
    """
    value = (weights or {}).get("name_diff_threshold")
    if value is None:
        yield
        return
    saved = stdc.SIM_THRESHOLD
    stdc.SIM_THRESHOLD = value
    try:
        yield
    finally:
        stdc.SIM_THRESHOLD = saved


def search(query_rows: list, reference_rows: list, top_k: int = 8,
           weights: dict | None = None) -> list:
    """각 쿼리행의 결과 리스트 반환.

    [{query_index, matches:[{ref_index, ref_row, nameSim,...,avg}]}]

    Args:
        query_rows (list): 유사 검색 대상 쿼리 행 목록.
        reference_rows (list): 비교 기준 행 목록.
        top_k (int, optional): 쿼리당 반환할 상위 후보 수. 기본 8.
        weights (dict | None, optional): UI에서 조절한 가중치 오버라이드.
            `find_similar.score_pair`가 받는 형식과 동일. 기본 None.

    Returns:
        list: 쿼리별 {query_index, matches} dict 목록.
    """
    with _override_name_threshold(weights):
        results = []
        for qi, q in enumerate(query_rows):
            matches = find_similar(q, reference_rows, top_k=top_k, weights=weights)
            results.append({"query_index": qi, "matches": matches})
    return results
