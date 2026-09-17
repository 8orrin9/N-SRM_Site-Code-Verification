# -*- coding: utf-8 -*-
"""주소 표준화 및 실재검증 파이프라인 (Case A/B/C + 듀얼주소 전처리 + 통합 매트릭스).

설계 문서 2/3/4장의 의사결정 트리를 그대로 구현한다. 어댑터(G/TS/TSA/RG)를 주입받아
레코드 단위 VerifyResult를 반환한다. addressComponents는 각 leaf에서 문서 주석(※)이
지정한 소스(G/TS/TSA/RG)를 채택하며, Case C의 MISMATCH만 두 소스를 병존한다.
"""

import STD_VLD_260917_geo_common as gc
from STD_VLD_260917_geo_common import make_result

CMP_TOLERANCE_M = gc.CMP_TOLERANCE_M


# ---------------------------------------------------------------------------
# 참조 URL 생성 (설계 문서 6장)
# ---------------------------------------------------------------------------
def _place_url(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def _query_url(company: str, address: str) -> str:
    import urllib.parse
    q = urllib.parse.quote(f"{company} {address}".strip())
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _verified_reason(relaxed: bool, direct_code: str, relaxed_code: str) -> str:
    return relaxed_code if relaxed else direct_code


# ---------------------------------------------------------------------------
# Case A — 주소 + 업체명
# ---------------------------------------------------------------------------
def verify_case_A(company_std, addr_text, adapter, *, company_disp=None) -> gc.VerifyResult:
    disp = company_disp or company_std
    g = adapter.G(f"{company_std} {addr_text}")

    if g["found"]:
        ts = adapter.TS(company_std, g["coord_std"])
        if ts["found"]:
            code = _verified_reason(ts["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                    gc.VERIFIED_GEOCODE_RELAXED)
            return make_result(
                code, note="지오코딩 성공, 표준좌표 기준 TextSearch 매칭"
                + ("(반경 완화)" if ts["relaxed"] else ""),
                std_address=g["address_std"],
                std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
                place_id=ts["place_id_t"], reference_url=_place_url(ts["place_id_t"]),
                address_components=ts["address_components_t"],
                method_trace=["G", "TS"])
        # TS 미발견 → 확인 필요(G 결과 잠정 채택)
        return make_result(
            gc.UNVERIFIED_NOT_FOUND,
            note="지오코딩은 성공했으나 표준좌표 기준 TextSearch에서 업체 미발견",
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            reference_url=_query_url(disp, addr_text),
            address_components=g["address_components_g"],
            method_trace=["G", "TS"])

    # G 실패 → TSA
    tsa = adapter.TSA(company_std, addr_text)
    if tsa["found"]:
        return make_result(
            gc.VERIFIED_TEXTSEARCH_ADDR_TEXT,
            note=f"지오코딩 실패, 업체명+주소텍스트 TextSearch로 매칭(레벨 L{tsa['level']})",
            std_address=tsa.get("address_std"),
            place_id=tsa["place_id_t"], reference_url=_place_url(tsa["place_id_t"]),
            address_components=tsa["address_components_t"],
            method_trace=["G", "TSA"])
    return make_result(
        gc.FAILED_ALL_METHODS,
        note="좌표 자원이 없는 상태에서 지오코딩·TextSearch 모두 실패",
        reference_url=_query_url(disp, addr_text),
        method_trace=["G", "TSA"])


# ---------------------------------------------------------------------------
# Case B — 좌표 + 업체명
# ---------------------------------------------------------------------------
def verify_case_B(company_std, coord, adapter, *, company_disp=None) -> gc.VerifyResult:
    disp = company_disp or company_std
    ts = adapter.TS(company_std, coord)
    if ts["found"]:
        code = _verified_reason(ts["relaxed"], gc.VERIFIED_COORD_DIRECT,
                                gc.VERIFIED_COORD_RELAXED)
        return make_result(
            code, note="기존좌표 기준 TextSearch 매칭"
            + ("(반경 완화)" if ts["relaxed"] else ""),
            std_address=ts.get("address_std"),
            std_lat=ts["coord_t"][0], std_lon=ts["coord_t"][1],
            place_id=ts["place_id_t"], reference_url=_place_url(ts["place_id_t"]),
            address_components=ts["address_components_t"],
            method_trace=["TS"])
    # TS 실패 → RG(주소만 확보)
    rg = adapter.RG(coord)
    return make_result(
        gc.UNVERIFIED_REVERSE_GEOCODE_ONLY,
        note="TextSearch 실패, Reverse Geocoding으로 주소만 확보(실재 검증 불가)",
        std_address=rg["address_rg"], std_lat=coord[0], std_lon=coord[1],
        reference_url=_query_url(disp, rg["address_rg"] or ""),
        address_components=rg["address_components_rg"],
        method_trace=["TS", "RG"])


# ---------------------------------------------------------------------------
# Case C — 주소 + 좌표 + 업체명  (G 결과를 받아 2단계 이하를 수행하는 내부 함수)
# ---------------------------------------------------------------------------
def _case_C_with_G(company_std, disp, addr_text, coord, g, adapter) -> gc.VerifyResult:
    """G.found = True 이후의 Case C 서브트리(문서 4장 2번)."""
    dist = gc.haversine(g["coord_std"], coord)

    if dist <= CMP_TOLERANCE_M:  # 2-2 위치 정합
        ts = adapter.TS(company_std, g["coord_std"])
        if ts["found"]:
            code = _verified_reason(ts["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                    gc.VERIFIED_GEOCODE_RELAXED)
            return make_result(
                code, note="표준·기존 좌표 정합, 표준좌표 TextSearch 매칭"
                + ("(반경 완화)" if ts["relaxed"] else ""),
                std_address=g["address_std"],
                std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
                place_id=ts["place_id_t"], reference_url=_place_url(ts["place_id_t"]),
                address_components=ts["address_components_t"],
                method_trace=["G", "TS"])
        return make_result(
            gc.UNVERIFIED_NOT_FOUND,
            note="표준·기존 좌표는 정합하나 TextSearch에서 업체 미발견",
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            reference_url=_query_url(disp, addr_text),
            address_components=g["address_components_g"],
            method_trace=["G", "TS"])

    # 2-3 위치 불일치 → 기존좌표 TS_old
    ts_old = adapter.TS(company_std, coord)
    if ts_old["found"]:
        result = gc.CMP(g["place_id_g"], ts_old["place_id_t"],
                        g["coord_std"], ts_old["coord_t"])
        if result in ("MATCH", "PROXIMITY_MATCH"):
            code = (gc.VERIFIED_PLACEID_MATCH if result == "MATCH"
                    else gc.VERIFIED_PROXIMITY_MATCH)
            note = ("place_id 동일 → 좌표 오차로 판단(기존좌표 오류 가능)"
                    if result == "MATCH"
                    else "place_id는 다르나 두 위치가 근접 → 동일 부지로 판단")
            return make_result(
                code, note=note, std_address=g["address_std"],
                std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
                place_id=g["place_id_g"], reference_url=_place_url(g["place_id_g"]),
                address_components=g["address_components_g"],
                method_trace=["G", "TS_old", "CMP"])
        # MISMATCH → 확인 필요, 두 후보 addressComponents 병존
        both = list(g["address_components_g"]) + list(ts_old["address_components_t"])
        return make_result(
            gc.UNVERIFIED_PLACEID_MISMATCH,
            note="표준·기존 좌표에서 서로 다른 업체 발견 → 동명이업체/위치오류 의심(두 후보 제시)",
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            reference_url=_query_url(disp, addr_text),
            address_components=both,
            method_trace=["G", "TS_old", "CMP"])

    # TS_old 실패 → 표준좌표 TS_std
    ts_std = adapter.TS(company_std, g["coord_std"])
    if ts_std["found"]:
        code = _verified_reason(ts_std["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                gc.VERIFIED_GEOCODE_RELAXED)
        return make_result(
            code, note="기존좌표 TextSearch 실패, 표준좌표 TextSearch로 매칭(기존좌표 신뢰도 낮음)"
            + ("(반경 완화)" if ts_std["relaxed"] else ""),
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            place_id=ts_std["place_id_t"], reference_url=_place_url(ts_std["place_id_t"]),
            address_components=ts_std["address_components_t"],
            method_trace=["G", "TS_old", "TS_std"])
    return make_result(
        gc.UNVERIFIED_NOT_FOUND,
        note="표준·기존 좌표 모두 TextSearch에서 업체 미발견",
        std_address=g["address_std"],
        std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
        reference_url=_query_url(disp, addr_text),
        address_components=g["address_components_g"],
        method_trace=["G", "TS_old", "TS_std"])


def _case_C_g_failed(company_std, disp, addr_text, coord, adapter) -> gc.VerifyResult:
    """G.found = False 이후의 Case C 서브트리(문서 4장 3번)."""
    ts_old = adapter.TS(company_std, coord)
    if ts_old["found"]:
        code = _verified_reason(ts_old["relaxed"], gc.VERIFIED_COORD_DIRECT,
                                gc.VERIFIED_COORD_RELAXED)
        return make_result(
            code, note="지오코딩 실패, 기존좌표 TextSearch로 매칭"
            + ("(반경 완화)" if ts_old["relaxed"] else ""),
            std_address=ts_old.get("address_std"),
            std_lat=ts_old["coord_t"][0], std_lon=ts_old["coord_t"][1],
            place_id=ts_old["place_id_t"], reference_url=_place_url(ts_old["place_id_t"]),
            address_components=ts_old["address_components_t"],
            method_trace=["G(fail)", "TS_old"])
    tsa = adapter.TSA(company_std, addr_text)
    if tsa["found"]:
        return make_result(
            gc.VERIFIED_TEXTSEARCH_ADDR_TEXT,
            note=f"지오코딩·기존좌표 TextSearch 실패, 주소텍스트 TextSearch로 매칭(L{tsa['level']})",
            std_address=tsa.get("address_std"),
            place_id=tsa["place_id_t"], reference_url=_place_url(tsa["place_id_t"]),
            address_components=tsa["address_components_t"],
            method_trace=["G(fail)", "TS_old", "TSA"])
    rg = adapter.RG(coord)
    return make_result(
        gc.UNVERIFIED_REVERSE_GEOCODE_ONLY,
        note="지오코딩·TextSearch 모두 실패, Reverse Geocoding으로 주소만 확보",
        std_address=rg["address_rg"], std_lat=coord[0], std_lon=coord[1],
        reference_url=_query_url(disp, rg["address_rg"] or ""),
        address_components=rg["address_components_rg"],
        method_trace=["G(fail)", "TS_old", "TSA", "RG"])


def verify_case_C(company_std, addr_en, addr_local, coord, adapter,
                  *, company_disp=None) -> gc.VerifyResult:
    disp = company_disp or company_std
    dual = bool(addr_en) and bool(addr_local)

    if dual:
        return _run_dual_address_C(company_std, disp, addr_en, addr_local, coord, adapter)

    addr_text = addr_en or addr_local
    g = adapter.G(f"{company_std} {addr_text}")
    if g["found"]:
        return _case_C_with_G(company_std, disp, addr_text, coord, g, adapter)
    return _case_C_g_failed(company_std, disp, addr_text, coord, adapter)


# ---------------------------------------------------------------------------
# 듀얼주소 전처리 (설계 문서 1-2장) — Case A/C 1단계(G) 대체
# ---------------------------------------------------------------------------
def _run_dual_address_C(company_std, disp, addr_en, addr_local, coord, adapter) -> gc.VerifyResult:
    """Case C에서 영문/현지어 주소가 모두 존재할 때의 라우팅."""
    g_local = adapter.G(f"{company_std} {addr_local}")
    g_en = adapter.G(f"{company_std} {addr_en}")

    both = g_local["found"] and g_en["found"]
    if both:
        result = gc.CMP(g_local["place_id_g"], g_en["place_id_g"],
                        g_local["coord_std"], g_en["coord_std"])
        if result in ("MATCH", "PROXIMITY_MATCH"):
            # 합의: Local 우선 채택 후 2단계 이하 정상 진입
            return _case_C_with_G(company_std, disp, addr_local, coord, g_local, adapter)
        # MISMATCH → Local/영문 각각 완주 후 통합 매트릭스
        r_local = _case_C_with_G(company_std, disp, addr_local, coord, g_local, adapter)
        r_en = _case_C_with_G(company_std, disp, addr_en, coord, g_en, adapter)
        return combine_matrix(r_local, r_en, adapter, company_std)

    if g_local["found"] or g_en["found"]:
        # 한쪽만 성공 → 그 결과를 G로 채택(신뢰도 낮음)
        g = g_local if g_local["found"] else g_en
        addr = addr_local if g_local["found"] else addr_en
        res = _case_C_with_G(company_std, disp, addr, coord, g, adapter)
        res.note = "(듀얼주소 중 한쪽 지오코딩만 성공, 신뢰도 낮음) " + res.note
        return res

    # 둘 다 실패 → G.found=False 분기. Local/영문 각각 TSA 시도(내부에서 좌표 폴백 포함)
    res = _case_C_g_failed(company_std, disp, addr_local, coord, adapter)
    if res.status == gc.STATUS_UNVERIFIED and res.code == gc.UNVERIFIED_REVERSE_GEOCODE_ONLY:
        # Local 경로가 RG까지 갔으면 영문 주소로 TSA 한 번 더 시도
        alt = _case_C_g_failed(company_std, disp, addr_en, coord, adapter)
        if alt.status == gc.STATUS_VERIFIED:
            return alt
    return res


def combine_matrix(r_local: gc.VerifyResult, r_en: gc.VerifyResult,
                   adapter=None, company_std=None) -> gc.VerifyResult:
    """설계 문서 1-2장 [통합 매트릭스]. MISMATCH 상태에서만 호출된다.

    R_local/R_en의 내부 판정은 각 Case의 'G.found=True' 서브트리 결과(검증완료/확인필요)로만
    한정된다('실패'는 등장하지 않음).
    """
    lv = r_local.status == gc.STATUS_VERIFIED
    ev = r_en.status == gc.STATUS_VERIFIED

    if lv and ev:
        # 둘 다 검증 완료 → place_id 재비교
        result = gc.CMP(r_local.place_id, r_en.place_id,
                        (r_local.std_lat, r_local.std_lon),
                        (r_en.std_lat, r_en.std_lon))
        if result in ("MATCH", "PROXIMITY_MATCH"):
            return make_result(
                gc.VERIFIED_ADDRESS_SOURCE_RESOLVED,
                note="영문/현지어 주소를 각각 완주 검증, place_id 동일/근접 → 표준 합의(Local 우선)",
                std_address=r_local.std_address,
                std_lat=r_local.std_lat, std_lon=r_local.std_lon,
                place_id=r_local.place_id, reference_url=r_local.reference_url,
                address_components=r_local.address_components,
                method_trace=["dual", "combine_matrix", "CMP"])
        # place_id 상이 → 확인 필요, 두 후보 제시
        both = list(r_local.address_components) + list(r_en.address_components)
        return make_result(
            gc.UNVERIFIED_ADDRESS_SOURCE_CONFLICT,
            note="영문/현지어 주소 모두 검증 완료됐으나 place_id 상이 → 두 후보 제시",
            std_address=r_local.std_address,
            std_lat=r_local.std_lat, std_lon=r_local.std_lon,
            reference_url=r_local.reference_url, address_components=both,
            method_trace=["dual", "combine_matrix", "CMP"])

    if lv and not ev:
        # 이긴 쪽(Local)의 내부 코드 그대로 채택, 진 쪽 사유는 비고에 로그
        r_local.note += f" | (영문 주소 경로: {r_en.code})"
        r_local.method_trace = list(r_local.method_trace) + ["dual-local-win"]
        return r_local
    if ev and not lv:
        r_en.note += f" | (현지어 주소 경로: {r_local.code})"
        r_en.method_trace = list(r_en.method_trace) + ["dual-en-win"]
        return r_en

    # 둘 다 확인 필요 → 충돌, 두 원인 병기
    both = list(r_local.address_components) + list(r_en.address_components)
    return make_result(
        gc.UNVERIFIED_ADDRESS_SOURCE_CONFLICT,
        note=f"영문/현지어 주소 모두 확인 필요(현지어: {r_local.code} / 영문: {r_en.code})",
        std_address=r_local.std_address or r_en.std_address,
        std_lat=r_local.std_lat, std_lon=r_local.std_lon,
        reference_url=r_local.reference_url, address_components=both,
        method_trace=["dual", "combine_matrix"])
