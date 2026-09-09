# -*- coding: utf-8 -*-
"""End-Image 목업용 데이터 추출 스크립트.

site_master.csv에서 near-duplicate 관계를 찾아 유사도 3개 대역으로 분류한
JSON(mockup/mock_data.json)을 생성한다. HTML 목업(site_code_verification.html)에
임베드할 용도이며, 유사도 값은 시연을 위해 대역별로 결정적으로 산출한다.

- 신규 채번(newAssign): 유사도 낮음 → 유사 Site 없음(신규 채번 대상)
- Code 연결(codeLink): 유사도 중간 → 같은 업체 다른 지점 등
- Site Code 확정(confirm): 유사도 높음 → 동일 지점·동일 업체 near-duplicate
"""
import csv
import json
import os
import random
import sys
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "site_master.csv")
OUT_PATH = os.path.join(ROOT, "mockup", "mock_data.json")

sys.path.insert(0, HERE)
from generate_site_master import (  # noqa: E402
    COMPANY_POOL, COMPANY_SUFFIX, PLACES, clean_address,
)

rng = random.Random(20260908)

# 좌표(6자리) → (place, street) 역인덱스. 표준(정제) 주소 파생용.
COORD2STREET = {}
for _place in PLACES:
    for _street in _place["streets"]:
        COORD2STREET[(f"{_street['lat']:.6f}", f"{_street['lon']:.6f}")] = (_place, _street)

# 접미사(불용어) 목록 — 긴 것부터 제거
ALL_SUFFIX = sorted({s for v in COMPANY_SUFFIX.values() for s in v}, key=len, reverse=True)

# 업체 base_en 식별용 변형 사전 (영문/로컬 표기 → base_en)
BASES = []
for _lang, pairs in COMPANY_POOL.items():
    for en, local in pairs:
        BASES.append((en, en.lower()))
        if local.lower() != en.lower():
            BASES.append((en, local.lower()))


def normalize(name):
    n = name.strip()
    for suf in ALL_SUFFIX:
        n = n.replace(suf, "")
    return n.strip().lower()


def match_base(name):
    """표기(오타·불용어·로컬)로부터 정규 업체명(base_en) 추정."""
    n = normalize(name)
    best, best_r = None, 0.0
    for en, variant in BASES:
        r = SequenceMatcher(None, n, variant).ratio()
        if r > best_r:
            best_r, best = r, en
    return best if best_r >= 0.6 else None


def std_of(r):
    """행의 정밀 좌표로 표준(정제) 주소·업체명·좌표를 파생한다.

    반환: dict(addrStd, companyStd, latStd, lonStd, noisy, latDisp, lonDisp)
    - addrStd : PLACES street 역추적 + clean_address 로 만든 표준 영문 주소.
    - companyStd : match_base 로 추정한 정규 업체명(없으면 원본 유지).
    - latStd/lonStd : 정밀 6자리 정답 좌표.
    - noisy : 원본 표기가 표준과 다른(=표준화 여지가 있는) 행인지.
    - latDisp/lonDisp : 화면 표시용 좌표. 노이즈 행은 저정밀(2자리)로 낮춰
                        Geocoding 교정 효과가 드러나게 한다.
    """
    key = (r["위도"], r["경도"])
    place, street = COORD2STREET.get(key, (None, None))
    if place:
        addr_std, _ = clean_address(place, street)
    else:
        addr_std = r["주소(Eng)"]
    company_std = r.get("_base") or r["업체"]
    lat_std, lon_std = r["위도"], r["경도"]
    noisy = (r["업체"] != company_std) or (r["주소(Eng)"] != addr_std)
    lat_disp = f"{float(r['위도']):.2f}" if noisy else lat_std
    lon_disp = f"{float(r['경도']):.2f}" if noisy else lon_std
    return dict(addrStd=addr_std, companyStd=company_std, latStd=lat_std,
                lonStd=lon_std, noisy=noisy, latDisp=lat_disp, lonDisp=lon_disp)


def std_filled(r):
    """초기 표준화 완료 여부(결정적). 이미 확정된 Site 또는 No.가 3의 배수인
    행은 표준화가 끝난 것으로 미리 채워 Before/After 를 함께 보여준다."""
    return r["Status"] == "등록확정" or int(r["No."]) % 3 == 0


def ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def sims(reg, rec, band):
    """등록 시도 행(reg)과 추천 행(rec) 사이의 항목별/평균 유사도(%)."""
    raw_name = ratio(normalize(reg["업체"]), normalize(rec["업체"]))
    raw_addr = ratio(reg["주소(Eng)"], rec["주소(Eng)"])
    if band == "high":
        name = 92 + raw_name * 7
        addr = 90 + raw_addr * 9
        corp = 65 + rng.random() * 25
        duns = 65 + rng.random() * 25
    elif band == "mid":
        name = 84 + raw_name * 11
        addr = 45 + raw_addr * 25
        corp = 30 + rng.random() * 30
        duns = 30 + rng.random() * 30
    else:  # low
        name = 20 + raw_name * 30
        addr = 38 + raw_addr * 27
        corp = 15 + rng.random() * 25
        duns = 15 + rng.random() * 25
    avg = 0.5 * name + 0.4 * addr + 0.05 * corp + 0.05 * duns

    def f(x):
        return round(min(x, 100.0), 2)

    return dict(nameSim=f(name), addrSim=f(addr), corpSim=f(corp),
                dunsSim=f(duns), avg=f(avg))


