# -*- coding: utf-8 -*-
"""Golden Dataset 변형(perturbation) 라이브러리.

표준화 이후 데이터 불변식(설계 문서 §1-2)을 준수한다:
  - 주소(addressComponents): Google 지오코딩 출력이므로 오탈자 없음.
    정당한 변이 = granularity 차이 / long·short·로마자 표기 변이 / 순서 차이 / 결측.
  - 업체명: 법인격만 제거되고 철자는 원본 유지 → 오탈자·표기차 정당.
  - 식별자(code/duns): 표준화 대상이 아니므로 하이픈/공백/오탈자/결측 정당.

각 변형 함수는 (변형된 record dict, 목표 gate verdict, variant_type) 을 반환한다.
목표 verdict 는 "이 변형된 행을 원본과 비교했을 때 해당 gate 가 내야 할 판정"이다.
record 는 한국어 키 dict 이며 addressComponents 는 JSON 문자열로 유지한다.

설계 문서: documents/Site Code 채번 고도화_260929_Similarity_Golden Dataset 설계.md
"""

import copy
import json
import math

from SIM_260929_eval_common import EQUAL, SIMILAR, DIFFERENT, SKIP

# dedup 의 상위/하위 주소 레벨 구분을 그대로 참조
UPPER_LEVELS = ("country", "administrative_area_level_1",
                "administrative_area_level_2", "administrative_area_level_3",
                "locality", "sublocality")
LOWER_LEVELS = ("route", "street_number")

LEGAL_SUFFIXES = ["Co., Ltd.", "Inc.", "Corp.", "㈜", "株式会社", "有限公司"]


# ---------------------------------------------------------------------------
# 저수준 헬퍼
# ---------------------------------------------------------------------------
def _clone(rec: dict) -> dict:
    """레코드를 깊은 복사한다(변형 함수가 원본을 훼손하지 않도록).

    Args:
        rec (dict): 원본 레코드.

    Returns:
        dict: 깊은 복사본.
    """
    return copy.deepcopy(rec)


def _load_components(rec: dict) -> list:
    """레코드의 addressComponents JSON 문자열을 리스트로 로드. 실패 시 [].

    Args:
        rec (dict): 'addressComponents' 키를 가진 레코드.

    Returns:
        list: 파싱된 컴포넌트 리스트.
    """
    raw = rec.get("addressComponents") or ""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []


def _dump_components(rec: dict, comps: list) -> None:
    """컴포넌트 리스트를 JSON 문자열로 직렬화해 레코드에 다시 넣는다.

    Args:
        rec (dict): 저장 대상 레코드.
        comps (list): addressComponents 리스트.
    """
    rec["addressComponents"] = json.dumps(comps, ensure_ascii=False)


def _has_level(comps: list, level: str) -> bool:
    """컴포넌트 중 지정 레벨을 types에 가진 것이 있는지.

    Args:
        comps (list): addressComponents 리스트.
        level (str): 찾을 레벨명.

    Returns:
        bool: 해당 레벨이 있으면 True.
    """
    return any(level in c.get("types", []) for c in comps)


def _first_with_level(comps: list, levels) -> int:
    """levels 중 하나를 types 에 가진 첫 컴포넌트의 인덱스. 없으면 -1.

    Args:
        comps (list): addressComponents 리스트.
        levels (iterable): 찾을 레벨명 모음.

    Returns:
        int: 첫 매칭 컴포넌트 인덱스. 없으면 -1.
    """
    for i, c in enumerate(comps):
        if any(lv in c.get("types", []) for lv in levels):
            return i
    return -1


