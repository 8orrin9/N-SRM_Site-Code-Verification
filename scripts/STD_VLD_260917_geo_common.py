# -*- coding: utf-8 -*-
"""주소/실재검증 공통 프리미티브.

- haversine: 두 좌표 간 거리(m).
- CMP: 두 후보(place_id, 좌표) 동일 업체 여부 판정(설계 문서 1장).
- normalize_address_components: Geocoding/Places 응답 스키마를 공통 스키마로 통일(1-3장).
- reduce_address: TSA용 주소 축약. 주소 문자열만 참조(위치 마스터 리스트와 매칭).
- 분류 코드 상수 및 status_for_code: 코드→표준화 3단계 매핑(5장).
- VerifyResult: 레코드별 판정 결과 컨테이너(6장 산출물).
"""

import math
import re
from dataclasses import dataclass, field

CMP_TOLERANCE_M = 50.0  # place_id 상이 시 동일 부지로 보는 허용 거리(m)

# ---------------------------------------------------------------------------
# 분류 코드(설계 문서 5장). 문자열 상수로 관리(필터링/집계용).
# ---------------------------------------------------------------------------
VERIFIED_GEOCODE_DIRECT = "VERIFIED_GEOCODE_DIRECT"
VERIFIED_GEOCODE_RELAXED = "VERIFIED_GEOCODE_RELAXED"
VERIFIED_GEOCODE_PROXIMITY = "VERIFIED_GEOCODE_PROXIMITY"  # 정밀 지오코딩 좌표에 근접한 유일 POI(업체명 유사도 미달이나 좌표로 실재 확인)
VERIFIED_COORD_DIRECT = "VERIFIED_COORD_DIRECT"
VERIFIED_COORD_RELAXED = "VERIFIED_COORD_RELAXED"
VERIFIED_TEXTSEARCH_ADDR_TEXT = "VERIFIED_TEXTSEARCH_ADDR_TEXT"
VERIFIED_PLACEID_MATCH = "VERIFIED_PLACEID_MATCH"
VERIFIED_PROXIMITY_MATCH = "VERIFIED_PROXIMITY_MATCH"
VERIFIED_ADDRESS_SOURCE_RESOLVED = "VERIFIED_ADDRESS_SOURCE_RESOLVED"
UNVERIFIED_NOT_FOUND = "UNVERIFIED_NOT_FOUND"
UNVERIFIED_PLACEID_MISMATCH = "UNVERIFIED_PLACEID_MISMATCH"
UNVERIFIED_REVERSE_GEOCODE_ONLY = "UNVERIFIED_REVERSE_GEOCODE_ONLY"
UNVERIFIED_ADDRESS_SOURCE_CONFLICT = "UNVERIFIED_ADDRESS_SOURCE_CONFLICT"
FAILED_ALL_METHODS = "FAILED_ALL_METHODS"

# 표준화 3단계
STATUS_VERIFIED = "검증 완료"
STATUS_UNVERIFIED = "확인 필요"
STATUS_FAILED = "실패"


def status_for_code(code: str) -> str:
    """분류 코드 접두어로 표준화 상태를 결정한다.

    Args:
        code (str): 분류 코드(VERIFIED_*/UNVERIFIED_*/FAILED_*).

    Returns:
        str: 표준화 3단계 상태(STATUS_VERIFIED/UNVERIFIED/FAILED).
    """
    if code.startswith("VERIFIED_"):
        return STATUS_VERIFIED
    if code.startswith("UNVERIFIED_"):
        return STATUS_UNVERIFIED
    return STATUS_FAILED


# ---------------------------------------------------------------------------
# 위치 마스터 리스트 (reduce_address 전용).
#   실제로는 admin/country 마스터 데이터가 존재한다고 가정하며, 여기서는 임의로 구성.
#   TSA는 admin/country '컬럼'을 참조하지 않고 주소 문자열에서만 위치를 추출한다.
# ---------------------------------------------------------------------------
COUNTRY_NAMES = [
    "South Korea", "Korea", "한국", "대한민국",
    "China", "中国", "中國", "중국",
    "Japan", "日本", "일본",
    "USA", "United States", "US", "미국",
    "Switzerland", "스위스",
    "Germany", "Deutschland", "독일",
]

