# -*- coding: utf-8 -*-
"""중복 Site 식별 로직 (Deduplication).

표준화·실재검증을 마친 Site 정보에서 동일 업체의 중복 행을 자동 식별해
"중복 확정 클러스터 / 중복 의심 엣지"로 제시한다(삭제는 사용자 몫).

프로세스 명세: docs/STD_VLD_dedup_process.md
재사용: SIM(std_company), haversine(geo_common)

사용:
  python scripts/STD_VLD_260926_dedup.py --in data/STD_VLD_260926_site_master_TF_2_std.xlsx --sheet TF_std
  python scripts/STD_VLD_260926_dedup.py --in data/STD_VLD_260917_site_master_std.csv
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from rapidfuzz.distance import Levenshtein  # noqa: E402

import STD_VLD_260917_geo_common as gc  # noqa: E402
from STD_VLD_260917_std_company import SIM, comparison_key  # noqa: E402

# ---------------------------------------------------------------------------
# 임계값 (튜닝 가능)
# ---------------------------------------------------------------------------
CODE_SIMILAR_MAX_EDITS = 1     # 코드/Duns 유사 판정 최대 편집거리(초엄격)
COORD_EQUAL_M = 100.0          # 좌표 동일 판정 거리(m)
GEO_GRID_DECIMALS = 2          # 좌표 블록 그리드 반올림 자릿수(≈1km)
ADDR_UPPER_MAX_EDITS = 1       # 상위 레벨(행정구역) 오타 허용 최대 편집거리(초엄격)
ADDR_LOWER_JACCARD = 0.5       # 하위 레벨(도로/번지) 토큰 Jaccard 유사 임계

# 게이트 반환값
EQUAL = "EQUAL"
SIMILAR = "SIMILAR"
DIFFERENT = "DIFFERENT"
SKIP = "SKIP"

# 구글 주소 레벨 위계(상위→하위)
ADDRESS_LEVELS = [
    "country",
    "administrative_area_level_1",
    "administrative_area_level_2",
    "administrative_area_level_3",
    "locality",
    "sublocality",
    "route",
    "street_number",
]
# 상위 레벨(행정 경계): 계층 일치를 엄격히 요구. 하위 레벨은 토큰 유사 허용.
ADDRESS_UPPER_LEVELS = frozenset([
    "country",
    "administrative_area_level_1",
    "administrative_area_level_2",
    "administrative_area_level_3",
    "locality",
    "sublocality",
])


# ---------------------------------------------------------------------------
# Union-Find (경로 압축 + union by rank)
# ---------------------------------------------------------------------------
class UnionFind:
    """경로 압축 + union by rank를 적용한 서로소 집합(Disjoint Set)."""

    def __init__(self, n):
        """n개 원소를 각자 독립 집합으로 초기화.

        Args:
            n (int): 원소 개수.
        """
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        """x의 대표 원소를 반환(경로 압축 적용).

        Args:
            x (int): 원소 인덱스.

        Returns:
            int: x가 속한 집합의 대표 인덱스.
        """
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 경로 압축
            x = self.parent[x]
        return x

    def union(self, a, b):
        """a와 b가 속한 두 집합을 합친다.

        Args:
            a (int): 원소 인덱스.
            b (int): 원소 인덱스.

        Returns:
            bool: 실제로 합쳐졌으면 True, 이미 같은 집합이면 False.
        """
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True

    def connected(self, a, b):
        """a와 b가 같은 집합인지.

        Args:
            a (int): 원소 인덱스.
            b (int): 원소 인덱스.

        Returns:
            bool: 같은 집합이면 True.
        """
        return self.find(a) == self.find(b)


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------
def normalize_code(s):
    """기업식별코드 정규화: 공백/구분자 제거. 빈 값이면 None.

    Args:
        s (str | None): 원본 코드 값.

    Returns:
        str | None: 영숫자만 남긴 코드. 빈 값이면 None.
    """
    if not s:
        return None
    out = "".join(ch for ch in str(s) if ch.isalnum())
    return out or None


def normalize_duns(s):
    """Duns No. 정규화: '-'/공백 제거. 빈 값이면 None.

    Args:
        s (str | None): 원본 Duns No.

    Returns:
        str | None: 영숫자만 남긴 값. 빈 값이면 None.
    """
    if not s:
        return None
    out = "".join(ch for ch in str(s) if ch.isalnum())
    return out or None


def _norm_token(s):
    """주소 값 비교용 소문자/공백정규화.

    Args:
        s (str | None): 원본 주소 값.

    Returns:
        str: 소문자화 + 공백 단일화된 문자열.
    """
    return " ".join(str(s or "").lower().split())


def _addr_tokens(s):
    """주소 값 → 토큰 집합. 소문자화 후 공백/구분자로 분해.

    Args:
        s (str | None): 원본 주소 값.

    Returns:
        set: 토큰 문자열 집합.
    """
    import re
    return {t for t in re.split(r"[\s,./\-]+", _norm_token(s)) if t}


def _jaccard(set_a, set_b):
    """두 토큰 집합의 Jaccard 유사도(교집합/합집합).

    Args:
        set_a (set): 토큰 집합 A.
        set_b (set): 토큰 집합 B.

    Returns:
        float: Jaccard 유사도(0~1). 한쪽이 비면 0.0.
    """
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _upper_level_same(vals_a, vals_b):
    """상위 레벨(행정 경계) 동일 판정.

    vals_*: (long_norm, short_norm) 튜플.
    1) 교차 필드 정확 일치: {long,short} 교집합이 있으면 동일(약어/ISO 코드/다국어 흡수).
    2) 오타 허용(초엄격): long 정규화 편집거리 ≤ ADDR_UPPER_MAX_EDITS.

    Args:
        vals_a (tuple): 레벨 A의 (long_norm, short_norm).
        vals_b (tuple): 레벨 B의 (long_norm, short_norm).

    Returns:
        bool: 동일 지역이면 True.
    """
    la, sa = vals_a
    lb, sb = vals_b
    set_a = {v for v in (la, sa) if v}
    set_b = {v for v in (lb, sb) if v}
    if set_a & set_b:                              # 1) 교차 필드 정확 일치
        return True
    if la and lb and Levenshtein.distance(la, lb) <= ADDR_UPPER_MAX_EDITS:
        return True                                # 2) 미세 오타만 허용
    return False


# ---------------------------------------------------------------------------
# 게이트
# ---------------------------------------------------------------------------
def _code_like_gate(a, b):
    """코드/Duns 공통 판정: 정규화 값 기준 EQUAL/SIMILAR/DIFFERENT/SKIP.

    Args:
        a (str | None): 정규화된 코드/Duns A.
        b (str | None): 정규화된 코드/Duns B.

    Returns:
        str: EQUAL(동일) | SIMILAR(미세 오타) | DIFFERENT | SKIP(한쪽 결측).
    """
    if a is None or b is None:
        return SKIP
    if a == b:
        return EQUAL
    # 초엄격 유사: 자릿수 동일 + 편집거리 ≤ 임계
    if len(a) == len(b) and Levenshtein.distance(a, b) <= CODE_SIMILAR_MAX_EDITS:
        return SIMILAR
    return DIFFERENT


def code_gate(row_a, row_b):
    """게이트 1: 기업식별코드.

    Args:
        row_a (dict): 비교 행 A('code' 키 참조).
        row_b (dict): 비교 행 B('code' 키 참조).

    Returns:
        str: EQUAL | SIMILAR | DIFFERENT | SKIP.
    """
    return _code_like_gate(normalize_code(row_a.get("code")),
                           normalize_code(row_b.get("code")))


def duns_gate(row_a, row_b):
    """게이트 2: Duns No. (게이트 1과 완전 독립).

    Args:
        row_a (dict): 비교 행 A('duns' 키 참조).
        row_b (dict): 비교 행 B('duns' 키 참조).

    Returns:
        str: EQUAL | SIMILAR | DIFFERENT | SKIP.
    """
    return _code_like_gate(normalize_duns(row_a.get("duns")),
                           normalize_duns(row_b.get("duns")))


def _levels_map(components):
    """addressComponents → {level: (long_norm, short_norm)}. 상위 레벨 하나만 채택.

    Args:
        components (list): 정규화된 addressComponents.

    Returns:
        dict: {레벨명: (long_norm, short_norm)}.
    """
    out = {}
    for comp in components or []:
        for t in comp.get("types", []):
            if t in ADDRESS_LEVELS and t not in out:
                out[t] = (_norm_token(comp.get("long_text")),
                          _norm_token(comp.get("short_text")))
    return out


def common_address_levels(comp_a, comp_b):
    """두 대상이 공통으로 가진 레벨을 위계 순서로 반환(요구사항 4-1-1).

    Args:
        comp_a (list): 대상 A의 addressComponents.
        comp_b (list): 대상 B의 addressComponents.

    Returns:
        tuple: (공통 레벨 리스트, A의 레벨맵, B의 레벨맵).
    """
    la, lb = _levels_map(comp_a), _levels_map(comp_b)
    return [lv for lv in ADDRESS_LEVELS if lv in la and lv in lb], la, lb


def address_gate(row_a, row_b):
    """게이트 3: 표준화 주소(구조적, 공통 최하위 레벨까지).

    계층 일치 + 하위만 토큰 방식:
      - 상위 레벨(country~sublocality): 계층 일치를 엄격히 요구.
          short_text 교차 보정 + 편집거리 ≤1 오타 허용(_upper_level_same).
          하나라도 불일치면 즉시 DIFFERENT(다른 행정구역 오탐 차단).
      - 하위 레벨(route/street_number): 토큰 Jaccard로 유사 허용.
          완전 일치가 아니면 SIMILAR 후보(순서 차이 '26 Euljiro'↔'Euljiro 26' 흡수).
    반환: EQUAL(공통 레벨 전부 동일) | SIMILAR(상위 동일 & 하위만 유사)
        | DIFFERENT | SKIP(공통 레벨 없음).

    Args:
        row_a (dict): 비교 행 A('components' 키 참조).
        row_b (dict): 비교 행 B('components' 키 참조).

    Returns:
        str: EQUAL | SIMILAR | DIFFERENT | SKIP.
    """
    common, la, lb = common_address_levels(row_a.get("components"),
                                           row_b.get("components"))
    if not common:
        return SKIP

    all_equal = True
    similar_seen = False
    for lv in common:
        va, vb = la[lv], lb[lv]          # 각 (long, short)
        if va == vb:
            continue
        # 교차 필드(long/short) 정확 일치는 표기 차이일 뿐 동일한 값으로 본다.
        set_a = {v for v in va if v}
        set_b = {v for v in vb if v}
        if set_a & set_b:
            continue
        all_equal = False
        if lv in ADDRESS_UPPER_LEVELS:
            # 상위 레벨: 동일하지 않으면(오타허용 포함) 다른 지역 → DIFFERENT
            if _upper_level_same(va, vb):
                similar_seen = True      # 표기만 다르고 같은 지역
            else:
                return DIFFERENT
        else:
            # 하위 레벨: long/short 각각 토큰 Jaccard의 최댓값으로 유사 허용
            j = max(_jaccard(_addr_tokens(va[0]), _addr_tokens(vb[0])),
                    _jaccard(_addr_tokens(va[1]), _addr_tokens(vb[1])))
            if j >= ADDR_LOWER_JACCARD:
                similar_seen = True
            else:
                return DIFFERENT
    if all_equal:
        return EQUAL
    return SIMILAR if similar_seen else DIFFERENT


# 게이트 4가 "건물/필지 단위" 정밀도로 간주하는 최소 레벨(그 이상 하위 레벨은
# 현재 ADDRESS_LEVELS에서 추적하지 않음 — route/street_number가 가장 하위).
COORD_GATE_MIN_LEVELS = frozenset(["route", "street_number"])


def _has_building_level_address(components) -> bool:
    """addressComponents가 건물/필지 단위(도로/번지)까지 존재하는지.

    Args:
        components (list): 정규화된 addressComponents.

    Returns:
        bool: route/street_number 레벨이 있으면 True.
    """
    return bool(_levels_map(components).keys() & COORD_GATE_MIN_LEVELS)


def coord_gate(row_a, row_b):
    """게이트 4: 좌표 거리(Haversine).

    주소 레벨이 건물/필지 단위(route/street_number)까지 있는 두 좌표끼리만
    "거리가 가까우면 같은 자리"로 판단한다. 한쪽이라도 그보다 상위 단위(도시/
    행정구역 등)의 주소만 가진 경우, 그 좌표는 대개 행정구역 중심점 등 대표점일
    뿐이라 가까운 것 자체가 "같은 Site"를 의미하지 않는다(서로 다른 두 Site가
    같은 시/구 중심좌표로 입력돼 우연히 EQUAL로 묶이는 오탐을 차단). 이 경우
    거리와 무관하게 SKIP — DIFFERENT로도 단정하지 않는 것은, 정보가 부족한
    상태에서의 "멀다"가 "다른 업체"를 보증하지 않기 때문(다른 게이트들의 SKIP
    처리와 동일한 원칙).

    Args:
        row_a (dict): 비교 행 A('coord'/'components' 키 참조).
        row_b (dict): 비교 행 B('coord'/'components' 키 참조).

    Returns:
        str: EQUAL(근접) | DIFFERENT(원거리) | SKIP(좌표·건물레벨 결측).
    """
    ca, cb = row_a.get("coord"), row_b.get("coord")
    if not ca or not cb:
        return SKIP
    if not (_has_building_level_address(row_a.get("components")) and
            _has_building_level_address(row_b.get("components"))):
        return SKIP
    return EQUAL if gc.haversine(ca, cb) <= COORD_EQUAL_M else DIFFERENT


def name_gate(row_a, row_b):
    """게이트 5: 표준화 업체명 최종 확인(SIM 재사용). 반환 (verdict, score).

    Args:
        row_a (dict): 비교 행 A('std_name' 키 참조).
        row_b (dict): 비교 행 B('std_name' 키 참조).

    Returns:
        tuple: (verdict, score). verdict는 EQUAL/DIFFERENT/SKIP,
            score는 SIM 유사도(0~1) 또는 None.
    """
    na, nb = row_a.get("std_name"), row_b.get("std_name")
    if not na or not nb:
        return SKIP, None
    score, is_match = SIM(na, nb)
    return (EQUAL if is_match else DIFFERENT), score


# ---------------------------------------------------------------------------
# 쌍 판정
# ---------------------------------------------------------------------------
def classify_pair(row_a, row_b):
    """두 행의 중복 여부를 종합 판정.

    반환: ("CONFIRMED", reasons, name_score)
        | ("SUSPECT", reason, name_score)
        | ("NONE", None, None)

    Args:
        row_a (dict): 비교 행 A.
        row_b (dict): 비교 행 B.

    Returns:
        tuple: (kind, reason, name_score). kind는 CONFIRMED/SUSPECT/NONE.
    """
    confirm_reason = None
    suspect_reason = None

    # 게이트를 순서대로: EQUAL이 나오면 강한 확정 근거이므로 이후 게이트는 생략한다
    # (플로차트: "코드 EQUAL → 이후 게이트 불필요"). DIFFERENT는 즉시 필터링.
    for gate_name, gate in (("code", code_gate),
                            ("duns", duns_gate),
                            ("address", address_gate),
                            ("coord", coord_gate)):
        r = gate(row_a, row_b)
        if r == DIFFERENT:
            return ("NONE", None, None)
        if r == EQUAL:
            confirm_reason = gate_name
            break
        if r == SIMILAR and suspect_reason is None:
            suspect_reason = gate_name + "_similar"

    # 확정 근거가 있으면 업체명으로 최종 교차 확인
    if confirm_reason:
        verdict, score = name_gate(row_a, row_b)
        if verdict == DIFFERENT:
            return ("NONE", None, None)
        # name_gate가 SKIP(업체명 결측)이면 코드/좌표 등 강한 근거로 확정 유지
        return ("CONFIRMED", [confirm_reason], score)

    # 확정 근거 없이 의심만 남은 경우: 프로세스 6단계에 따라 업체명이 뒷받침해야 한다.
    # (약한 근거인 유사 신호는 업체명 유사가 없으면 다른 업체로 간주해 필터링.)
    if suspect_reason:
        verdict, score = name_gate(row_a, row_b)
        if verdict == EQUAL:
            return ("SUSPECT", suspect_reason, score)
        return ("NONE", None, None)

    return ("NONE", None, None)


# ---------------------------------------------------------------------------
# 블로킹
# ---------------------------------------------------------------------------
def _block_keys(row):
    """한 행이 속하는 블록 키 집합.

    코드/Duns/좌표그리드/상위지명/업체명 정규화 키로 블록을 만들어, 전수 비교 대신
    같은 블록을 공유하는 행끼리만 후보로 삼게 한다.

    Args:
        row (dict): 비교 행.

    Returns:
        set: 블록 키 튜플 집합.
    """
    keys = set()
    code = normalize_code(row.get("code"))
    if code:
        keys.add(("code", code))
    duns = normalize_duns(row.get("duns"))
    if duns:
        keys.add(("duns", duns))
    coord = row.get("coord")
    if coord:
        lat = round(coord[0], GEO_GRID_DECIMALS)
        lon = round(coord[1], GEO_GRID_DECIMALS)
        keys.add(("geo", lat, lon))
    la = _levels_map(row.get("components"))
    # 공통 상위 지명(도시/시도) 블록 — locality 우선, 없으면 admin_1.
    # short_text(약어/ISO) 우선으로 잡아 표기 흔들림(다국어·약어)을 같은 블록에 모은다.
    for lv in ("locality", "administrative_area_level_1"):
        vals = la.get(lv)
        if vals and (vals[1] or vals[0]):
            keys.add(("addr", lv, vals[1] or vals[0]))
            break
    # 업체명 정규화 키 블록 — 코드/Duns가 결측·오타여도 동명 후보를 잡기 위함
    nk = comparison_key(row.get("std_name") or "")
    if nk:
        keys.add(("name", nk))
    return keys


def build_candidate_pairs(rows):
    """블록 키를 공유하는 행끼리만 후보 쌍(i<j)을 생성.

    Args:
        rows (list): dedup 입력 행 리스트.

    Returns:
        set: 비교할 (i, j) 인덱스 쌍 집합(i<j).
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for i, row in enumerate(rows):
        for key in _block_keys(row):
            buckets[key].append(i)
    pairs = set()
    for members in buckets.values():
        m = sorted(members)
        for x in range(len(m)):
            for y in range(x + 1, len(m)):
                pairs.add((m[x], m[y]))
    return pairs