def _get_coord(rec: dict):
    """레코드에서 (lat, lon) 좌표를 추출. 표준 좌표 우선, 실패 시 None.

    Args:
        rec (dict): 좌표 컬럼을 가진 레코드.

    Returns:
        tuple | None: (lat, lon). 파싱 불가면 None.
    """
    lat = rec.get("표준 위도") or rec.get("위도")
    lon = rec.get("표준 경도") or rec.get("경도")
    try:
        return float(str(lat).strip()), float(str(lon).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _set_coord(rec: dict, lat: float, lon: float) -> None:
    """레코드의 표준 위/경도 컬럼을 소수 6자리 문자열로 설정한다.

    Args:
        rec (dict): 저장 대상 레코드.
        lat (float): 위도.
        lon (float): 경도.
    """
    rec["표준 위도"] = f"{lat:.6f}"
    rec["표준 경도"] = f"{lon:.6f}"


def offset_coord(lat: float, lon: float, meters: float, bearing_deg: float = 0.0):
    """(lat,lon)에서 bearing 방향으로 meters 만큼 이동한 좌표(inverse-haversine 근사).

    bearing 0=북. dedup 의 haversine 과 동일한 지구 반지름(6371000m)을 사용해
    거리 경계(100m)를 정확히 넘나들게 한다.

    Args:
        lat (float): 기준 위도.
        lon (float): 기준 경도.
        meters (float): 이동 거리(m).
        bearing_deg (float, optional): 방위각(도, 0=북). 기본 0.0.

    Returns:
        tuple: 이동 후 (lat, lon).
    """
    r = 6371000.0
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    ang = meters / r
    p2 = math.asin(math.sin(p1) * math.cos(ang)
                   + math.cos(p1) * math.sin(ang) * math.cos(br))
    l2 = math.radians(lon) + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(p1),
        math.cos(ang) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


# ---------------------------------------------------------------------------
# 업체명 변형 (→ name_gate)
# ---------------------------------------------------------------------------
def name_legal_suffix(rec: dict, suffix: str = "Co., Ltd."):
    """법인격 접미사 부착. comparison_key 가 제거하므로 EQUAL 이어야 한다.

    Args:
        rec (dict): 원본 레코드.
        suffix (str, optional): 부착할 법인격 접미사. 기본 "Co., Ltd.".

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    out["STD 업체명"] = f"{(rec.get('STD 업체명') or '').strip()} {suffix}".strip()
    return out, EQUAL, "name_legal_suffix"


def name_case_punct(rec: dict):
    """대소문자/구두점/공백 변형. EQUAL 이어야 한다.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    s = (rec.get("STD 업체명") or "")
    out["STD 업체명"] = s.upper().replace(" ", "  ").replace("-", " ")
    return out, EQUAL, "name_case_punct"


def name_typo1(rec: dict):
    """1자 치환 오타. 접두사 가중(JaroWinkler)을 피하려 뒤쪽 알파넘 문자를 치환한다.

    첫 글자를 바꾸면 짧은 이름에서 SIM 이 급락하므로(로직 특성), 마지막에서 두 번째
    알파넘 문자를 인접 문자로 치환해 대체로 EQUAL 을 유지한다.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    s = list(rec.get("STD 업체명") or "")
    alnum_idx = [i for i, ch in enumerate(s) if ch.isalnum()]
    if alnum_idx:
        # 마지막에서 두 번째(없으면 마지막) 알파넘 위치를 치환
        i = alnum_idx[-2] if len(alnum_idx) >= 2 else alnum_idx[-1]
        s[i] = "x" if s[i].lower() != "x" else "y"
    out["STD 업체명"] = "".join(s)
    return out, EQUAL, "name_typo1"


def name_typo2(rec: dict):
    """2자 치환 오타. SIM 을 EQUAL 임계(0.85) 아래로 떨어뜨려 name_gate 를 DIFFERENT 로
    만드는 것이 목표(복합 변형용). 단, SIM 값이 이름 길이·문자 분포에 따라 달라지므로
    verdict 를 단정하지 않고(None) 관측만 한다. 마지막 두 알파넘 문자를 치환한다.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, None(관측 전용), variant_type).
    """
    out = _clone(rec)
    s = list(rec.get("STD 업체명") or "")
    alnum_idx = [i for i, ch in enumerate(s) if ch.isalnum()]
    for i in alnum_idx[-2:]:
        s[i] = "x" if s[i].lower() != "x" else "q"
    out["STD 업체명"] = "".join(s)
    return out, None, "name_typo2"


def name_word_order(rec: dict):
    """토큰 순서 교환.

    주의(관측된 약점): comparison_key 가 최종 단계에서 공백까지 제거해 토큰 경계가
    사라지므로 token_sort_ratio 가 어순을 정렬로 흡수하지 못한다. 따라서 어순 교환은
    현재 로직에서 대체로 DIFFERENT 다. 이는 로직 특성이므로 기대 verdict 를 단정하지
    않고(None) 관측만 한다. (개선 시 comparison_key 에 공백 보존이 필요.)

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, None(관측 전용), variant_type).
    """
    out = _clone(rec)
    toks = (rec.get("STD 업체명") or "").split()
    if len(toks) >= 2:
        toks = toks[::-1]
    out["STD 업체명"] = " ".join(toks)
    return out, None, "name_word_order"


# ---------------------------------------------------------------------------
# 주소 변형 (→ address_gate). 주소 오탈자 금지.
# ---------------------------------------------------------------------------
def addr_drop_detail(rec: dict):
    """하위 레벨(route/street_number/premise) 제거 = granularity 차이.

    남은 공통 상위 레벨이 전부 일치하면 EQUAL(하위는 한쪽에만 있어 비교 제외).

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    comps = [c for c in _load_components(rec)
             if not any(lv in c.get("types", [])
                        for lv in LOWER_LEVELS + ("premise", "subpremise"))]
    _dump_components(out, comps)
    return out, EQUAL, "addr_drop_detail"


