# -*- coding: utf-8 -*-
"""공식 행정구역 마스터 ↔ Google Geocoding 응답 매핑/판정 로직.

official 행 스키마(dict):
    country (str): "JP" | "TW"
    level (str): JP="pref"|"muni"|"ward", TW="county"|"township"
    code (str): 공식 코드(총무성 団体コード / NLSC 縣市代碼·towncode)
    name (str): 공식 명칭(현지어 원문)
    parent_code (str | None): 상위 레벨 code. 최상위(都道府県/縣市)는 None.
    expected_type (str | None): JP만 채움. 일본 기대 Google 타입
        (administrative_area_level_1/locality/sublocality_level_1/
        administrative_area_level_2). TW는 실측(discovery) 대상이라 None.
"""

import MASTER_261021_normalize as norm

STATUS_MATCH = "MATCH"
STATUS_TYPE_DIFF = "TYPE_DIFF"
STATUS_NAME_DIFF = "NAME_DIFF"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_FOUND = "NOT_FOUND"


def build_query_path(by_code: dict, row: dict) -> str:
    """상위 행정구역을 포함한 전체 경로 쿼리 문자열을 만든다.

    동명 지역(府中市 등)의 오매칭을 막기 위해, parent_code 체인을 최상위까지
    따라가 "상위→하위" 순으로 명칭을 이어붙인다(공백 없음 — 현지 주소 표기 방식).

    Args:
        by_code (dict): {(country, code): row} 조회 테이블.
        row (dict): 경로를 구성할 대상 행.

    Returns:
        str: 전체 경로 쿼리 문자열. 예: "神奈川県横浜市港北区".
    """
    chain = []
    cur = row
    while cur is not None:
        chain.append(cur["name"])
        parent_code = cur.get("parent_code")
        cur = by_code.get((cur["country"], parent_code)) if parent_code else None
    return "".join(reversed(chain))


def _find_matching_component(official_name: str, components: list) -> dict | None:
    """address_components 중 공식 명칭과 같은 이름을 가진 컴포넌트를 찾는다.

    2단계로 찾는다: 먼저 접미사까지 완전히 같은 컴포넌트를 전체에서 찾고, 그게
    없을 때만 접미사 유무를 허용한 완화 비교로 다시 찾는다. 한 번에 섞어서 찾으면
    배열 앞쪽의 약한 일치(예: 콜로키얼 지명 "羅東")가 뒤쪽의 정확한 일치(행정구역
    공식명 "羅東鎮")보다 먼저 뽑혀버리는 문제가 있어 2단계로 분리했다.

    Args:
        official_name (str): 공식 명칭.
        components (list): Geocoding 결과의 address_components.

    Returns:
        dict | None: 일치하는 컴포넌트. 없으면 None.
    """
    target = norm.normalize_name(official_name)
    for comp in components:
        candidates = (comp.get("long_name"), comp.get("short_name"))
        if any(norm.normalize_name(c) == target for c in candidates if c):
            return comp
    for comp in components:
        candidates = (comp.get("long_name"), comp.get("short_name"))
        if any(norm.names_match(official_name, c) for c in candidates):
            return comp
    return None


# Google types는 "political" 같은 범용 태그를 함께 붙이고, 그 위치도 응답마다
# 일정하지 않다(구는 political이 맨 앞, 시/현은 맨 뒤 등). 대표 타입을 고를 때는
# 이 우선순위에서 먼저 찾고, 없으면 political을 제외한 첫 태그를 쓴다.
_TYPE_SPECIFICITY = (
    "street_number", "route", "sublocality_level_2", "sublocality_level_1",
    "sublocality", "locality", "colloquial_area",
    "administrative_area_level_3", "administrative_area_level_2",
    "administrative_area_level_1", "country",
)


def _pick_representative_type(types: list, expected_type: str | None) -> str | None:
    """컴포넌트의 types 배열에서 대표 타입 1개를 고른다.

    기대 타입이 주어졌고 배열에 포함돼 있으면 그걸 그대로 쓴다(가장 의미 있는
    신호). 아니면 `_TYPE_SPECIFICITY` 우선순위로 고르고, 거기도 없으면 political을
    제외한 첫 태그, 그래도 없으면 배열의 첫 태그를 쓴다.

    Args:
        types (list): 컴포넌트의 types 배열.
        expected_type (str | None): 기대 Google type.

    Returns:
        str | None: 대표 타입. types가 비어 있으면 None.
    """
    if not types:
        return None
    if expected_type and expected_type in types:
        return expected_type
    for t in _TYPE_SPECIFICITY:
        if t in types:
            return t
    non_political = [t for t in types if t != "political"]
    return non_political[0] if non_political else types[0]


def classify_result(official_name: str, expected_type: str | None,
                     google_top_result: dict | None) -> dict:
    """공식 행정구역 1건에 대한 Google Geocoding 응답(최상위 결과)을 판정한다.

    Args:
        official_name (str): 공식 명칭(비교 기준).
        expected_type (str | None): 기대 Google type. None이면 타입은
            실측만 기록하고 TYPE_DIFF 판정에는 쓰지 않는다(대만 discovery 모드).
        google_top_result (dict | None): Geocoding API results[0].
            결과가 없으면(ZERO_RESULTS 등) None.

    Returns:
        dict: {status, matched_type, matched_name, place_id, partial_match}.
    """
    if not google_top_result:
        return {"status": STATUS_NOT_FOUND, "matched_type": None,
                "matched_name": None, "place_id": None, "partial_match": False}

    partial = bool(google_top_result.get("partial_match"))
    components = google_top_result.get("address_components", [])
    hit = _find_matching_component(official_name, components)

    if hit is None:
        # 이름이 어떤 컴포넌트와도 일치하지 않음 — 가장 세부적인(0번) 컴포넌트를
        # 참고 정보로 기록하되 NAME_DIFF로 판정.
        fallback = components[0] if components else {}
        return {"status": STATUS_NAME_DIFF,
                "matched_type": _pick_representative_type(fallback.get("types") or [], expected_type),
                "matched_name": fallback.get("long_name"),
                "place_id": google_top_result.get("place_id"),
                "partial_match": partial}

    hit_types = hit.get("types") or []
    matched_type = _pick_representative_type(hit_types, expected_type)
    type_ok = (expected_type is None) or (expected_type in hit_types)
    status = (STATUS_PARTIAL if partial else STATUS_MATCH) if type_ok else STATUS_TYPE_DIFF

    return {"status": status, "matched_type": matched_type,
            "matched_name": hit.get("long_name"),
            "place_id": google_top_result.get("place_id"),
            "partial_match": partial}
