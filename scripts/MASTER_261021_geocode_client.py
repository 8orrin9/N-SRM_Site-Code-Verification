# -*- coding: utf-8 -*-
"""Google Geocoding API 호출기: 캐시 + QPS 제한 + 지수 백오프 + dry-run.

쿼리 1건 = (query 문자열, language, components 국가필터) 조합. 캐시 키는 이
조합의 해시이며, 캐시 파일이 있으면 재호출하지 않는다(멱등성·재실행 비용 0).
dry_run=True면 캐시 미스 시에도 실제 호출을 하지 않고 예상 호출 정보만 반환한다
(비기능 요건: 실행 전 예상 호출 수 확인용).
"""

import hashlib
import json
import os
import time

import requests

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# OVER_QUERY_LIMIT/UNKNOWN_ERROR는 일시적일 수 있어 지수 백오프 후 재시도.
# ZERO_RESULTS/REQUEST_DENIED/INVALID_REQUEST 등은 재시도 대상이 아닌 결과로 취급.
RETRYABLE_STATUSES = frozenset(["OVER_QUERY_LIMIT", "UNKNOWN_ERROR"])

# 캐시에 영구 저장해도 되는 "안정적인" 상태. OK/ZERO_RESULTS는 실제 지리 사실이라
# 재조회해도 바뀌지 않는다. 그 외(키 오류·요청 오류·재시도 끝난 일시 오류)는 캐시하지
# 않아야 다음 재실행에서 다시 시도할 수 있다(영구 오류 고착 방지).
CACHEABLE_STATUSES = frozenset(["OK", "ZERO_RESULTS"])


def cache_key(query: str, language: str, region_country: str) -> str:
    """쿼리 조합 → 캐시 파일명(해시, 확장자 없음).

    Args:
        query (str): 지오코딩 쿼리 문자열.
        language (str): 응답 언어(ja/zh-TW/en 등).
        region_country (str): components country 필터(JP/TW).

    Returns:
        str: sha1 해시 기반 캐시 키.
    """
    raw = f"{region_country}|{language}|{query}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class GeocodeClient:
    """캐시·QPS 제한·백오프를 갖춘 Geocoding 호출기."""

    def __init__(self, api_key: str, cache_dir: str, *, qps: float = 5.0,
                 max_retries: int = 5, session=None):
        """
        Args:
            api_key (str): Google Maps API 키.
            cache_dir (str): 응답 원문 JSON 캐시 디렉터리(없으면 생성).
            qps (float, optional): 초당 최대 호출 수. 기본 5.0.
            max_retries (int, optional): RETRYABLE_STATUSES에서의 최대 재시도. 기본 5.
            session (requests.Session, optional): 재사용할 세션. 없으면 새로 생성.
        """
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.qps = qps
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._last_call_ts = 0.0
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _throttle(self):
        """QPS 제한: 마지막 호출과의 간격이 1/qps보다 짧으면 그만큼 대기."""
        if self.qps <= 0:
            return
        min_interval = 1.0 / self.qps
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def plan(self, query: str, language: str, region_country: str) -> dict:
        """실제 호출 없이, 캐시 히트 여부만 확인한다(dry-run 집계용).

        Args:
            query (str): 지오코딩 쿼리 문자열.
            language (str): 응답 언어.
            region_country (str): components country 필터.

        Returns:
            dict: {cache_key, cached(bool)}.
        """
        key = cache_key(query, language, region_country)
        return {"cache_key": key, "cached": os.path.exists(self._cache_path(key))}

    def geocode(self, query: str, *, language: str, region_country: str,
                dry_run: bool = False) -> dict:
        """캐시 확인 → (dry_run이면 미스 시 스킵) → 실제 호출(백오프 포함) → 캐시 저장.

        Args:
            query (str): 지오코딩 쿼리 문자열(상위 행정구역 포함 전체 경로).
            language (str): 응답 언어.
            region_country (str): components country:XX 필터용 국가 코드.
            dry_run (bool, optional): True면 캐시 미스 시 실제 호출 없이
                `{"_dry_run": True, "_cache_key": ...}`만 반환.

        Returns:
            dict: Geocoding API JSON 응답(캐시 히트 시 캐시된 원문 그대로).
        """
        key = cache_key(query, language, region_country)
        path = self._cache_path(key)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        if dry_run:
            return {"_dry_run": True, "_cache_key": key, "_query": query}

        params = {
            "key": self.api_key,
            "address": query,
            "components": f"country:{region_country}",
            "language": language,
        }
        data = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = self.session.get(GEOCODE_URL, params=params, timeout=15)
            self._last_call_ts = time.monotonic()
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status in RETRYABLE_STATUSES and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            break

        if data.get("status") in CACHEABLE_STATUSES:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return data
