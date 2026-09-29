# -*- coding: utf-8 -*-
"""업체 표준화·실재검증 실행 엔트리.

data/html_260908_site_master.csv를 읽어 레코드별로 업체명 표준화 + Case A/B/C 실재검증을
수행하고, 원본 컬럼 + STD 컬럼(채움) + 설계 문서 6장 산출물 컬럼을 포함한 신규 결과 CSV
(data/html_260908_site_master_std.csv)를 기록한다. 원본 CSV는 보존한다.

사용:
  python scripts/STD_VLD_260917_run_verification.py --mode mock [--limit N] [--in ...] [--out ...]
  python scripts/STD_VLD_260917_run_verification.py --mode real   # GOOGLE_MAPS_API_KEY 필요
"""

import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

import STD_VLD_260917_geo_common as gc  # noqa: E402
import STD_VLD_260917_verify_pipeline as vp  # noqa: E402
from STD_VLD_260917_locale import lang_for_country  # noqa: E402
from STD_VLD_260917_maps_adapter import make_adapter  # noqa: E402
from STD_VLD_260917_std_company import standardize_company  # noqa: E402
from STD_VLD_260929_juso_adapter import make_juso_client  # noqa: E402

IN_PATH = os.path.join(ROOT, "data", "STD_VLD_260917_site_master_light.csv")
OUT_PATH = os.path.join(ROOT, "data", "STD_VLD_260917_site_master_light_std.csv")

# 원본 컬럼(순서 유지)
BASE_COLUMNS = [
    "No.", "Status", "Site Code", "Site 유형", "업체", "항구/공항 코드",
    "기업식별 코드", "Duns No.", "국가/지역", "행정구역", "주소(Eng)", "주소(Local)",
    "위도", "경도", "관련 협력사 코드", "수정일", "Site 출처", "STD 주소", "STD 업체명",
    "도로명주소", "지번주소",
]
# 산출물 추가 컬럼(설계 문서 6장)
EXTRA_COLUMNS = [
    "표준화", "분류 코드", "비고", "표준 위도", "표준 경도",
    "place_id", "참조 URL", "addressComponents",
]
OUT_COLUMNS = BASE_COLUMNS + EXTRA_COLUMNS


def _parse_coord(row):
    """위도/경도를 (lat, lon) float 튜플로. 없거나 파싱 불가면 None."""
    try:
        lat = float(row.get("위도", "").strip())
        lon = float(row.get("경도", "").strip())
    except (ValueError, AttributeError):
        return None
    return (lat, lon)


# 국가/지역이 코드 없이 국가명으로만 적히는 경우('한국' 등)도 KR로 인식하기 위한 별칭.
_KR_ALIASES = {"KR", "KOR", "한국", "대한민국", "SOUTH KOREA", "KOREA", "REPUBLIC OF KOREA"}


def _is_kr(country_field) -> bool:
    """'국가/지역' 값이 한국인지. 'KR: 한국' 형식의 콜론 앞 코드(locale.py:33 규칙)뿐
    아니라 '한국'처럼 코드 없이 국가명으로만 적힌 경우도 KR로 인식한다."""
    if not country_field:
        return False
    text = str(country_field).strip()
    code = text.split(":", 1)[0].strip().upper()
    if code in _KR_ALIASES:
        return True
    # 콜론 뒤 국가명(또는 콜론이 없는 순수 국가명)도 확인
    tail = text.split(":", 1)[-1].strip().upper()
    return tail in _KR_ALIASES


def _has_hangul(s) -> bool:
    """문자열에 한글 음절(가~힣)이 하나라도 있으면 True."""
    return any("가" <= c <= "힣" for c in (s or ""))


