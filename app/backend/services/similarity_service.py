# -*- coding: utf-8 -*-
"""유사 검색 서비스 (find_similar 래핑)."""

import deps  # noqa: F401

from find_similar import find_similar


def search(query_rows: list, reference_rows: list, top_k: int = 8) -> list:
    """각 쿼리행의 결과 리스트 반환.

    [{query_index, matches:[{ref_index, ref_row, nameSim,...,avg}]}]
    """
    results = []
    for qi, q in enumerate(query_rows):
        matches = find_similar(q, reference_rows, top_k=top_k)
        results.append({"query_index": qi, "matches": matches})
    return results
