# -*- coding: utf-8 -*-
"""고객사 TF 테스트 데이터(xlsx) 표준화·실재검증 실행 엔트리.

data/STD_VLD_260926_site_master_TF_2.xlsx의 TF_raw 시트를 읽어, 컬럼명을 기존
STD_VLD_260917 파이프라인이 기대하는 표준 컬럼명으로 매핑한 뒤 process_row에
그대로 위임한다. Case 분기(A/B/C/X)는 pick_case가 필드 존재로 자동 결정한다.
새 데이터셋은 위도/경도 컬럼을 포함하며, 이는 파이프라인 표준 컬럼명과 동일해
별도 매핑 없이 통과하고 좌표가 있는 행은 Case C(주소+좌표)로 처리된다.

사용:
  python scripts/STD_VLD_260922_run_verification_TF.py --mode real   # GOOGLE_MAPS_API_KEY 필요
  python scripts/STD_VLD_260922_run_verification_TF.py --mode mock [--in ...] [--out ...] [--sheet ...]
"""

import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

from STD_VLD_260917_maps_adapter import make_adapter  # noqa: E402
from STD_VLD_260917_run_verification import EXTRA_COLUMNS, process_row  # noqa: E402

IN_PATH = os.path.join(ROOT, "data", "STD_VLD_260926_site_master_TF_2.xlsx")
OUT_PATH = os.path.join(ROOT, "data", "STD_VLD_260926_site_master_TF_2_std.xlsx")
IN_SHEET = "TF_raw"
OUT_SHEET = "TF_std"

# TF_raw 원본 컬럼(순서 유지) — 출력 앞부분에 그대로 보존한다.
SOURCE_COLUMNS = ["업체명 (Eng)", "국가/지역", "행정구역", "주소", "위도", "경도"]

# TF_raw 컬럼 → 기존 파이프라인 표준 컬럼명. 위도/경도는 파이프라인 표준 컬럼명과
# 동일하므로 매핑 불필요(그대로 통과 → _parse_coord가 인식).
COLUMN_MAP = {
    "업체명 (Eng)": "업체",
    "주소": "주소(Eng)",  # 단일 주소를 Eng 슬롯에 매핑 (→ 좌표 있으면 Case C)
}

# 최종 출력 컬럼: 원본 4컬럼 + STD 컬럼 + 파이프라인 산출물(EXTRA). TF에 없는
# 기존 CSV 스키마 컬럼(No./Status/위도/경도 등)은 제외한다.
FINAL_COLUMNS = SOURCE_COLUMNS + ["STD 업체명", "STD 주소"] + list(EXTRA_COLUMNS)


def _map_row(src: dict) -> dict:
    """TF_raw 행 dict를 표준 컬럼명 dict로 변환. 매핑에 없는 컬럼은 보존."""
    mapped = {}
    for key, val in src.items():
        std_key = COLUMN_MAP.get(key, key)
        mapped[std_key] = val
    return mapped


def _read_rows(in_path: str, sheet: str) -> list:
    df = pd.read_excel(in_path, sheet_name=sheet, dtype=str)
    df = df.where(pd.notna(df), "")  # NaN → 빈 문자열
    return df.to_dict(orient="records")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(os.path.join(ROOT, ".env"))
    parser = argparse.ArgumentParser(description="TF 테스트 데이터 표준화·실재검증 실행")
    parser.add_argument("--mode", choices=["mock", "real"], default=None,
                        help="어댑터 모드(기본: 환경변수 MAPS_ADAPTER_MODE 또는 real)")
    parser.add_argument("--in", dest="in_path", default=IN_PATH)
    parser.add_argument("--out", dest="out_path", default=OUT_PATH)
    parser.add_argument("--sheet", dest="in_sheet", default=IN_SHEET)
    parser.add_argument("--limit", type=int, default=None, help="처리 행 수 제한")
    args = parser.parse_args(argv)

    mode = args.mode or os.getenv("MAPS_ADAPTER_MODE", "real")
    adapter = make_adapter(mode, api_key=os.getenv("GOOGLE_MAPS_API_KEY"))

    src_rows = _read_rows(args.in_path, args.in_sheet)
    if args.limit:
        src_rows = src_rows[:args.limit]

    out_rows = []
    for src in src_rows:
        out = process_row(_map_row(src), adapter)
        # process_row는 매핑된 row를 복사해 반환하므로 원본 표시 컬럼을 다시 채운다.
        for col in SOURCE_COLUMNS:
            out[col] = src.get(col, "")
        out_rows.append(out)

    out_df = pd.DataFrame(out_rows).reindex(columns=FINAL_COLUMNS)
    with pd.ExcelWriter(args.out_path, engine="openpyxl") as writer:
        out_df.to_excel(writer, sheet_name=OUT_SHEET, index=False)

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
