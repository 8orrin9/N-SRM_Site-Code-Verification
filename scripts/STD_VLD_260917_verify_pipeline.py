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


# TS 매칭 place가 G 좌표에서 이 거리를 넘으면 좌표 불일치로 보고 found 무효화.
# TS 1차 locationBias 반경(maps_adapter._bias 2000m)과 동일. 이름만 비슷한 원거리
# POI 오매칭(예: 'SUZHOU POSTEL'이 13km 밖 'Suzhou Postal Hub'로 매칭)을 차단한다.
TS_MATCH_GATE_M = 2000.0


def _is_approximate(g) -> bool:
    """G 좌표가 도시·구역 레벨(APPROXIMATE)인지. 이때 좌표는 앵커로 신뢰할 수 없다.

    실측: Google Geocoding은 도로/번지를 못 찾으면 도시 중심을 APPROXIMATE로 반환한다
    (예: Kematek '1 San Qian Road'→'Suzhou' 도시중심). 이 경우 진짜 업체가 도시 중심에서
    수 km 떨어져 있는 것이 정상이므로 거리 게이트·CMP에서 좌표를 신뢰하면 정탐을 놓친다.
    """
    return (g or {}).get("location_type") == "APPROXIMATE"


def _within_gate(g_coord, ts_coord, radius_m=TS_MATCH_GATE_M, *, approximate=False):
    """TS 매칭 place가 G 좌표 반경 내인지.

    - 좌표가 없으면 판단 불가로 통과.
    - G가 APPROXIMATE(도시레벨)이면 좌표 앵커가 부정확하므로 거리 게이트를 적용하지
      않는다(먼 매칭이 오히려 정상). G가 정밀할 때만 원거리 오매칭을 차단한다.
    """
    if approximate:
        return True
    if not g_coord or not ts_coord or ts_coord[0] is None:
        return True
    return gc.haversine(g_coord, ts_coord) <= radius_m


def _pick_std_address(ts_addr, ts_comps, g_addr, g_comps):
    """TS 매칭 성공 leaf의 표준 주소 선택. TS/G 주소 중 addressComponents가
    더 많은(더 상세한) 쪽을 채택하되, 동수이면 TS(매칭된 place)를 우선한다.

    실제 POI가 등재된 경우 TS가 상세하나(예: 도로+번지), 업체 미등재로 상위
    행정구역이 잡히면 G(주소 파싱)가 더 상세할 수 있다.
    """
    if not ts_addr:
        return g_addr
    if not g_addr:
        return ts_addr
    if len(g_comps or []) > len(ts_comps or []):
        return g_addr
    return ts_addr


