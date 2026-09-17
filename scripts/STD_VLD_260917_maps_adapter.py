# -*- coding: utf-8 -*-
"""Google Maps 서브루틴 어댑터 (G / TS / TSA / RG).

- MapsAdapter: 추상 인터페이스. 반환 dict는 설계 문서의 필드명을 그대로 사용.
- MockMapsAdapter: PLACES 참조 데이터 기반의 결정적 응답. 가상 업체명이라 실제
  Google에는 존재하지 않으므로, Case A/B/C 전체 트리를 오프라인·무비용으로 시연하기
  위한 기본 어댑터. 도로(street) 식별자별로 시나리오를 고정 배정해 RELAXED /
  PROXIMITY_MATCH / PLACEID_MISMATCH / UNVERIFIED_NOT_FOUND / 듀얼주소 MISMATCH 등
  모든 분기를 결정적으로 발생시킨다.
- RealMapsAdapter: 실제 REST 호출(Geocoding + Places API New searchText +
  Reverse Geocoding). 응답 언어는 영문(en).

found 정의(TS/TSA): place_id 존재 AND SIM(업체명_STD, displayName_STD).is_match.
  → 어댑터 내부에서 계산하여 두 구현이 동일 불변식을 보장한다.
"""

import abc
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from html_260908_generate_site_master import PLACES, clean_address  # noqa: E402

import STD_VLD_260917_geo_common as gc  # noqa: E402
from STD_VLD_260917_std_company import SIM, standardize_company  # noqa: E402


# ---------------------------------------------------------------------------
# 추상 인터페이스
# ---------------------------------------------------------------------------
class MapsAdapter(abc.ABC):
    @abc.abstractmethod
    def G(self, query: str) -> dict:
        """Geocoding. query = 업체명+주소 결합 문자열.
        반환: {found, address_std, coord_std, place_id_g, address_components_g}"""

    @abc.abstractmethod
    def TS(self, company: str, center_coord) -> dict:
        """좌표 중심 업체명 TextSearch. 1차 실패 시 반경 완화 1회 재시도.
        반환: {found, relaxed, place_id_t, coord_t, address_components_t}"""

    @abc.abstractmethod
    def TSA(self, company: str, address_text: str) -> dict:
        """좌표 없이 업체명+주소텍스트 TextSearch. 실패 시 주소 레벨 축약 재시도.
        반환: {found, level, place_id_t, address_components_t}"""

    @abc.abstractmethod
    def RG(self, coord) -> dict:
        """Reverse Geocoding. 반환: {address_rg, address_components_rg}"""


def make_adapter(mode: str, *, api_key: str = None) -> MapsAdapter:
    """mode: 'mock' | 'real'."""
    if mode == "real":
        if not api_key:
            raise ValueError(
                "real 모드에는 GOOGLE_MAPS_API_KEY가 필요합니다. "
                ".env 또는 환경변수를 확인하세요."
            )
        return RealMapsAdapter(api_key)
    return MockMapsAdapter()


# ===========================================================================
# Mock 어댑터
# ===========================================================================
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def _has_cjk(s: str) -> bool:
    return any(
        "　" <= c <= "鿿" or "가" <= c <= "힣" or "぀" <= c <= "ヿ"
        for c in s
    )


# 도로 식별자(street index) → 시나리오. 인덱스 0~8에 각 특수 분기를 고정 배정해
# 26개 도로에서 모든 분기가 최소 1회 이상 발생하도록 보장한다(나머지는 direct).
_SCENARIO_BY_MOD = {
    0: "relaxed",
    1: "ts_miss",
    2: "placeid_match",
    3: "proximity",
    4: "mismatch",
    5: "g_fail_coord",
    6: "g_fail_tsa",
    7: "g_fail_rg",
    8: "dual_mismatch",
}

_OFFSET_DEG = 0.0020  # 약 222m. CMP 허용범위(50m) 초과, 도시 내 도로 간격보다 작음.