# ---------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------
def dedup(rows):
    """전체 중복 식별. rows는 아래 dict 리스트:
      {code, duns, std_name, coord:(lat,lon)|None, components:list, status, orig_index}

    표준화 실패(STATUS_FAILED) 행은 제외. 반환: {"clusters", "suspects"}.

    Args:
        rows (list): dedup 입력 행 dict 리스트.

    Returns:
        dict: {"clusters": 확정 클러스터 리스트, "suspects": 의심 엣지 리스트}.
    """
    # 0. 표준화 실패 행 제외
    active = [i for i, r in enumerate(rows) if r.get("status") != gc.STATUS_FAILED]
    active_set = set(active)

    uf = UnionFind(len(rows))
    seen_pairs = set()
    suspect_edges = []

    for (i, j) in build_candidate_pairs(rows):
        if i not in active_set or j not in active_set:
            continue
        if (i, j) in seen_pairs:          # 재비교 방지 2: 중복 등장 쌍
            continue
        seen_pairs.add((i, j))
        if uf.connected(i, j):            # 재비교 방지 3: 이미 같은 클러스터
            continue
        kind, reason, score = classify_pair(rows[i], rows[j])
        if kind == "CONFIRMED":
            uf.union(i, j)
        elif kind == "SUSPECT":
            suspect_edges.append({"pair": [i, j], "reason": reason,
                                  "name_score": round(score, 3) if score else None})

    # 클러스터 수집(2개 이상 구성원만)
    from collections import defaultdict
    groups = defaultdict(list)
    for i in active:
        groups[uf.find(i)].append(i)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members)
        clusters.append({
            "member_indices": members,
            "representative": members[0],
        })
    clusters.sort(key=lambda c: c["representative"])

    # 의심 엣지 중 이미 같은 클러스터로 확정된 것은 제거(중복 표시 방지)
    suspects = [e for e in suspect_edges
                if not uf.connected(e["pair"][0], e["pair"][1])]

    return {"clusters": clusters, "suspects": suspects}