# ---------------------------------------------------------------------------
# Case A — 주소 + 업체명
# ---------------------------------------------------------------------------
def verify_case_A(company_std, addr_text, adapter, *, company_disp=None) -> gc.VerifyResult:
    disp = company_disp or company_std
    g = adapter.G(addr_text)  # 주소만 지오코딩(업체명 결합은 파싱을 흐려 도시레벨로 떨어뜨림)

    if g["found"]:
        approx = _is_approximate(g)
        ts = adapter.TS(company_std, g["coord_std"], precise=not approx)
        if ts["found"] and _within_gate(g["coord_std"], ts["coord_t"], approximate=approx):
            if ts.get("proximity"):
                code = gc.VERIFIED_GEOCODE_PROXIMITY
            else:
                code = _verified_reason(ts["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                        gc.VERIFIED_GEOCODE_RELAXED)
            # G가 APPROXIMATE면 좌표 앵커가 부정확하므로 TS가 찾은 실제 POI 좌표를 채택.
            std_coord = ts["coord_t"] if approx else g["coord_std"]
            return make_result(
                code, note="지오코딩 성공, 표준좌표 기준 TextSearch 매칭"
                + ("(반경 완화)" if ts["relaxed"] else "")
                + ("(정밀좌표 근접 POI 수용: 업체명 표기 상이)" if ts.get("proximity") else "")
                + ("(G 도시레벨→TS 좌표 채택)" if approx else ""),
                std_address=_pick_std_address(
                    ts.get("address_std"), ts["address_components_t"],
                    g["address_std"], g["address_components_g"]),
                std_lat=std_coord[0], std_lon=std_coord[1],
                place_id=ts["place_id_t"], reference_url=_place_url(ts["place_id_t"]),
                address_components=ts["address_components_t"],
                method_trace=["G", "TS"])

        # TS 미발견 또는 게이트 탈락(원거리 오매칭) → 업체명+주소텍스트 TSA로 재검증(병행 보강)
        tsa = adapter.TSA(company_std, addr_text)
        if tsa["found"]:
            return make_result(
                gc.VERIFIED_TEXTSEARCH_ADDR_TEXT,
                note=f"표준좌표 TextSearch 미매칭, 업체명+주소텍스트 TextSearch로 매칭(레벨 L{tsa['level']})",
                std_address=tsa.get("address_std"),
                place_id=tsa["place_id_t"], reference_url=_place_url(tsa["place_id_t"]),
                address_components=tsa["address_components_t"],
                method_trace=["G", "TS", "TSA"])
        # 최종 미발견 → 확인 필요(상세한 G 주소 채택)
        return make_result(
            gc.UNVERIFIED_NOT_FOUND,
            note="지오코딩은 성공했으나 TextSearch(좌표·주소텍스트)에서 업체 미발견",
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            reference_url=_query_url(disp, g["address_std"]),
            address_components=g["address_components_g"],
            method_trace=["G", "TS", "TSA"])

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
    approx = _is_approximate(g)

    if dist <= CMP_TOLERANCE_M:  # 2-2 위치 정합
        ts = adapter.TS(company_std, g["coord_std"], precise=not approx)
        if ts["found"] and _within_gate(g["coord_std"], ts["coord_t"], approximate=approx):
            if ts.get("proximity"):
                code = gc.VERIFIED_GEOCODE_PROXIMITY
            else:
                code = _verified_reason(ts["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                        gc.VERIFIED_GEOCODE_RELAXED)
            return make_result(
                code, note="표준·기존 좌표 정합, 표준좌표 TextSearch 매칭"
                + ("(반경 완화)" if ts["relaxed"] else "")
                + ("(정밀좌표 근접 POI 수용: 업체명 표기 상이)" if ts.get("proximity") else ""),
                std_address=_pick_std_address(
                    ts.get("address_std"), ts["address_components_t"],
                    g["address_std"], g["address_components_g"]),
                std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
                place_id=ts["place_id_t"], reference_url=_place_url(ts["place_id_t"]),
                address_components=ts["address_components_t"],
                method_trace=["G", "TS"])
        return make_result(
            gc.UNVERIFIED_NOT_FOUND,
            note="표준·기존 좌표는 정합하나 TextSearch에서 업체 미발견",
            std_address=g["address_std"],
            std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
            reference_url=_query_url(disp, g["address_std"]),
            address_components=g["address_components_g"],
            method_trace=["G", "TS"])

    # 2-3 위치 불일치 → 기존좌표 TS_old
    ts_old = adapter.TS(company_std, coord)
    if ts_old["found"]:
        # G가 APPROXIMATE(도시레벨)면 G의 place_id/좌표는 '어느 업체인지'의 증인이 될 수
        # 없다(도시 중심일 뿐). CMP 거부권을 박탈하고 기존좌표 TS가 찾은 실제 POI를 채택.
        if approx:
            code = _verified_reason(ts_old["relaxed"], gc.VERIFIED_COORD_DIRECT,
                                    gc.VERIFIED_COORD_RELAXED)
            return make_result(
                code, note="지오코딩이 도시레벨(부정확)이라 위치비교 생략, 기존좌표 TextSearch 매칭"
                + ("(반경 완화)" if ts_old["relaxed"] else ""),
                std_address=ts_old.get("address_std"),
                std_lat=ts_old["coord_t"][0], std_lon=ts_old["coord_t"][1],
                place_id=ts_old["place_id_t"], reference_url=_place_url(ts_old["place_id_t"]),
                address_components=ts_old["address_components_t"],
                method_trace=["G(approx)", "TS_old"])
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
            reference_url=_query_url(disp, g["address_std"]),
            address_components=both,
            method_trace=["G", "TS_old", "CMP"])

    # TS_old 실패 → 표준좌표 TS_std
    ts_std = adapter.TS(company_std, g["coord_std"], precise=not approx)
    if ts_std["found"] and _within_gate(g["coord_std"], ts_std["coord_t"], approximate=approx):
        if ts_std.get("proximity"):
            code = gc.VERIFIED_GEOCODE_PROXIMITY
        else:
            code = _verified_reason(ts_std["relaxed"], gc.VERIFIED_GEOCODE_DIRECT,
                                    gc.VERIFIED_GEOCODE_RELAXED)
        std_coord = ts_std["coord_t"] if approx else g["coord_std"]
        return make_result(
            code, note="기존좌표 TextSearch 실패, 표준좌표 TextSearch로 매칭(기존좌표 신뢰도 낮음)"
            + ("(반경 완화)" if ts_std["relaxed"] else "")
            + ("(정밀좌표 근접 POI 수용: 업체명 표기 상이)" if ts_std.get("proximity") else "")
            + ("(G 도시레벨→TS 좌표 채택)" if approx else ""),
            std_address=_pick_std_address(
                ts_std.get("address_std"), ts_std["address_components_t"],
                g["address_std"], g["address_components_g"]),
            std_lat=std_coord[0], std_lon=std_coord[1],
            place_id=ts_std["place_id_t"], reference_url=_place_url(ts_std["place_id_t"]),
            address_components=ts_std["address_components_t"],
            method_trace=["G", "TS_old", "TS_std"])
    return make_result(
        gc.UNVERIFIED_NOT_FOUND,
        note="표준·기존 좌표 모두 TextSearch에서 업체 미발견",
        std_address=g["address_std"],
        std_lat=g["coord_std"][0], std_lon=g["coord_std"][1],
        reference_url=_query_url(disp, g["address_std"]),
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
    g = adapter.G(addr_text)  # 주소만 지오코딩(업체명 결합은 파싱을 흐려 도시레벨로 떨어뜨림)
    if g["found"]:
        return _case_C_with_G(company_std, disp, addr_text, coord, g, adapter)
    return _case_C_g_failed(company_std, disp, addr_text, coord, adapter)


# ---------------------------------------------------------------------------
# 듀얼주소 전처리 (설계 문서 1-2장) — Case A/C 1단계(G) 대체
# ---------------------------------------------------------------------------
def _run_dual_address_C(company_std, disp, addr_en, addr_local, coord, adapter) -> gc.VerifyResult:
    """Case C에서 영문/현지어 주소가 모두 존재할 때의 라우팅."""
    g_local = adapter.G(addr_local)  # 주소만 지오코딩(업체명 결합은 파싱을 흐림)
    g_en = adapter.G(addr_en)

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