ADMIN_NAMES = [
    # 영문 행정구역
    "Seoul", "Gyeonggi-do", "Gyeonggi", "Busan",
    "Shanghai", "Jiangsu", "Guangdong",
    "Tokyo", "Osaka", "Aichi",
    "California", "Illinois", "St. Gallen", "Bavaria",
    # 현지어 행정구역
    "서울", "경기", "부산", "上海", "江苏省", "江苏", "广东省", "广东",
    "東京都", "東京", "大阪府", "大阪", "愛知県", "愛知",
]

CITY_NAMES = [
    "Seoul", "Suwon", "Busan", "Shanghai", "Suzhou", "Shenzhen",
    "Tokyo", "Osaka", "Nagoya", "St. Gallen", "Mountain View",
    "Cupertino", "Chicago", "Munich", "München",
    "서울특별시", "수원시", "부산광역시", "上海市", "苏州市", "深圳市",
    "名古屋市",
]

# 우편번호 패턴(한/중/미 5~6자리, 일 3-4자리)
_POSTAL_RE = re.compile(r"\b\d{3}-?\d{4}\b|\b\d{5,6}\b")
# 도로 상세(선두 번지/호수) — L1에서 축소 대상
_MULTISPACE_RE = re.compile(r"\s{2,}")


def _find_matches(text: str, candidates):
    """text 안에 등장하는 마스터 후보를 원문 순서대로(중복 제거) 반환.

    Args:
        text (str): 검색 대상 주소 문자열.
        candidates (list): 매칭을 시도할 마스터 후보 목록.

    Returns:
        list: text에 포함된 후보들(후보 목록 순서, 중복 제거).
    """
    found = []
    for c in candidates:
        if c and c in text and c not in found:
            found.append(c)
    return found


def reduce_address(address_text: str, level: int) -> str:
    """TSA용 주소 축약. 주소 문자열만 참조한다(admin/country 컬럼 미사용).

    level 0: 원문 그대로
          1: 우편번호 제거 + 중복 공백/문장부호 정리(경미한 정제)
          2: 주소에서 매칭된 '도시/행정구역' 위치만 (대략적 위치)
          3: 주소에서 매칭된 '국가'만 (광역 폴백)
    매칭이 없으면 상위 레벨은 원문 tail로 폴백한다.

    Args:
        address_text (str): 축약할 원본 주소 문자열.
        level (int): 축약 단계(0~3). 클수록 더 광역으로 축소.

    Returns:
        str: 지정 레벨로 축약된 주소 문자열.
    """
    text = (address_text or "").strip()
    if level <= 0:
        return text

    if level == 1:
        s = _POSTAL_RE.sub(" ", text)
        s = s.replace(" ,", ",")
        s = _MULTISPACE_RE.sub(" ", s)
        return s.strip(" ,")

    if level == 2:
        parts = _find_matches(text, CITY_NAMES) + _find_matches(text, ADMIN_NAMES)
        # 중복 제거(순서 보존)
        seen, uniq = set(), []
        for p in parts:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        if uniq:
            return ", ".join(uniq)
        return reduce_address(text, 1)

    # level >= 3
    countries = _find_matches(text, COUNTRY_NAMES)
    if countries:
        return countries[0]
    admins = _find_matches(text, ADMIN_NAMES)
    if admins:
        return admins[-1]
    return reduce_address(text, 2)


# ---------------------------------------------------------------------------
# 거리 / 비교
# ---------------------------------------------------------------------------
def haversine(c1, c2) -> float:
    """두 (lat, lon) 사이 거리(m). Haversine 공식.

    Args:
        c1 (tuple): 좌표 1 (lat, lon).
        c2 (tuple): 좌표 2 (lat, lon).

    Returns:
        float: 두 좌표 사이 거리(미터).
    """
    lat1, lon1 = c1
    lat2, lon2 = c2
    r = 6371000.0  # 지구 반지름(m)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def CMP(id_1, id_2, coord_1, coord_2, tol_m: float = CMP_TOLERANCE_M) -> str:
    """설계 문서 1장. 두 후보가 동일 업체인지 판정.

    place_id가 같으면 MATCH, 다르더라도 좌표가 tol_m 이내면 PROXIMITY_MATCH,
    그 외는 MISMATCH.

    Args:
        id_1 (str | None): 후보 1 place_id.
        id_2 (str | None): 후보 2 place_id.
        coord_1 (tuple | None): 후보 1 좌표 (lat, lon).
        coord_2 (tuple | None): 후보 2 좌표 (lat, lon).
        tol_m (float, optional): 근접 허용 거리(m). 기본 CMP_TOLERANCE_M.

    Returns:
        str: "MATCH" | "PROXIMITY_MATCH" | "MISMATCH".
    """
    if id_1 and id_2 and id_1 == id_2:
        return "MATCH"
    if coord_1 and coord_2 and haversine(coord_1, coord_2) <= tol_m:
        return "PROXIMITY_MATCH"
    return "MISMATCH"


