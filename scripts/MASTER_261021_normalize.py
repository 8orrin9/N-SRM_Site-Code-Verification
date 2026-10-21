# -*- coding: utf-8 -*-
"""일본·대만 행정구역명 비교용 정규화 유틸.

공식 목록(총무성/NLSC)과 Google Geocoding 응답의 명칭이 이체자·전각/반각·
접미사 유무로 갈리는 경우를 흡수해 "같은 이름"으로 판정하기 위한 순수 함수들.
"""

import re
import unicodedata

# 이체자 통일(한쪽 표기로 모아서 비교). 어느 쪽도 쓰지 않는 글자면 no-op이라
# 일본/대만 혼용 테이블을 하나로 둬도 안전하다.
_VARIANT_MAP = {
    "臺": "台",  # 대만 번체 이체자(臺北 ↔ 台北)
    "區": "区",  # 구자체(區) ↔ 신자체(区)
    "惠": "恵",  # 구자체(惠) ↔ 신자체(恵) — 福岡県 須恵町/須惠町에서 실제로 발견됨
}

# 비교 시 접미사 유무 차이를 허용하기 위해 제거 대상으로 보는 1글자 접미사.
_ADMIN_SUFFIXES = ("都", "道", "府", "県", "市", "区", "鄉", "鎮", "村", "町")


def unify_variants(s: str) -> str:
    """이체자를 한쪽 표기로 통일한다.

    Args:
        s (str): 원문.

    Returns:
        str: 이체자 통일된 문자열.
    """
    for src, dst in _VARIANT_MAP.items():
        s = s.replace(src, dst)
    return s


def normalize_name(s: str) -> str:
    """비교용 정규화: NFKC(전각/반각 통일) + 이체자 통일 + 공백 제거.

    Args:
        s (str | None): 원문 명칭.

    Returns:
        str: 비교용 정규화 문자열. 입력이 없으면 빈 문자열.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = unify_variants(s)
    return re.sub(r"\s+", "", s)


def strip_admin_suffix(s: str) -> str:
    """정규화된 문자열 끝의 행정구역 접미사 1글자를 제거한다(있으면).

    Args:
        s (str): `normalize_name`을 통과한 문자열.

    Returns:
        str: 접미사를 제거한 핵심 명칭. 접미사가 없으면 원문 그대로.
    """
    if s and s[-1] in _ADMIN_SUFFIXES:
        return s[:-1]
    return s


def names_match(a: str, b: str) -> bool:
    """정규화 후 전체 일치하거나, 접미사 제거 후 일치하면 같은 이름으로 본다.

    Args:
        a (str | None): 비교 대상 1.
        b (str | None): 비교 대상 2.

    Returns:
        bool: 같은 이름으로 판단되면 True.
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return strip_admin_suffix(na) == strip_admin_suffix(nb)