def rec_obj(reg, rec, band):
    s = sims(reg, rec, band)
    std = std_of(reg)
    return {
        "no": int(reg["No."]),
        "status": reg["Status"],
        "sub": {
            "companyEn": reg["업체"],
            "corpId": reg["기업식별 코드"],
            "duns": reg["Duns No."],
            "country": reg["국가/지역"],
            "admin": reg["행정구역"],
            "addr": reg["주소(Eng)"],
            "lat": std["latDisp"], "lon": std["lonDisp"],
            "partner": reg["관련 협력사 코드"],
            "source": reg["Site 출처"],
            "companyStd": std["companyStd"], "addrStd": std["addrStd"],
            "latStd": std["latStd"], "lonStd": std["lonStd"],
            "stdFilled": std_filled(reg),
        },
        "rec": {
            "siteCode": rec["Site Code"],
            "avg": s["avg"],
            "company": rec["업체"],
            "nameSim": s["nameSim"],
            "corpId": rec["기업식별 코드"],
            "corpSim": s["corpSim"],
            "duns": rec["Duns No."],
            "dunsSim": s["dunsSim"],
            "country": rec["국가/지역"],
            "admin": rec["행정구역"],
            "addr": rec["주소(Eng)"],
            "addrSim": s["addrSim"],
            "lat": rec["위도"], "lon": rec["경도"],
        },
        "modified": reg["수정일"],
    }


def hist_obj(r):
    """검증이력 행: 확정된 Site의 하위 공급망 정보(자체 Site Code 포함)."""
    std = std_of(r)
    return {
        "no": int(r["No."]),
        "status": r["Status"],
        "sub": {
            "siteCode": r["Site Code"],
            "companyEn": r["업체"],
            "corpId": r["기업식별 코드"],
            "duns": r["Duns No."],
            "country": r["국가/지역"],
            "admin": r["행정구역"],
            "addr": r["주소(Eng)"],
            "lat": std["latDisp"], "lon": std["lonDisp"],
            "partner": r["관련 협력사 코드"],
            "source": r["Site 출처"],
            "companyStd": std["companyStd"], "addrStd": std["addrStd"],
            "latStd": std["latStd"], "lonStd": std["lonStd"],
            "stdFilled": std_filled(r),
        },
        "modified": r["수정일"],
    }


def master_obj(r):
    """Site Registration 관리 화면용: Site 마스터 원본 전체 필드."""
    std = std_of(r)
    return {
        "no": int(r["No."]),
        "status": r["Status"],
        "siteCode": r["Site Code"],
        "siteType": r["Site 유형"],
        "company": r["업체"],
        "portCode": r["항구/공항 코드"],
        "corpId": r["기업식별 코드"],
        "duns": r["Duns No."],
        "country": r["국가/지역"],
        "admin": r["행정구역"],
        "addrEn": r["주소(Eng)"],
        "addrLocal": r["주소(Local)"],
        "lat": std["latDisp"], "lon": std["lonDisp"],
        "modified": r["수정일"],
        "source": r["Site 출처"],
        "companyStd": std["companyStd"], "addrStd": std["addrStd"],
        "latStd": std["latStd"], "lonStd": std["lonStd"],
        "stdFilled": std_filled(r),
    }


def load_rows():
    rows = []
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r["_base"] = match_base(r["업체"])
            r["_coord"] = (r["위도"], r["경도"])
            rows.append(r)
    return rows


def build():
    rows = load_rows()
    used = set()

    # high: 동일 base + 동일 좌표 (진짜 near-duplicate)
    by_bc = {}
    for r in rows:
        if r["_base"]:
            by_bc.setdefault((r["_base"], r["_coord"]), []).append(r)
    high = []
    for _key, grp in sorted(by_bc.items(), key=lambda kv: str(kv[0])):
        if len(grp) >= 2:
            reg, rec = grp[0], grp[1]
            high.append(rec_obj(reg, rec, "high"))
            used.add(reg["No."])

    # mid: 동일 base, 다른 좌표 (같은 업체 다른 지점)
    by_b = {}
    for r in rows:
        if r["_base"]:
            by_b.setdefault(r["_base"], {})
            by_b[r["_base"]].setdefault(r["_coord"], r)
    mid = []
    for _base, coords in sorted(by_b.items()):
        cs = list(coords.values())
        if len(cs) >= 2:
            reg, rec = cs[0], cs[1]
            if reg["No."] in used and len(cs) >= 2:
                reg, rec = cs[1], cs[0]
            mid.append(rec_obj(reg, rec, "mid"))
            used.add(reg["No."])

    # low: 미사용 행 → 같은 행정구역의 다른 업체를 약한 추천으로
    by_admin = {}
    for r in rows:
        by_admin.setdefault(r["행정구역"], []).append(r)
    low = []
    for r in rows:
        if r["No."] in used:
            continue
        cand = [x for x in by_admin.get(r["행정구역"], [])
                if x["_base"] != r["_base"] and x["No."] != r["No."]]
        if not cand:
            cand = [x for x in rows
                    if x["국가/지역"] == r["국가/지역"] and x["No."] != r["No."]]
        if not cand:
            continue
        low.append(rec_obj(r, cand[0], "low"))
        used.add(r["No."])
        if len(low) >= 14:
            break

    # history: 검증 완료(등록확정) Site 이력 — 자체 Site Code 포함, 추천 정보 없음
    history = [hist_obj(r) for r in rows if r["Status"] == "등록확정"][:14]

    # master: Site Registration 관리 화면 — 마스터 100건 전체(No. 오름차순)
    master = [master_obj(r) for r in sorted(rows, key=lambda x: int(x["No."]))]

    return {
        "newAssign": low[:14],
        "codeLink": mid[:14],
        "confirm": high[:14],
        "history": history,
        "master": master,
    }


if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"생성 완료: {OUT_PATH}")
    for k, v in data.items():
        print(f"- {k}: {len(v)}건")
