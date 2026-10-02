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
from SIM_261002_translate import detect_and_translate  # noqa: E402
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
    "STD 업체명(Eng)", "업체명 언어", "도로명주소", "지번주소",
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


def _strip_road_paren(road_addr: str) -> str:
    """행안부 roadAddr 끝의 괄호 참고항목(예: ' (천호동, 하이브2)')을 제거한다.

    이 괄호는 법정동·건물명 참고정보로, STD 주소에는 순수 도로명만 남긴다(컬럼
    '도로명주소'에는 행안부 원본을 그대로 보존).
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", road_addr or "").strip()


# language=ko 주소 앞의 국가명 접두. 붙어 있으면 행안부 검색이 깨지므로 제거한다
# (실측: '대한민국 경기도…'는 매칭 실패, '경기도…'는 도로명 변환 성공).
_COUNTRY_PREFIX_RE = re.compile(r"^(대한민국|한국)\s+")
# 지번부 시작 토큰(동/읍/면/리/가/로/길). 여기부터 검색어로 추출한다.
_ADDR_START_RE = re.compile(r".*(동|읍|면|리|가|로|길)$")
# 도로명 토큰(로/길). 번지 전까지 이어붙인다.
_ROAD_RE = re.compile(r".*(로|길)$")
# 번지/건물번호 토큰(숫자[-숫자][번지]).
_NUM_RE = re.compile(r"\d+(-\d+)?(번지)?$")


def _strip_country_prefix(addr: str) -> str:
    """ko 주소 선두의 '대한민국/한국 ' 접두를 제거(행안부 검색어 정리)."""
    return _COUNTRY_PREFIX_RE.sub("", (addr or "").strip())


def _split_ko_address(ko_addr: str):
    """ko 재조회 주소를 (시도, [시군구…], 행안부 검색어)로 분해.

    예) '대한민국 인천광역시 서구 가좌동 548-1' → ('인천광역시', ['서구'], '가좌동 548-1').
    행안부 검색 API는 (a) 시도·시군구를 앞에 붙이거나 (b) 번지 뒤 건물명·층·호·국가
    코드 꼬리가 붙으면 매칭이 깨지므로(실측), 동/도로명~번지까지만 검색어로 추려내고
    시도·시군구는 후보 교차검증에 쓴다.
    """
    s = _strip_country_prefix(ko_addr)
    toks = s.split()
    if not toks:
        return "", [], ""
    sido = toks[0]
    sgg, i = [], 1
    # 동/도로명이 나오기 전까지 시/군/구 토큰을 시군구로 수집
    while i < len(toks) and not _ADDR_START_RE.match(toks[i]) \
            and (toks[i].endswith("시") or toks[i].endswith("군") or toks[i].endswith("구")):
        sgg.append(toks[i])
        i += 1
    # 동/도로명 시작 토큰부터, 번지(숫자) 하나까지만 검색어로 추출(꼬리 상세는 버림)
    search, started = [], False
    for t in toks[i:]:
        if not started:
            if _ADDR_START_RE.match(t):
                started = True
                search.append(t)
            continue
        if _NUM_RE.match(t):
            search.append(t)
            break
        if _ROAD_RE.match(t):
            search.append(t)
            continue
        break
    return sido, sgg, " ".join(search)


def _pick_by_region(candidates, sido, sgg):
    """후보 중 시도 일치(필수) + 시군구 일치(선호) 하나를 고른다.

    시군구 명칭이 ko 주소와 행안부에서 다를 수 있어(예: 서구→서해구) 시도만 필수로
    보고, 시군구까지 일치하는 후보가 있으면 우선 채택한다. 시도 일치가 없으면 None.
    """
    same_sido = [c for c in candidates if c.get("si_nm") == sido]
    if not same_sido:
        return None
    sgg_key = " ".join(sgg)
    for c in same_sido:
        # 행안부 sgg_nm은 '수원시 영통구'처럼 합쳐진 형태 → 부분 포함으로 비교
        if sgg_key and (sgg_key in c.get("sgg_nm", "") or c.get("sgg_nm", "") in sgg_key):
            return c
    return same_sido[0]


def _unify_kr_road(result, adapter, juso_client):
    """KR 레코드의 최종 STD 주소를 한글 도로명으로 통일한다.

    실재검증 결과의 STD 주소는 Google 응답 그대로라 영어/혼재 표기(예:
    '…Yeongtong-gu, 원천동 471')이거나 지번일 수 있다. place_id(없으면 좌표)로
    language=ko 재조회해 순수 한글 주소를 얻고, 동+지번만 행안부로 조회해 시도·시군구
    교차검증으로 올바른 도로명을 채택한다(동명이동 오매칭 차단). 변환 성공 시 (도로명주소,
    지번주소)를, 실패/대상아님이면 ("", "")를 반환한다(STD 주소는 그대로 둠).
    """
    coord = (result.std_lat, result.std_lon) if result.std_lat is not None else None
    ko_addr = adapter.address_ko(place_id=result.place_id, coord=coord)
    if not ko_addr:
        return "", ""
    sido, sgg, keyword = _split_ko_address(ko_addr)
    if not keyword:
        return "", ""
    cands = juso_client.resolve_candidates(keyword)
    pick = _pick_by_region(cands, sido, sgg)
    if not (pick and pick.get("road_addr")):
        return "", ""
    result.std_address = _strip_road_paren(pick["road_addr"])
    return pick["road_addr"], pick.get("jibun_addr", "")


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

    juso_client가 주어진 KR 레코드는, 실재검증으로 STD 주소가 확정된 뒤 행안부로
    도로명 통일 후처리를 수행한다(Google 응답이 영어/혼재·지번으로 나와도 최종 STD
    주소를 한글 도로명으로 맞춘다). 원본 주소(Eng/Local)는 out에 그대로 보존된다.
    """
    disp = (row.get("업체") or "").strip()
    company_std = standardize_company(disp)
    # 언어 판정 + 영문 표기(비영어 업체명 대상). 유사 검색의 언어별 비교에 사용.
    translated = detect_and_translate(company_std)
    addr_en = (row.get("주소(Eng)") or "").strip()
    addr_local = (row.get("주소(Local)") or "").strip()
    coord = _parse_coord(row)
    lang = lang_for_country(row.get("국가/지역"))

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

    # 행안부 도로명 통일 후처리(KR·STD 주소 보유 시). STD 주소를 한글 도로명으로 교체하고
    # 도로명/지번 컬럼을 채운다. 대상 아님/실패면 ("", "")로 STD 주소는 그대로 둔다.
    juso_road = juso_jibun = ""
    if juso_client and _is_kr(row.get("국가/지역")) and result.std_address:
        juso_road, juso_jibun = _unify_kr_road(result, adapter, juso_client)

    out = dict(row)
    out["STD 업체명"] = company_std
    out["STD 업체명(Eng)"] = translated["name_eng"]
    out["업체명 언어"] = translated["lang"]
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
    # 행안부 도로명 통일로 확보한 한글 도로명/지번(변환 성공 시에만 채움).
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
