# -*- coding: utf-8 -*-
"""일본 공식 행정구역 목록(총무성 全国地方公共団体コード) 확보.

출처: https://www.soumu.go.jp/denshijiti/code.html
    "都道府県コード及び市区町村コード"(メイン表) — URL은 개정 시 바뀔 수 있어
    `fetch_jp_excel`이 매번 그 페이지에서 최신 링크를 다시 찾는다.

파일 구조(확인됨, 기준일 R6.1.1 = 令和6年1月1日 = 2024-01-01):
    시트 "R6.1.1現在の団体": 団体コード, 都道府県名(漢字), 市区町村名(漢字, 都道府県
        자체 행은 공백), 都道府県名(カナ), 市区町村名(カナ). 47개 都道府県 + 1747개
        市区町村(東京23特別区 포함, 정령지정도시도 "市" 레벨 행 1개로 포함).
    시트 "R6.1.1政令指定都市": 정령지정도시 20개 각각, 그 시 자체 행(시트1과 동일
        코드로 중복) 뒤에 行政区 행들이 이어진다. 区 행의 市区町村名은 "札幌市中央区"
        처럼 시명+구명이 붙은 전체 표기라, 구 자체 명칭은 선행 시명을 떼어내 얻는다.
        시트 전체 191행 중 구 행 171개(시 자체 중복 행 20개는 제외) — 작업지시서의
        "175개"는 추정치였고, 실제 공식 데이터는 171개.

제외(작업지시서 2장): 町字・丁目 이하, 一部事務組合・広域連合 코드(다른 시트/파일).
"""

import io
import re

import requests

CODE_PAGE_URL = "https://www.soumu.go.jp/denshijiti/code.html"

LEVEL_PREF = "pref"
LEVEL_MUNI = "muni"
LEVEL_WARD = "ward"

EXPECTED_TYPE = {
    LEVEL_PREF: "administrative_area_level_1",
    LEVEL_MUNI: "locality",
    LEVEL_WARD: "sublocality_level_1",
}


def _reiwa_to_iso(sheet_name: str) -> str | None:
    """시트명의 "R6.1.1" 같은 令和 연호 표기를 ISO 날짜로 변환.

    Args:
        sheet_name (str): 예) "R6.1.1現在の団体".

    Returns:
        str | None: "2024-01-01" 형식. 패턴이 없으면 None.
    """
    m = re.match(r"R(\d+)\.(\d+)\.(\d+)", sheet_name)
    if not m:
        return None
    reiwa_year, month, day = (int(x) for x in m.groups())
    year = 2018 + reiwa_year  # 令和1年 = 2019
    return f"{year:04d}-{month:02d}-{day:02d}"


def fetch_jp_excel(*, session=None) -> tuple[bytes, str]:
    """총무성 코드 페이지에서 "都道府県コード及び市区町村コード" Excel 링크를 찾아 받는다.

    페이지의 여러 Excel 링크 중, "都道府県コード及び市区町村コード"(메인 표) 바로
    아래의 링크만 쓴다 — 改正一覧表(변경 이력)·一部事務組合等コード(제외 대상)는
    건너뛴다.

    Args:
        session (requests.Session, optional): 재사용할 세션.

    Returns:
        tuple: (엑셀 바이트, 다운로드 URL).
    """
    s = session or requests.Session()
    page = s.get(CODE_PAGE_URL, timeout=20)
    page.raise_for_status()
    html = page.content.decode("shift_jis", errors="replace")

    # "都道府県コード及び市区町村コード" 표제 뒤, 改正一覧表/一部事務組合等 표제
    # 전까지의 구간에서 첫 .xlsx 링크를 취한다.
    start = html.find("都道府県コード及び市区町村コード")
    if start == -1:
        raise RuntimeError("코드 페이지에서 '都道府県コード及び市区町村コード' 표제를 찾지 못함")
    m = re.search(r'href="([^"]+\.xlsx)"', html[start:])
    if not m:
        raise RuntimeError("메인 표 구간에서 .xlsx 링크를 찾지 못함")
    url = m.group(1)
    if url.startswith("/"):
        url = "https://www.soumu.go.jp" + url

    resp = s.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content, url