# ---------------------------------------------------------------------------
# 데이터 로딩 / 실행
# ---------------------------------------------------------------------------
def _parse_coord(lat_s, lon_s):
    """위도/경도 문자열을 (lat, lon) float 튜플로 변환. 실패 시 None.

    Args:
        lat_s: 위도 값(문자열 등).
        lon_s: 경도 값(문자열 등).

    Returns:
        tuple | None: (lat, lon). 파싱 불가면 None.
    """
    try:
        return (float(str(lat_s).strip()), float(str(lon_s).strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_components(s):
    """addressComponents JSON 문자열을 리스트로 파싱. 실패/빈 값이면 [].

    Args:
        s (str | None): JSON 직렬화된 addressComponents.

    Returns:
        list: 파싱된 컴포넌트 리스트.
    """
    if not s:
        return []
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return []


def _to_rows(records):
    """원본 레코드(dict) 리스트 → dedup 입력 행 리스트로 매핑.

    컬럼명이 데이터마다 다를 수 있어 안전하게 get으로 접근한다.
    표준 위도/경도가 있으면 우선, 없으면 원 위/경도 사용.

    Args:
        records (list): 원본 레코드 dict 리스트.

    Returns:
        list: dedup 입력 행 dict 리스트.
    """
    rows = []
    for rec in records:
        lat = rec.get("표준 위도") or rec.get("위도")
        lon = rec.get("표준 경도") or rec.get("경도")
        rows.append({
            "code": rec.get("기업식별 코드"),
            "duns": rec.get("Duns No."),
            "std_name": rec.get("STD 업체명"),
            "coord": _parse_coord(lat, lon),
            "components": _parse_components(rec.get("addressComponents")),
            "status": rec.get("표준화"),
            "label": (rec.get("STD 업체명") or rec.get("업체")
                      or rec.get("업체명 (Eng)") or ""),
        })
    return rows


def _load_records(in_path, sheet):
    """입력 파일(xlsx/csv)을 읽어 레코드 dict 리스트로 반환.

    Args:
        in_path (str): 입력 파일 경로.
        sheet (str | None): xlsx 시트명(csv면 무시).

    Returns:
        list: 레코드 dict 리스트.
    """
    ext = os.path.splitext(in_path)[1].lower()
    if ext in (".xlsx", ".xls"):
        import pandas as pd
        df = pd.read_excel(in_path, sheet_name=sheet or 0, dtype=str).fillna("")
        return df.to_dict("records")
    import csv
    with open(in_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _fmt_row(rows, idx):
    """클러스터/엣지 출력용으로 한 행을 사람이 읽는 요약 문자열로 포맷.

    Args:
        rows (list): dedup 입력 행 리스트.
        idx (int): 포맷할 행 인덱스.

    Returns:
        str: 들여쓰기된 요약 문자열(라벨/코드/duns/좌표).
    """
    r = rows[idx]
    parts = [f"[{idx}] {r['label']}"]
    if r.get("code"):
        parts.append(f"code={r['code']}")
    if r.get("duns"):
        parts.append(f"duns={r['duns']}")
    if r.get("coord"):
        parts.append(f"({r['coord'][0]:.4f},{r['coord'][1]:.4f})")
    return "  " + " | ".join(parts)


def main(argv=None):
    """입력 파일을 읽어 중복 식별 후 클러스터·의심 엣지를 표준출력에 출력한다.

    Args:
        argv (list, optional): CLI 인자 리스트. 기본 None(sys.argv 사용).

    Returns:
        int: 종료 코드(정상 0).
    """
    parser = argparse.ArgumentParser(description="중복 Site 식별")
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--sheet", default=None, help="xlsx 시트명")
    args = parser.parse_args(argv)

    records = _load_records(args.in_path, args.sheet)
    rows = _to_rows(records)
    result = dedup(rows)

    print(f"입력 {len(rows)}행 (실패 제외 대상 "
          f"{sum(1 for r in rows if r['status'] != gc.STATUS_FAILED)}행)")
    print(f"=== 중복 확정 클러스터: {len(result['clusters'])}개")
    for c in result["clusters"]:
        print(f"■ 클러스터(대표 [{c['representative']}]) "
              f"— {len(c['member_indices'])}개 행")
        for idx in c["member_indices"]:
            print(_fmt_row(rows, idx))
    print(f"\n=== 중복 의심 엣지: {len(result['suspects'])}개")
    for e in result["suspects"]:
        i, j = e["pair"]
        print(f"? [{i}] ↔ [{j}]  사유={e['reason']} 업체명유사={e['name_score']}")
        print(_fmt_row(rows, i))
        print(_fmt_row(rows, j))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
