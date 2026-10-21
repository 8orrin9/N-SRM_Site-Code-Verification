# -*- coding: utf-8 -*-
"""대만 공식 행정구역 목록(NLSC 코드서비스, 戶政 기준) 확보.

확인된 엔드포인트(이번 작업에서 직접 호출해 검증함):
    縣市 목록: https://api.nlsc.gov.tw/other/ListCounty
        → countycode(알파벳 1자, ListTown1 경로 파라미터로 씀), countyname,
          countycode01(5자리 숫자 코드). 22개 확인됨(작업지시서와 일치).
    鄉鎮市區 목록: https://api.nlsc.gov.tw/other/ListTown1/{countycode}
        → towncode(8자리), towncode01, townname. 22개 縣市 합산 368개 확인됨
          (작업지시서 "390건" = 縣市 22 + 鄉鎮市區 368, 정확히 일치).

작업지시서 5장: 대만은 기대 타입 없이 Google 반환 타입을 실측(discovery)하므로
expected_type은 두 레벨 모두 None.
"""

import xml.etree.ElementTree as ET

import requests

LIST_COUNTY_URL = "https://api.nlsc.gov.tw/other/ListCounty"
LIST_TOWN_URL = "https://api.nlsc.gov.tw/other/ListTown1/{county_code}"

LEVEL_COUNTY = "county"
LEVEL_TOWNSHIP = "township"


def fetch_counties(*, session=None) -> list[dict]:
    """縣市 22개 목록을 받아 official 행으로 변환한다.

    Args:
        session (requests.Session, optional): 재사용할 세션.

    Returns:
        list: {country, level, code, name, parent_code, expected_type} 행 목록.
    """
    s = session or requests.Session()
    resp = s.get(LIST_COUNTY_URL, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    rows = []
    for item in root.findall("countyItem"):
        rows.append({
            "country": "TW", "level": LEVEL_COUNTY,
            "code": item.findtext("countycode"),
            "name": item.findtext("countyname"),
            "parent_code": None,
            "expected_type": None,
        })
    return rows


def fetch_townships(county_code: str, *, session=None) -> list[dict]:
    """특정 縣市의 鄉鎮市區 목록을 받아 official 행으로 변환한다.

    Args:
        county_code (str): `fetch_counties`가 반환한 countycode(알파벳 1자).
        session (requests.Session, optional): 재사용할 세션.

    Returns:
        list: {country, level, code, name, parent_code, expected_type} 행 목록.
    """
    s = session or requests.Session()
    resp = s.get(LIST_TOWN_URL.format(county_code=county_code), timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    rows = []
    for item in root.findall("townItem"):
        rows.append({
            "country": "TW", "level": LEVEL_TOWNSHIP,
            "code": item.findtext("towncode"),
            "name": item.findtext("townname"),
            "parent_code": county_code,
            "expected_type": None,
        })
    return rows


def build_tw_official(*, session=None) -> list[dict]:
    """縣市 전체 + 각 縣市의 鄉鎮市區 전체를 모아 TW official 행 리스트를 만든다.

    Args:
        session (requests.Session, optional): 재사용할 세션(없으면 새로 생성해 공유).

    Returns:
        list: county 22행 + township 368행(총 390행, 확인됨).
    """
    s = session or requests.Session()
    counties = fetch_counties(session=s)
    rows = list(counties)
    for c in counties:
        rows.extend(fetch_townships(c["code"], session=s))
    return rows