def _strip_road_paren(road_addr: str) -> str:
    """행안부 roadAddr 끝의 괄호 참고항목(예: ' (천호동, 하이브2)')을 제거한다.

    이 괄호는 법정동·건물명 참고정보인데, Geocoding에 그대로 넣으면 파싱이 흐려져
    엉뚱한 지번으로 떨어진다(실측: 괄호 포함 시 '천호제3동 164-70'로 오인식). 순수
    도로명만 남겨 Geocoding에 넣기 위한 정리로, 컬럼 저장에는 원본을 그대로 쓴다.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", road_addr or "").strip()


def _juso_road_addr(addr_candidates, juso_client):
    """KR·한글 주소 후보로 행안부를 조회해 (도로명주소, 지번주소)를 반환한다.

    한글 주소만 검색 대상: 주소 후보(주소(Eng)/주소(Local)) 중 한글인 것을 순서대로
    사용한다. 입력 데이터가 한글 주소를 Eng/Local 어느 컬럼에 넣을지 일정치 않아 둘
    다 후보로 본다. 매칭 성공 시 (road_addr, jibun_addr), 실패/한글없음 시 None.

    이 결과의 road_addr를 Geocoding 입력으로 선처리하면, 입력이 지번이어도 도로명으로
    통일된 표준 주소를 얻는다(행안부만 지번↔도로명 변환이 가능하기 때문).
    """
    keyword = None
    for cand in addr_candidates:
        if _has_hangul(cand):
            keyword = cand
            break
    if keyword is None:
        return None  # 한글 주소가 없으면 대상 아님(영문 주소는 매칭률 낮음)

    hit = juso_client.resolve(keyword)
    if hit and hit.get("road_addr"):
        return hit["road_addr"], hit.get("jibun_addr", "")
    return None


def pick_case(row) -> str:
    """필드 존재로 Case A/B/C 결정. 좌표·주소 모두 없으면 'X'(실패)."""
    coord = _parse_coord(row)
    has_addr = bool((row.get("주소(Eng)") or "").strip()) or \
        bool((row.get("주소(Local)") or "").strip())
    if has_addr and coord:
        return "C"
    if has_addr:
        return "A"
    if coord:
        return "B"
    return "X"


def process_row(row, adapter, juso_client=None) -> dict:
    """한 행을 표준화·검증하여 출력 행 dict를 반환.

    juso_client가 주어지고 KR·한글 주소이면, Geocoding 전에 행안부로 지번→도로명
    변환을 선처리하여 표준 주소를 도로명으로 통일한다(Geocoding은 지번↔도로명 변환을
    하지 못하므로 입력 자체를 도로명으로 바꿔 넣는다).
    """
    disp = (row.get("업체") or "").strip()
    company_std = standardize_company(disp)
    addr_en = (row.get("주소(Eng)") or "").strip()
    addr_local = (row.get("주소(Local)") or "").strip()
    coord = _parse_coord(row)
    lang = lang_for_country(row.get("국가/지역"))

    # 행안부 선처리(KR·한글): 지번→도로명 변환 후 그 도로명을 유일한 Geocoding 입력으로
    # 사용한다. 원본 주소(Eng/Local)는 out(=dict(row))에 그대로 보존된다.
    juso_road = juso_jibun = ""
    if juso_client and _is_kr(row.get("국가/지역")):
        hit = _juso_road_addr([addr_en, addr_local], juso_client)
        if hit:
            juso_road, juso_jibun = hit  # 컬럼에는 행안부 원본(괄호 포함) 보존
            # Geocoding 입력은 괄호 참고항목을 제거한 순수 도로명으로 단일 치환
            addr_en, addr_local = _strip_road_paren(juso_road), ""

    case = pick_case({"주소(Eng)": addr_en, "주소(Local)": addr_local,
                      "위도": row.get("위도"), "경도": row.get("경도")})

    if not company_std:
        result = gc.make_result(gc.FAILED_ALL_METHODS, note="업체명이 비어 있어 검증 불가")
    elif case == "C":
        result = vp.verify_case_C(company_std, addr_en, addr_local, coord, adapter,
                                  company_disp=disp, lang=lang)
    elif case == "A":
        result = vp.verify_case_A(company_std, addr_en or addr_local, adapter,
                                  company_disp=disp, lang=lang)
    elif case == "B":
        result = vp.verify_case_B(company_std, coord, adapter, company_disp=disp, lang=lang)
    else:
        result = gc.make_result(gc.FAILED_ALL_METHODS,
                                note="좌표·주소 자원이 전혀 없어 표준화 불가")

    out = dict(row)
    out["STD 업체명"] = company_std
    out["STD 주소"] = result.std_address or ""
    out["표준화"] = result.status
    out["분류 코드"] = result.code
    out["비고"] = result.note
    out["표준 위도"] = f"{result.std_lat:.6f}" if result.std_lat is not None else ""
    out["표준 경도"] = f"{result.std_lon:.6f}" if result.std_lon is not None else ""
    out["place_id"] = result.place_id or ""
    out["참조 URL"] = result.reference_url or ""
    out["addressComponents"] = (
        json.dumps(result.address_components, ensure_ascii=False)
        if result.address_components else ""
    )
    # 행안부 선처리로 확보한 한글 도로명/지번(변환 성공 시에만 채움).
    out["도로명주소"] = juso_road
    out["지번주소"] = juso_jibun
    return out


def main(argv=None) -> int:
    load_dotenv(os.path.join(ROOT, ".env"))
    parser = argparse.ArgumentParser(description="업체 표준화·실재검증 실행")
    parser.add_argument("--mode", choices=["mock", "real"], default=None,
                        help="어댑터 모드(기본: 환경변수 MAPS_ADAPTER_MODE 또는 mock)")
    parser.add_argument("--in", dest="in_path", default=IN_PATH)
    parser.add_argument("--out", dest="out_path", default=OUT_PATH)
    parser.add_argument("--limit", type=int, default=None, help="처리 행 수 제한")
    args = parser.parse_args(argv)

    mode = args.mode or os.getenv("MAPS_ADAPTER_MODE", "real")
    adapter = make_adapter(mode, api_key=os.getenv("GOOGLE_MAPS_API_KEY"))
    juso_client = make_juso_client(os.getenv("JUSO_CONFM_KEY"))

    with open(args.in_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]

    out_rows = [process_row(r, adapter, juso_client) for r in rows]

    with open(args.out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    # 요약 출력
    from collections import Counter
    status_c = Counter(r["표준화"] for r in out_rows)
    code_c = Counter(r["분류 코드"] for r in out_rows)
    print(f"완료: {args.out_path} (mode={mode}, {len(out_rows)}건)")
    print("표준화:", dict(status_c))
    print("분류 코드:")
    for k, v in sorted(code_c.items()):
        print(f"  {v:3d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