# ---------------------------------------------------------------------------
# addressComponents 스키마 정규화(설계 문서 1-3장)
# ---------------------------------------------------------------------------
def normalize_address_components(raw, source_api: str):
    """Geocoding / Places(New) addressComponents를 공통 스키마로 통일.

    source_api: "geocoding" (types/long_name/short_name)
              | "places_new" (types/longText/shortText/languageCode)

    Args:
        raw (list): API가 반환한 원본 addressComponents.
        source_api (str): 원본 API 종류("geocoding" | "places_new").

    Returns:
        list: [{types, long_text, short_text, language_code, source_api}, ...].
    """
    out = []
    for comp in raw or []:
        if source_api == "geocoding":
            out.append({
                "types": comp.get("types", []),
                "long_text": comp.get("long_name", ""),
                "short_text": comp.get("short_name", ""),
                "language_code": comp.get("language_code"),  # 요청 언어로 대체됨
                "source_api": "geocoding",
            })
        else:  # places_new
            out.append({
                "types": comp.get("types", []),
                "long_text": comp.get("longText", ""),
                "short_text": comp.get("shortText", ""),
                "language_code": comp.get("languageCode"),
                "source_api": "places_new",
            })
    return out


# ---------------------------------------------------------------------------
# 주소 상세 레벨 판정 (참조 URL 선택용)
# ---------------------------------------------------------------------------
# 동(sublocality) 이하 상세 레벨. 표준주소에 이 중 하나라도 있으면 "충분히 상세"로 본다.
_DETAIL_ADDRESS_LEVELS = frozenset(["sublocality", "route", "street_number"])


def has_detail_below_locality(components) -> bool:
    """addressComponents에 동/도로/번지(sublocality 이하) 상세가 하나라도 있는지.

    실재검증 실패로 표준주소가 도시/행정구역 레벨까지만 뭉개진 경우(False), 사용자
    검토용 URL은 상세 주소를 담은 원본 주소로 검색하는 편이 더 유용하다(참조 URL 선택).

    Args:
        components (list): 정규화된 addressComponents.

    Returns:
        bool: sublocality/route/street_number 중 하나라도 있으면 True.
    """
    for comp in components or []:
        if _DETAIL_ADDRESS_LEVELS & set(comp.get("types", [])):
            return True
    return False


# ---------------------------------------------------------------------------
# 레코드별 판정 결과(설계 문서 6장 산출물)
# ---------------------------------------------------------------------------
@dataclass
class VerifyResult:
    status: str                          # 표준화: 검증 완료 / 확인 필요 / 실패
    code: str                            # 분류 코드
    note: str = ""                       # 비고(사람이 읽는 근거)
    std_address: str = None              # 표준 주소
    std_lat: float = None                # 표준 위도
    std_lon: float = None                # 표준 경도
    place_id: str = None                 # 최종 채택 place_id
    reference_url: str = None            # 참조 URL
    address_components: list = field(default_factory=list)  # 채택된 정규화 컴포넌트
    method_trace: list = field(default_factory=list)        # 거친 단계(디버그)


def make_result(code: str, **kwargs) -> VerifyResult:
    """분류 코드로부터 status를 자동 설정해 VerifyResult 생성.

    Args:
        code (str): 분류 코드.
        **kwargs: VerifyResult의 나머지 필드(note, std_address 등).

    Returns:
        VerifyResult: status가 코드에 맞게 설정된 결과 객체.
    """
    return VerifyResult(status=status_for_code(code), code=code, **kwargs)