def parse_jp_excel(xlsx_bytes: bytes) -> tuple[list[dict], str | None]:
    """다운로드한 Excel 바이트를 official 행 리스트로 변환한다.

    Args:
        xlsx_bytes (bytes): `fetch_jp_excel`이 받은 엑셀 파일 바이트.

    Returns:
        tuple: (official 행 리스트, 기준일 ISO 문자열 또는 None).
            각 행: {country, level, code, name, kana, parent_code, expected_type}.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    main_sheet_name = next(n for n in wb.sheetnames if "政令指定都市" not in n)
    ward_sheet_name = next(n for n in wb.sheetnames if "政令指定都市" in n)
    as_of = _reiwa_to_iso(main_sheet_name)

    rows: list[dict] = []
    pref_code_by_name: dict[str, str] = {}

    # 1차: 都道府県 행 먼저 전부 모아 이름→코드 조회 테이블을 만든다(市区町村 행의
    # parent_code를 뒤에서 바로 채우기 위함. 시트 내 등장 순서는 都道府県별로
    # 묶여 있지만, 조회 테이블은 순서에 의존하지 않기 위해 선행 수집한다).
    # 団体コード는 항상 6자리 문자열이어야 하는데, 엑셀 셀 서식이 일부 행만
    # 숫자로 돼 있어 openpyxl이 int로 읽어오는 경우가 있다(확인됨 — 政令指定都市
    # 시트의 浜松市·熊本市 관련 9행). 문자열/정수가 섞이면 이후 코드→행 조회
    # 테이블의 키 타입이 불일치해 조회가 조용히 실패하므로, 읽는 즉시 통일한다.
    def _norm_code(code):
        return str(code).zfill(6)

    main_rows = [r for r in wb[main_sheet_name].iter_rows(min_row=2, values_only=True) if r[0]]
    for code, pref_kanji, muni_kanji, pref_kana, muni_kana, *_ in main_rows:
        if not muni_kanji:
            pref_code_by_name[pref_kanji] = _norm_code(code)

    for code, pref_kanji, muni_kanji, pref_kana, muni_kana, *_ in main_rows:
        code = _norm_code(code)
        if not muni_kanji:
            rows.append({"country": "JP", "level": LEVEL_PREF, "code": code,
                         "name": pref_kanji, "kana": pref_kana, "parent_code": None,
                         "expected_type": EXPECTED_TYPE[LEVEL_PREF]})
        else:
            rows.append({"country": "JP", "level": LEVEL_MUNI, "code": code,
                         "name": muni_kanji, "kana": muni_kana,
                         "parent_code": pref_code_by_name[pref_kanji],
                         "expected_type": EXPECTED_TYPE[LEVEL_MUNI]})

    # 2차: 政令指定都市 시트 — 시 자체 중복 행은 건너뛰고(이미 위에서 muni로 추가됨),
    # 区 행만 추가한다. 블록 순서(시 행 → 그 시의 구 행들)에 의존해 현재 시를
    # 추적하면서 区 명칭에서 시명 접두사를 떼어낸다.
    ward_rows = [r for r in wb[ward_sheet_name].iter_rows(min_row=2, values_only=True) if r[0]]
    current_city_code = None
    current_city_name = None
    for code, pref_kanji, name_kanji, pref_kana, name_kana, *_ in ward_rows:
        code = _norm_code(code)
        if not name_kanji.endswith("区"):
            current_city_code, current_city_name = code, name_kanji
            continue
        ward_name = name_kanji[len(current_city_name):] if name_kanji.startswith(current_city_name) else name_kanji
        rows.append({"country": "JP", "level": LEVEL_WARD, "code": code,
                     "name": ward_name, "kana": name_kana,
                     "parent_code": current_city_code,
                     "expected_type": EXPECTED_TYPE[LEVEL_WARD]})

    return rows, as_of