class MockMapsAdapter(MapsAdapter):
    """PLACES 참조 데이터 기반 결정적 Mock."""

    def __init__(self):
        # 모든 도로를 결정적 순서로 인덱싱
        self._streets = []                # [(place, street, index)]
        self._coord_index = {}            # (lat6, lon6) → index
        for place in PLACES:
            for street in place["streets"]:
                idx = len(self._streets)
                self._streets.append((place, street, idx))
                key = (round(street["lat"], 6), round(street["lon"], 6))
                self._coord_index[key] = idx
        # 도로별 검색 문자열(주소 텍스트 매칭용)
        self._search_terms = []
        for place, street, _ in self._streets:
            terms = [
                street["en"], street["local"],
                f"{street['en']} {place['city_en']}",
                f"{place['city_local']}{street['local']}",
            ]
            self._search_terms.append(terms)

    # ---- 내부 유틸 ----
    def _scenario(self, idx: int) -> str:
        return _SCENARIO_BY_MOD.get(idx % 12, "direct")

    def _resolve_by_text(self, text: str):
        """주소/쿼리 문자열로 가장 잘 맞는 도로를 찾는다. (place, street, idx) 또는 None."""
        from rapidfuzz.fuzz import partial_ratio
        best, best_score = None, 0.0
        for (place, street, idx), terms in zip(self._streets, self._search_terms):
            score = max(partial_ratio(text, t) for t in terms)
            if score > best_score:
                best_score, best = score, (place, street, idx)
        return best if best_score >= 60 else None

    def _resolve_by_coord(self, coord):
        """좌표에서 가장 가까운 도로를 찾는다. (place, street, idx)."""
        best, best_d = None, float("inf")
        for place, street, idx in self._streets:
            d = gc.haversine(coord, (street["lat"], street["lon"]))
            if d < best_d:
                best_d, best = d, (place, street, idx)
        return best

    def _components(self, place, street, source_api):
        """place/street에서 addressComponents 원본(소스 스키마)을 만들어 정규화."""
        region = place["admin"].split(": ")[1]
        if source_api == "geocoding":
            raw = [
                {"types": ["street_number"], "long_name": street["en"].split(" ")[0],
                 "short_name": street["en"].split(" ")[0]},
                {"types": ["route"], "long_name": street["en"], "short_name": street["en"]},
                {"types": ["locality"], "long_name": place["city_en"], "short_name": place["city_en"]},
                {"types": ["administrative_area_level_1"], "long_name": region, "short_name": region},
                {"types": ["country"], "long_name": place["country"].split(": ")[1],
                 "short_name": place["country"].split(":")[0]},
                {"types": ["postal_code"], "long_name": street["postal"], "short_name": street["postal"]},
            ]
        else:  # places_new
            raw = [
                {"types": ["route"], "longText": street["en"], "shortText": street["en"],
                 "languageCode": "en"},
                {"types": ["locality"], "longText": place["city_en"], "shortText": place["city_en"],
                 "languageCode": "en"},
                {"types": ["administrative_area_level_1"], "longText": region, "shortText": region,
                 "languageCode": "en"},
                {"types": ["country"], "longText": place["country"].split(": ")[1],
                 "shortText": place["country"].split(":")[0], "languageCode": "en"},
                {"types": ["postal_code"], "longText": street["postal"], "shortText": street["postal"],
                 "languageCode": "en"},
            ]
        return gc.normalize_address_components(raw, source_api)

    # ---- 서브루틴 ----
    def G(self, query: str) -> dict:
        hit = self._resolve_by_text(query)
        if hit is None:
            return {"found": False, "address_std": None, "coord_std": None,
                    "place_id_g": None, "address_components_g": []}
        place, street, idx = hit
        scenario = self._scenario(idx)

        # 지오코딩 자체가 실패하는 시나리오
        if scenario in ("g_fail_coord", "g_fail_tsa", "g_fail_rg"):
            return {"found": False, "address_std": None, "coord_std": None,
                    "place_id_g": None, "address_components_g": []}

        # 듀얼주소 MISMATCH: 영문 쿼리는 같은 도시의 '다른 도로'로 어긋나게 한다.
        if scenario == "dual_mismatch" and not _has_cjk(query):
            sib = self._sibling_street(place, street)
            if sib is not None:
                place, street = place, sib

        addr_std, _ = clean_address(place, street)
        base = (street["lat"], street["lon"])

        # Case C의 dist>tol 분기를 유도하는 시나리오는 좌표를 오프셋한다.
        if scenario in ("proximity", "mismatch", "placeid_match"):
            coord = (base[0] + _OFFSET_DEG, base[1])
        else:
            coord = base

        return {
            "found": True,
            "address_std": addr_std,
            "coord_std": coord,
            "place_id_g": f"mockG:{_slug(place['city_en'])}:{_slug(street['en'])}",
            "address_components_g": self._components(place, street, "geocoding"),
        }

    def _sibling_street(self, place, street):
        for s in place["streets"]:
            if s is not street:
                return s
        return None

    def TS(self, company: str, center_coord) -> dict:
        place, street, idx = self._resolve_by_coord(center_coord)
        scenario = self._scenario(idx)
        comps = self._components(place, street, "places_new")
        base = (street["lat"], street["lon"])
        std_company = standardize_company(company)

        # 업체 미발견(displayName 유사도 미달) 시나리오
        if scenario == "ts_miss":
            return {"found": False, "relaxed": False, "place_id_t": None,
                    "coord_t": None, "address_components_t": []}

        # 반경 완화 후에야 발견되는 시나리오
        relaxed = scenario == "relaxed"

        addr_std, _ = clean_address(place, street)

        # PROXIMITY: place_id 상이 + 좌표는 G의 오프셋 위치와 근접(≤tol)
        if scenario == "proximity":
            return {"found": True, "relaxed": False,
                    "place_id_t": f"mockT:{_slug(street['en'])}:alt",
                    "coord_t": (base[0] + _OFFSET_DEG, base[1]),
                    "address_std": addr_std, "address_components_t": comps}
        # MISMATCH: place_id 상이 + 좌표는 실제 도로(=기존좌표, G 오프셋과 멂)
        if scenario == "mismatch":
            return {"found": True, "relaxed": False,
                    "place_id_t": f"mockT:{_slug(street['en'])}:other",
                    "coord_t": base, "address_std": addr_std,
                    "address_components_t": comps}
        # PLACEID_MATCH: G와 동일 place_id
        if scenario == "placeid_match":
            return {"found": True, "relaxed": False,
                    "place_id_t": f"mockG:{_slug(place['city_en'])}:{_slug(street['en'])}",
                    "coord_t": base, "address_std": addr_std,
                    "address_components_t": comps}
        # g_fail_coord: G 실패 후 기존좌표 TS로 검증(VERIFIED_COORD_*)
        # 그 외(direct/relaxed/g_fail_tsa/g_fail_rg/dual_mismatch): 정상 발견
        if scenario == "g_fail_tsa" or scenario == "g_fail_rg":
            # 이 시나리오들은 기존좌표 TS도 실패해야 TSA/RG 단계로 내려간다.
            return {"found": False, "relaxed": False, "place_id_t": None,
                    "coord_t": None, "address_std": None, "address_components_t": []}

        # displayName은 표준 업체명을 그대로 반영(SIM ≈ 1.0 → found)
        display_name = std_company
        _, is_match = SIM(std_company, display_name)
        found = is_match  # place_id는 아래에서 항상 존재
        return {
            "found": found,
            "relaxed": relaxed,
            "place_id_t": f"mockT:{_slug(place['city_en'])}:{_slug(street['en'])}",
            "coord_t": base,
            "address_std": addr_std,
            "address_components_t": comps,
        }

    def TSA(self, company: str, address_text: str) -> dict:
        # 주소 레벨을 축약해가며(L1→L3) 재시도
        for level in (1, 2, 3):
            reduced = gc.reduce_address(address_text, level)
            hit = self._resolve_by_text(reduced) or self._resolve_by_text(address_text)
            if hit is None:
                continue
            place, street, idx = hit
            scenario = self._scenario(idx)
            if scenario == "g_fail_tsa":
                addr_std, _ = clean_address(place, street)
                return {"found": True, "level": level,
                        "place_id_t": f"mockTSA:{_slug(street['en'])}",
                        "address_std": addr_std,
                        "address_components_t": self._components(place, street, "places_new")}
            # g_fail_rg 및 기타: TSA도 실패로 처리(RG 단계로 유도)
            return {"found": False, "level": level, "place_id_t": None,
                    "address_std": None, "address_components_t": []}
        return {"found": False, "level": 3, "place_id_t": None,
                "address_std": None, "address_components_t": []}

    def RG(self, coord) -> dict:
        place, street, _ = self._resolve_by_coord(coord)
        addr_std, _ = clean_address(place, street)
        return {"address_rg": addr_std,
                "address_components_rg": self._components(place, street, "geocoding")}


