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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

import STD_VLD_260917_geo_common as gc  # noqa: E402
import STD_VLD_260917_verify_pipeline as vp  # noqa: E402
from STD_VLD_260917_maps_adapter import make_adapter  # noqa: E402
from STD_VLD_260917_std_company import standardize_company  # noqa: E402

IN_PATH = os.path.join(ROOT, "data", "STD_VLD_260917_site_master_light.csv")
OUT_PATH = os.path.join(ROOT, "data", "STD_VLD_260917_site_master_light_std.csv")

# 원본 컬럼(순서 유지)
BASE_COLUMNS = [
    "No.", "Status", "Site Code", "Site 유형", "업체", "항구/공항 코드",
    "기업식별 코드", "Duns No.", "국가/지역", "행정구역", "주소(Eng)", "주소(Local)",
    "위도", "경도", "관련 협력사 코드", "수정일", "Site 출처", "STD 주소", "STD 업체명",
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


def process_row(row, adapter) -> dict:
    """한 행을 표준화·검증하여 출력 행 dict를 반환."""
    disp = (row.get("업체") or "").strip()
    company_std = standardize_company(disp)
    addr_en = (row.get("주소(Eng)") or "").strip()
    addr_local = (row.get("주소(Local)") or "").strip()
    coord = _parse_coord(row)
    case = pick_case(row)

    if not company_std:
        result = gc.make_result(gc.FAILED_ALL_METHODS, note="업체명이 비어 있어 검증 불가")
    elif case == "C":
        result = vp.verify_case_C(company_std, addr_en, addr_local, coord, adapter,
                                  company_disp=disp)
    elif case == "A":
        result = vp.verify_case_A(company_std, addr_en or addr_local, adapter,
                                  company_disp=disp)
    elif case == "B":
        result = vp.verify_case_B(company_std, coord, adapter, company_disp=disp)
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

    with open(args.in_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]

    out_rows = [process_row(r, adapter) for r in rows]

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