def addr_abbr_iso(rec: dict):
    """상위 레벨의 long_text 를 변형하되 short_text 는 유지 → cross-field EQUAL.

    _upper_level_same 의 {long,short} 교집합 규칙으로 흡수되어 EQUAL 이어야 한다.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    comps = _load_components(rec)
    changed = False
    # long_text 와 short_text 가 서로 다른 상위 레벨을 찾아 long 만 확장한다
    # (short 교집합이 유지되므로 _upper_level_same 이 EQUAL 로 흡수).
    for c in comps:
        if not any(lv in c.get("types", []) for lv in UPPER_LEVELS):
            continue
        if c.get("short_text") and c.get("long_text") != c.get("short_text"):
            c["long_text"] = c["long_text"] + " Region"  # 표기만 확장
            changed = True
            break
    _dump_components(out, comps)
    return out, EQUAL, "addr_abbr_iso" if changed else "addr_abbr_iso_noop"


def addr_upper_romanization(rec: dict, edits: int = 1):
    """상위 레벨 로마자 표기 변이(오탈자 아님). short_text 를 제거해 cross-field
    보정을 막고 long_text 를 edits 만큼 변형한다.

    edits==1 → 편집거리 1 → _upper_level_same True → SIMILAR.
    edits>=3 → 편집거리 초과 → DIFFERENT.

    Args:
        rec (dict): 원본 레코드.
        edits (int, optional): 추가할 문자 수(편집거리). 기본 1.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    comps = _load_components(rec)
    # locality/admin1 은 블로킹 키라 유지하고, 그 아래 상위 레벨을 골라 변형
    idx = _first_with_level(comps, ("administrative_area_level_2",
                                    "administrative_area_level_3", "sublocality"))
    if idx < 0:
        idx = _first_with_level(comps, ("locality",))
    target_verdict = SIMILAR if edits <= 1 else DIFFERENT
    if idx >= 0:
        c = comps[idx]
        long = c.get("long_text") or ""
        c["short_text"] = ""              # cross-field 보정 차단
        # long_text 끝에 edits 개 문자를 덧붙여 편집거리 = edits 로 만든다
        c["long_text"] = long + ("z" * edits)
    _dump_components(out, comps)
    vt = "addr_upper_typo1" if edits <= 1 else "addr_upper_diff"
    return out, target_verdict, vt


def addr_lower_reorder(rec: dict):
    """하위 레벨(route) 토큰 순서 뒤집기. Jaccard=1 이지만 값이 달라 SIMILAR.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    comps = _load_components(rec)
    idx = _first_with_level(comps, ("route",))
    verdict = SIMILAR
    if idx >= 0:
        c = comps[idx]
        toks = (c.get("long_text") or "").split()
        if len(toks) >= 2:
            c["long_text"] = " ".join(toks[::-1])
            c["short_text"] = " ".join((c.get("short_text") or "").split()[::-1])
        else:
            verdict = EQUAL   # 토큰 1개면 순서 변화 없음 → 그대로 EQUAL
    else:
        verdict = EQUAL       # route 없으면 상위만 비교 → EQUAL
    _dump_components(out, comps)
    return out, verdict, "addr_lower_reorder"


# ---------------------------------------------------------------------------
# 좌표 변형 (→ coord_gate, 100m)
# ---------------------------------------------------------------------------
def coord_none(rec: dict):
    """좌표 결측 → SKIP.

    Args:
        rec (dict): 원본 레코드.

    Returns:
        tuple: (변형 record, SKIP, variant_type).
    """
    out = _clone(rec)
    out["표준 위도"] = ""
    out["표준 경도"] = ""
    out["위도"] = ""
    out["경도"] = ""
    return out, SKIP, "coord_none"


def coord_drift(rec: dict, meters: float):
    """좌표를 meters 만큼 북쪽 이동. <=100m EQUAL, >100m DIFFERENT.

    Args:
        rec (dict): 원본 레코드.
        meters (float): 북쪽 이동 거리(m).

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type). 좌표 결측이면 SKIP.
    """
    out = _clone(rec)
    c = _get_coord(rec)
    verdict = EQUAL if meters <= 100.0 else DIFFERENT
    if c:
        lat, lon = offset_coord(c[0], c[1], meters, bearing_deg=0.0)
        _set_coord(out, lat, lon)
    else:
        verdict = SKIP
    return out, verdict, f"coord_drift_{int(meters)}m"


# ---------------------------------------------------------------------------
# 식별자 변형 (→ code_gate / duns_gate)
# ---------------------------------------------------------------------------
def code_hyphen_space(rec: dict, field: str = "기업식별 코드"):
    """구분자 삽입. 정규화로 제거되어 EQUAL 이어야 한다.

    Args:
        rec (dict): 원본 레코드.
        field (str, optional): 변형할 식별자 컬럼명. 기본 "기업식별 코드".

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    v = str(rec.get(field) or "")
    if len(v) >= 2:
        mid = len(v) // 2
        out[field] = v[:mid] + "-" + v[mid:]
    return out, EQUAL, f"{_id_tag(field)}_hyphen"