# ===========================================================================
# Real 어댑터 (실제 REST 호출)
# ===========================================================================
class RealMapsAdapter(MapsAdapter):
    """실제 Google Maps Platform 호출. 응답 언어는 영문(en)."""

    GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

    def __init__(self, api_key: str, session=None):
        import requests
        self.api_key = api_key
        self.session = session or requests.Session()

    # ---- Geocoding (G, RG 공용) ----
    def _geocode(self, params):
        p = {"key": self.api_key, "language": "en", **params}
        resp = self.session.get(self.GEOCODE_URL, params=p, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def G(self, query: str) -> dict:
        data = self._geocode({"address": query})
        results = data.get("results", [])
        if not results:
            return {"found": False, "address_std": None, "coord_std": None,
                    "place_id_g": None, "address_components_g": []}
        top = results[0]
        loc = top["geometry"]["location"]
        return {
            "found": True,
            "address_std": top.get("formatted_address"),
            "coord_std": (loc["lat"], loc["lng"]),
            "place_id_g": top.get("place_id"),
            "address_components_g": gc.normalize_address_components(
                top.get("address_components", []), "geocoding"),
        }

    def RG(self, coord) -> dict:
        data = self._geocode({"latlng": f"{coord[0]},{coord[1]}"})
        results = data.get("results", [])
        if not results:
            return {"address_rg": None, "address_components_rg": []}
        top = results[0]
        return {
            "address_rg": top.get("formatted_address"),
            "address_components_rg": gc.normalize_address_components(
                top.get("address_components", []), "geocoding"),
        }

    # ---- Places API (New) TextSearch ----
    def _search_text(self, text_query, *, location_bias=None):
        import requests
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.addressComponents"
            ),
        }
        body = {"textQuery": text_query, "languageCode": "en"}
        if location_bias:
            body["locationBias"] = location_bias
        resp = self.session.post(self.TEXTSEARCH_URL, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        return resp.json().get("places", [])

    def _first_match(self, places, company):
        """place_id 존재 AND SIM(업체명, displayName) 판정으로 found 결정."""
        std_company = standardize_company(company)
        for pl in places:
            name = (pl.get("displayName") or {}).get("text", "")
            _, is_match = SIM(std_company, name)
            if pl.get("id") and is_match:
                loc = pl.get("location", {})
                return {
                    "place_id_t": pl["id"],
                    "coord_t": (loc.get("latitude"), loc.get("longitude")),
                    "address_std": pl.get("formattedAddress"),
                    "address_components_t": gc.normalize_address_components(
                        pl.get("addressComponents", []), "places_new"),
                }
        return None

    def TS(self, company: str, center_coord) -> dict:
        def _bias(radius):
            return {"circle": {"center": {"latitude": center_coord[0],
                                          "longitude": center_coord[1]},
                               "radius": radius}}
        # 1차: 좁은 반경
        places = self._search_text(company, location_bias=_bias(2000.0))
        m = self._first_match(places, company)
        if m:
            return {"found": True, "relaxed": False, **m}
        # 2차: 반경 완화 재시도
        places = self._search_text(company, location_bias=_bias(20000.0))
        m = self._first_match(places, company)
        if m:
            return {"found": True, "relaxed": True, **m}
        return {"found": False, "relaxed": True, "place_id_t": None,
                "coord_t": None, "address_std": None, "address_components_t": []}

    def TSA(self, company: str, address_text: str) -> dict:
        for level in (1, 2, 3):
            reduced = gc.reduce_address(address_text, level)
            places = self._search_text(f"{company} {reduced}")
            m = self._first_match(places, company)
            if m:
                return {"found": True, "level": level,
                        "place_id_t": m["place_id_t"],
                        "address_std": m.get("address_std"),
                        "address_components_t": m["address_components_t"]}
        return {"found": False, "level": 3, "place_id_t": None,
                "address_std": None, "address_components_t": []}
