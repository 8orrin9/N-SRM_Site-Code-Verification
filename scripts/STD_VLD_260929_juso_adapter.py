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
        """클라이언트를 초기화한다.

        Args:
            confm_key (str): 행안부 발급 승인키(confmKey).
            session (requests.Session, optional): 재사용할 세션. 없으면 새로 생성.
        """
        self.confm_key = confm_key
        self.session = session or requests.Session()

    def resolve(self, keyword: str) -> dict:
        """keyword(한글 주소)로 도로명주소를 조회. 매칭 성공 시 dict, 실패/오류 시 None.

        반환: {road_addr, jibun_addr, zip_no, eng_addr}
        네트워크·파싱 예외는 None으로 흡수해 호출부가 기존 결과로 폴백하도록 한다.

        Args:
            keyword (str): 검색할 한글 주소(지번/도로명 무관).

        Returns:
            dict | None: 최상위 후보 1건. 매칭 실패·오류 시 None.
        """
        cands = self.resolve_candidates(keyword, count=1)
        return cands[0] if cands else None

    def resolve_candidates(self, keyword: str, count: int = 10) -> list:
        """keyword로 도로명주소 후보 목록을 조회(최대 count건).

        시/도·시군구 명칭이 다른 동명이동을 호출부가 교차검증으로 거를 수 있도록
        후보마다 si_nm(시도)·sgg_nm(시군구)을 함께 담는다. 실패/오류 시 빈 리스트.

        Args:
            keyword (str): 검색할 한글 주소.
            count (int, optional): 최대 후보 수. 기본 10.

        Returns:
            list: {road_addr, jibun_addr, zip_no, eng_addr, si_nm, sgg_nm} 리스트.
                빈 keyword·실패·오류 시 빈 리스트.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        params = {
            "confmKey": self.confm_key,
            "keyword": keyword,
            "currentPage": 1,
            "countPerPage": count,
            "resultType": "json",
        }
        try:
            resp = self.session.get(ADDR_LINK_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []

        results = data.get("results", {})
        if results.get("common", {}).get("errorCode") != "0":
            return []
        out = []
        for j in results.get("juso") or []:
            out.append({
                "road_addr": j.get("roadAddr", ""),
                "jibun_addr": j.get("jibunAddr", ""),
                "zip_no": j.get("zipNo", ""),
                "eng_addr": j.get("engAddr", ""),
                "si_nm": j.get("siNm", ""),
                "sgg_nm": j.get("sggNm", ""),
            })
        return out


def make_juso_client(confm_key: str):
    """confmKey가 있으면 JusoClient, 없으면 None(도로명 변환 비활성).

    Args:
        confm_key (str): 행안부 승인키. 빈 값이면 비활성.

    Returns:
        JusoClient | None: 승인키가 있으면 클라이언트, 없으면 None.
    """
    if not confm_key:
        return None
    return JusoClient(confm_key)