def code_typo1(rec: dict, field: str = "기업식별 코드"):
    """동일 길이 1자 치환 → SIMILAR(자릿수 동일 + 편집거리 1).

    Args:
        rec (dict): 원본 레코드.
        field (str, optional): 변형할 식별자 컬럼명. 기본 "기업식별 코드".

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    v = list(str(rec.get(field) or ""))
    if v:
        v[-1] = "0" if v[-1] != "0" else "1"
    out[field] = "".join(v)
    return out, SIMILAR, f"{_id_tag(field)}_typo1"


def code_typo2(rec: dict, field: str = "기업식별 코드"):
    """동일 길이 2자 치환 → 편집거리 2 > CODE_SIMILAR_MAX_EDITS(1) → DIFFERENT.

    find_similar 의 _relax_id_gate(편집거리 ≤1 만 SIMILAR 재분류)도 통과 못 하므로
    veto 가 발동한다(복합 저점 프로파일용).

    Args:
        rec (dict): 원본 레코드.
        field (str, optional): 변형할 식별자 컬럼명. 기본 "기업식별 코드".

    Returns:
        tuple: (변형 record, 목표 verdict, variant_type).
    """
    out = _clone(rec)
    v = list(str(rec.get(field) or ""))
    for i in (-1, -2):
        if len(v) >= abs(i):
            v[i] = "0" if v[i] != "0" else "1"
    out[field] = "".join(v)
    return out, DIFFERENT, f"{_id_tag(field)}_typo2"


def code_missing(rec: dict, field: str = "기업식별 코드"):
    """식별자 결측 → SKIP.

    Args:
        rec (dict): 원본 레코드.
        field (str, optional): 변형할 식별자 컬럼명. 기본 "기업식별 코드".

    Returns:
        tuple: (변형 record, SKIP, variant_type).
    """
    out = _clone(rec)
    out[field] = ""
    return out, SKIP, f"{_id_tag(field)}_missing"


def _id_tag(field: str) -> str:
    """식별자 컬럼명을 variant_type 접두 태그(code/duns)로 변환.

    Args:
        field (str): 식별자 컬럼명.

    Returns:
        str: "duns"(Duns No.) 또는 "code".
    """
    return "duns" if field == "Duns No." else "code"


# ---------------------------------------------------------------------------
# 복합(multi-field) 변형
# ---------------------------------------------------------------------------
def compose(rec: dict, steps: list):
    """변형 함수 리스트를 순차 적용해 여러 필드를 동시에 열화한다.

    steps: [(fn, gate), ...] — 각 fn 은 record 를 받아 (변형 record, verdict, vt) 반환.
    gate 는 그 성분이 겨냥하는 gate 이름(code/duns/addr/coord/name).

    반환: (변형 record, per_gate: {gate: verdict}, tags: [vt,...])
    각 성분 함수가 record 를 반환하므로 체이닝된다. verdict 가 None(관측 전용)이면
    per_gate 에 포함하지 않는다(결정적 성분만 Oracle 검증 대상).

    Args:
        rec (dict): 원본 레코드.
        steps (list): [(변형함수, gate이름), ...] 순차 적용할 성분 목록.

    Returns:
        tuple: (변형 record, {gate: verdict}, [variant_type, ...]).
    """
    cur = _clone(rec)
    per_gate = {}
    tags = []
    for fn, gate in steps:
        cur, verdict, vt = fn(cur)
        tags.append(vt)
        if verdict is not None:
            per_gate[gate] = verdict
    return cur, per_gate, tags
