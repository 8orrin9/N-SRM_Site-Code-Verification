# -*- coding: utf-8 -*-
"""행안부(Juso) 도로명주소 검색 API 클라이언트.

Google Geocoding은 입력 체계(지번/도로명)에 따라 formatted_address가 갈리므로,
한국 주소를 도로명으로 강제 통일하기 위한 후처리 모듈이다. Juso 검색 API는 지번/
도로명 어느 keyword로 검색하든 응답의 roadAddr(전체 도로명주소)를 반환한다.

코어 로직(STD_VLD_260917_*)과 분리된 얇은 후처리 레이어로, real 어댑터의
requests.Session/timeout 관례를 따른다.
"""

import requests

ADDR_LINK_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


class JusoClient:
    """행안부 도로명주소 검색 API 클라이언트."""

    def __init__(self, confm_key: str, session=None):
        self.confm_key = confm_key
        self.session = session or requests.Session()

    def resolve(self, keyword: str) -> dict:
        """keyword(한글 주소)로 도로명주소를 조회. 매칭 성공 시 dict, 실패/오류 시 None.

        반환: {road_addr, jibun_addr, zip_no, eng_addr}
        네트워크·파싱 예외는 None으로 흡수해 호출부가 기존 결과로 폴백하도록 한다.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return None
        params = {
            "confmKey": self.confm_key,
            "keyword": keyword,
            "currentPage": 1,
            "countPerPage": 1,
            "resultType": "json",
        }
        try:
            resp = self.session.get(ADDR_LINK_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return None

        results = data.get("results", {})
        common = results.get("common", {})
        if common.get("errorCode") != "0":
            return None
        juso = results.get("juso") or []
        if not juso:
            return None
        top = juso[0]
        return {
            "road_addr": top.get("roadAddr", ""),
            "jibun_addr": top.get("jibunAddr", ""),
            "zip_no": top.get("zipNo", ""),
            "eng_addr": top.get("engAddr", ""),
        }


def make_juso_client(confm_key: str):
    """confmKey가 있으면 JusoClient, 없으면 None(도로명 변환 비활성)."""
    if not confm_key:
        return None
    return JusoClient(confm_key)
