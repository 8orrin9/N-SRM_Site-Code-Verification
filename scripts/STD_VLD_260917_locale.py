# -*- coding: utf-8 -*-
"""국가코드 → 현지어 languageCode 매핑 로더.

config/country_lang.yaml을 1회 읽어 캐시한다. "국가/지역" 컬럼 값("CN:중국")에서
현지어 검색 언어코드를 조회하며, 매핑에 없으면 None(현지어 재검색 생략)을 반환한다.
"""

import os

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_YAML_PATH = os.path.join(_ROOT, "config", "country_lang.yaml")

_MAP = None


def _load():
    """country_lang.yaml을 1회 읽어 캐시한다.

    Returns:
        dict: ISO 국가코드 → languageCode 매핑. 파일이 비면 빈 dict.
    """
    global _MAP
    if _MAP is None:
        with open(_YAML_PATH, encoding="utf-8") as f:
            _MAP = yaml.safe_load(f) or {}
    return _MAP


def lang_for_country(country_field):
    """'CN:중국' 같은 국가/지역 값에서 현지어 languageCode를 조회. 없으면 None.

    콜론 앞의 ISO 국가코드로 조회한다. 빈 값·미매핑이면 None(재검색 생략).

    Args:
        country_field (str): "CN:중국" 형식의 국가/지역 값.

    Returns:
        str | None: 현지어 languageCode(BCP-47). 빈 값·미매핑이면 None.
    """
    if not country_field:
        return None
    code = str(country_field).split(":", 1)[0].strip().upper()
    return _load().get(code)
