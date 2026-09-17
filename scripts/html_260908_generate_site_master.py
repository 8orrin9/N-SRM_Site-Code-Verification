# -*- coding: utf-8 -*-
"""
Site 마스터 데이터 생성 스크립트 (N-SRM Site 코드 채번 고도화 PoC - 데이터 준비)

산출물: data/site_master.csv (100건, UTF-8-BOM)

설계 원칙
- 위경도는 참조 풀에 정의된 '실제 지점(도로명 주소)의 실제 좌표'를 그대로 사용한다.
  좌표는 도시 단위가 아니라 '도로명 주소 단위'로 부여되어, 각 행의 주소와 정확히 align 된다.
  (지터/무작위 조합 금지)
- 노이즈(불완전 데이터)는 '주소/업체명 문자열 표기'에만 주입하며, 좌표 값 자체는 정답을 유지한다.
  → Task 1 Geocoding/LLM 이 흔들린 표기를 정답으로 표준화하는 시연 구도.
- 100건 중 일부를 의도적 near-duplicate(동일 Site, 다른 표기)로 구성한다. (Task 2/3 정답)
  near-duplicate 는 동일 지점(동일 도로/좌표)을 공유하되 업체명/주소 표기·Site Code·출처만 다르게 한다.
"""

import csv
import os

import numpy as np

SEED = 20260908
rng = np.random.default_rng(SEED)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_PATH = os.path.join(OUT_DIR, "site_master.csv")

N_ROWS = 100
NOISE_RATE = 0.60          # 업체/주소 불완전 비율
N_DUPLICATE = 9            # 의도적 near-duplicate 행 수

COLUMNS = [
    "No.", "Status", "Site Code", "Site 유형", "업체", "항구/공항 코드",
    "기업식별 코드", "Duns No.", "국가/지역", "행정구역", "주소(Eng)", "주소(Local)",
    "위도", "경도", "관련 협력사 코드", "수정일", "Site 출처", "STD 주소", "STD 업체명",
]

# ---------------------------------------------------------------------------
# 1) 참조 풀: 국가별 실제 장소. 각 도로명 주소(street)마다 실제 좌표를 개별 부여.
#    place = {country, admin, city_en, city_local, lang, streets: [street, ...]}
#    street = {en, local, postal, lat, lon}  ← 좌표는 이 지점의 실제 값
# ---------------------------------------------------------------------------
PLACES = [
    # ---- 한국 ----
    {
        "country": "KR: 한국", "admin": "13: Seoul",
        "city_en": "Seoul", "city_local": "서울특별시", "lang": "ko",
        "streets": [
            {"en": "14 Sejong-daero, Jung-gu", "local": "중구 세종대로 14",
             "postal": "04524", "lat": 37.566295, "lon": 126.976889},
            {"en": "26 Euljiro, Jung-gu", "local": "중구 을지로 26",
             "postal": "04539", "lat": 37.566010, "lon": 126.982877},
            {"en": "128 Yeoui-daero, Yeongdeungpo-gu", "local": "영등포구 여의대로 128",
             "postal": "07320", "lat": 37.525651, "lon": 126.924191},
        ],
    },
    {
        "country": "KR: 한국", "admin": "09: Gyeonggi-do",
        "city_en": "Suwon", "city_local": "경기도 수원시", "lang": "ko",
        "streets": [
            {"en": "1 Samsung-ro, Yeongtong-gu", "local": "영통구 삼성로 1",
             "postal": "16677", "lat": 37.257356, "lon": 127.052550},
            {"en": "152 Gwanggyo-ro, Yeongtong-gu", "local": "영통구 광교로 152",
             "postal": "16229", "lat": 37.287280, "lon": 127.046370},
        ],
    },
    {
        "country": "KR: 한국", "admin": "12: Busan",
        "city_en": "Busan", "city_local": "부산광역시", "lang": "ko",
        "streets": [
            {"en": "120 Jungang-daero, Jung-gu", "local": "중구 중앙대로 120",
             "postal": "48943", "lat": 35.106321, "lon": 129.032630},
            {"en": "55 Jungang-daero, Dong-gu", "local": "동구 중앙대로 55",
             "postal": "48821", "lat": 35.115034, "lon": 129.041624},
        ],
    },
    # ---- 중국 ----
    {
        "country": "CN: 중국", "admin": "020: Shanghai",
        "city_en": "Shanghai", "city_local": "上海市", "lang": "zh",
        "streets": [
            {"en": "1000 Century Avenue, Pudong New District", "local": "浦东新区世纪大道1000号",
             "postal": "200120", "lat": 31.233705, "lon": 121.524621},
            {"en": "500 Nanjing Road, Huangpu District", "local": "黄浦区南京路500号",
             "postal": "200001", "lat": 31.235180, "lon": 121.477500},
        ],
    },
    {
        "country": "CN: 중국", "admin": "100: Jiangsu",
        "city_en": "Suzhou", "city_local": "江苏省苏州市", "lang": "zh",
        "streets": [
            {"en": "8 Suhong West Road, Suzhou Industrial Park", "local": "苏州工业园区苏虹西路8号",
             "postal": "215021", "lat": 31.315610, "lon": 120.686340},
            {"en": "200 Xinghai Street", "local": "星海街200号",
             "postal": "215028", "lat": 31.322450, "lon": 120.717800},
        ],
    },
    {
        "country": "CN: 중국", "admin": "440: Guangdong",
        "city_en": "Shenzhen", "city_local": "广东省深圳市", "lang": "zh",
        "streets": [
            {"en": "10000 Shennan Avenue, Futian District", "local": "福田区深南大道10000号",
             "postal": "518000", "lat": 22.543611, "lon": 114.056880},
            {"en": "1 Keyuan Road, Nanshan District", "local": "南山区科苑路1号",
             "postal": "518057", "lat": 22.537300, "lon": 113.947700},
        ],
    },
    # ---- 일본 ----
    {
        "country": "JP: 일본", "admin": "13: Tokyo",
        "city_en": "Tokyo", "city_local": "東京都", "lang": "ja",
        "streets": [
            {"en": "2-11-1 Nagatacho, Chiyoda-ku", "local": "千代田区永田町2-11-1",
             "postal": "100-0014", "lat": 35.676190, "lon": 139.744730},
            {"en": "1-1-2 Oshiage, Sumida-ku", "local": "墨田区押上1-1-2",
             "postal": "131-0045", "lat": 35.710060, "lon": 139.810700},
        ],
    },
    {
        "country": "JP: 일본", "admin": "27: Osaka",
        "city_en": "Osaka", "city_local": "大阪府", "lang": "ja",
        "streets": [
            {"en": "1-3-20 Umeda, Kita-ku", "local": "北区梅田1-3-20",
             "postal": "530-0001", "lat": 34.702485, "lon": 135.496040},
            {"en": "2-1-33 Nishishinsaibashi, Chuo-ku", "local": "中央区西心斎橋2-1-33",
             "postal": "542-0086", "lat": 34.671870, "lon": 135.499750},
        ],
    },
    {
        "country": "JP: 일본", "admin": "23: Aichi",
        "city_en": "Nagoya", "city_local": "愛知県名古屋市", "lang": "ja",
        "streets": [
            {"en": "1-1-4 Meieki, Nakamura-ku", "local": "中村区名駅1-1-4",
             "postal": "450-0002", "lat": 35.170920, "lon": 136.881637},
            {"en": "3-1-1 Sakae, Naka-ku", "local": "中区栄3-1-1",
             "postal": "460-0008", "lat": 35.168060, "lon": 136.908390},
        ],
    },
    # ---- 서구 ----
    {
        "country": "CH: 스위스", "admin": "SG: St. Gallen",
        "city_en": "St. Gallen", "city_local": "St. Gallen", "lang": "en",
        "streets": [
            {"en": "Bahnhofstrasse 12", "local": "Bahnhofstrasse 12",
             "postal": "9000", "lat": 47.422780, "lon": 9.369870},
            {"en": "Marktgasse 8", "local": "Marktgasse 8",
             "postal": "9004", "lat": 47.425600, "lon": 9.377180},
        ],
    },
    {
        "country": "US: 미국", "admin": "CA: California",
        "city_en": "Mountain View", "city_local": "Mountain View", "lang": "en",
        "streets": [
            {"en": "1600 Amphitheatre Parkway", "local": "1600 Amphitheatre Parkway",
             "postal": "94043", "lat": 37.422030, "lon": -122.084000},
            {"en": "1 Infinite Loop, Cupertino", "local": "1 Infinite Loop, Cupertino",
             "postal": "95014", "lat": 37.331820, "lon": -122.030330},
        ],
    },
    {
        "country": "US: 미국", "admin": "IL: Illinois",
        "city_en": "Chicago", "city_local": "Chicago", "lang": "en",
        "streets": [
            {"en": "233 S Wacker Drive", "local": "233 S Wacker Drive",
             "postal": "60606", "lat": 41.878760, "lon": -87.635800},
            {"en": "875 N Michigan Avenue", "local": "875 N Michigan Avenue",
             "postal": "60611", "lat": 41.898780, "lon": -87.623380},
        ],
    },
    {
        "country": "DE: 독일", "admin": "BY: Bavaria",
        "city_en": "Munich", "city_local": "München", "lang": "de",
        "streets": [
            {"en": "Marienplatz 8", "local": "Marienplatz 8",
             "postal": "80331", "lat": 48.137150, "lon": 11.575490},
            {"en": "Leopoldstrasse 21", "local": "Leopoldstraße 21",
             "postal": "80802", "lat": 48.159180, "lon": 11.586030},
        ],
    },
]

# 국가 분포 가중치 (한/중/일 중심 + 일부 서구)
PLACE_WEIGHTS = np.array([
    3, 3, 2,      # KR (Seoul, Gyeonggi, Busan)
    3, 3, 2,      # CN (Shanghai, Jiangsu, Guangdong)
    3, 2, 2,      # JP (Tokyo, Osaka, Aichi)
    1, 1, 1, 1,   # CH, US-CA, US-IL, DE
], dtype=float)
PLACE_WEIGHTS = PLACE_WEIGHTS / PLACE_WEIGHTS.sum()

# ---------------------------------------------------------------------------
# 2) 업체명 풀 (가상 명칭). base_en / base_local(로컬 표기) 세트.
# ---------------------------------------------------------------------------
COMPANY_POOL = {
    "ko": [
        ("Hanla Precision", "한라정밀"), ("Daeyang Electronics", "대양전자"),
        ("Sungwoo Materials", "성우소재"), ("Jinwoo Semiconductor", "진우반도체"),
        ("Kyungin Chemical", "경인화학"), ("Nexen Components", "넥센부품"),
    ],
    "zh": [
        ("Huaxin Technology", "华芯科技"), ("Zhongsheng Electronics", "中晟电子"),
        ("Ruifeng Materials", "瑞丰材料"), ("Dongfang Precision", "东方精密"),
        ("Jinlong Semiconductor", "金龙半导体"), ("Haiyuan Components", "海源部件"),
    ],
    "ja": [
        ("Sakura Denshi", "さくら電子"), ("Nippon Seimitsu", "日本精密"),
        ("Toyo Materials", "東洋マテリアル"), ("Fuji Handotai", "富士半導体"),
        ("Asahi Components", "旭部品"), ("Daiwa Electronics", "大和エレクトロニクス"),
    ],
    "en": [
        ("Alpine Precision", "Alpine Precision"), ("Summit Electronics", "Summit Electronics"),
        ("Rheintal Materials", "Rheintal Materials"), ("Pioneer Semiconductor", "Pioneer Semiconductor"),
        ("Lakeside Components", "Lakeside Components"), ("Bavaria Technik", "Bavaria Technik"),
    ],
    "de": [
        ("Alpine Precision", "Alpine Präzision"), ("Summit Electronics", "Summit Elektronik"),
        ("Bavaria Technik", "Bavaria Technik"), ("Rheinland Materials", "Rheinland Materialien"),
    ],
}

COMPANY_SUFFIX = {
    "ko": ["(주)", "㈜", "주식회사", "유한회사"],
    "zh": ["有限公司", "股份有限公司"],
    "ja": ["株式会社", "有限会社"],
    "en": ["Co., Ltd.", "LLC", "Inc.", "Corp.", "Ltd."],
    "de": ["GmbH", "AG"],
}

STATUS_POOL = ["임시저장", "검증중", "등록확정", "재검토요청"]
STATUS_WEIGHTS = [0.15, 0.20, 0.50, 0.15]

SOURCE_POOL = ["협력사등록", "Factory Information", "Supply Tree", "원 메이커"]

PORT_CODES = {  # UN/LOCODE
    "KR: 한국": ["KRPUS", "KRINC"], "CN: 중국": ["CNSHA", "CNSZX"],
    "JP: 일본": ["JPTYO", "JPUKB"], "US: 미국": ["USLGB"], "DE: 독일": ["DEHAM"],
    "CH: 스위스": ["CHBSL"],
}
AIRPORT_CODES = {  # IATA
    "KR: 한국": ["ICN", "GMP", "PUS"], "CN: 중국": ["PVG", "SZX", "CAN"],
    "JP: 일본": ["NRT", "HND", "KIX"], "US: 미국": ["SFO", "ORD"], "DE: 독일": ["MUC"],
    "CH: 스위스": ["ZRH"],
}

# ---------------------------------------------------------------------------
# 유틸: 유일 코드 생성기
# ---------------------------------------------------------------------------
_used_site_codes = set()
_used_corp_ids = set()
_used_duns = set()
_used_partner = set()


def gen_site_code():
    while True:
        code = "S" + "".join(str(d) for d in rng.integers(0, 10, size=6))
        if code not in _used_site_codes:
            _used_site_codes.add(code)
            return code


def gen_corp_id():
    while True:
        cid = "".join(str(d) for d in rng.integers(0, 10, size=10))
        if cid not in _used_corp_ids:
            _used_corp_ids.add(cid)
            return cid


def gen_duns():
    while True:
        digits = "".join(str(d) for d in rng.integers(0, 10, size=9))
        if digits in _used_duns:
            continue
        _used_duns.add(digits)
        # 절반은 하이픈 형식, 절반은 숫자만
        if rng.random() < 0.5:
            return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
        return digits


def gen_partner_code():
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    while True:
        code = alpha[rng.integers(0, 26)] + "".join(
            alnum[i] for i in rng.integers(0, 36, size=3)
        )
        if code not in _used_partner:
            _used_partner.add(code)
            return code


def gen_date():
    # 2024-01-01 ~ 2026-09-08
    year = int(rng.choice([2024, 2025, 2026], p=[0.25, 0.45, 0.30]))
    if year == 2026:
        month = int(rng.integers(1, 10))  # 1~9
        max_day = 8 if month == 9 else 28
    else:
        month = int(rng.integers(1, 13))
        max_day = 28
    day = int(rng.integers(1, max_day + 1))
    return f"{year:04d}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# 업체명 / 주소 노이즈 주입
# ---------------------------------------------------------------------------
def make_company_name(place, add_noise):
    """(표시용 업체명, base_en) 반환. add_noise=True면 불완전 표기."""
    lang = place["lang"]
    base_en, base_local = COMPANY_POOL[lang][int(rng.integers(0, len(COMPANY_POOL[lang])))]

    if not add_noise:
        # 정제된 상태: 영문 표기(불용어 없음)
        return base_en, base_en

    # 노이즈 유형 선택
    kind = rng.choice(["suffix", "local_only", "typo", "case", "suffix_local"])
    suffixes = COMPANY_SUFFIX.get(lang, COMPANY_SUFFIX["en"])
    if kind == "suffix":
        return f"{base_en} {suffixes[int(rng.integers(0, len(suffixes)))]}", base_en
    if kind == "suffix_local":
        return f"{base_local}{suffixes[int(rng.integers(0, len(suffixes)))]}", base_en
    if kind == "local_only":
        return base_local, base_en
    if kind == "typo":
        # 문자 하나 중복/누락
        s = base_en
        if len(s) > 4:
            p = int(rng.integers(1, len(s) - 1))
            s = s[:p] + s[p] + s[p:] if rng.random() < 0.5 else s[:p] + s[p + 1:]
        return s, base_en
    # case
    return base_en.upper() if rng.random() < 0.5 else base_en.lower(), base_en


def clean_address(place, street):
    """지점(street) 기준 정제된 (영문, 로컬) 주소."""
    lang = place["lang"]
    region = place["admin"].split(": ")[1]
    clean_en = f"{street['en']}, {place['city_en']}, {region} {street['postal']}"
    if lang == "ko":
        clean_local = f"{place['city_local']} {street['local']} ({street['postal']})"
    elif lang == "zh":
        clean_local = f"{place['city_local']}{street['local']} {street['postal']}"
    elif lang == "ja":
        clean_local = f"{street['postal']} {place['city_local']}{street['local']}"
    else:  # en / de
        clean_local = f"{street['local']}, {street['postal']} {place['city_local']}"
    return clean_en, clean_local


def make_addresses(place, street, add_noise):
    """지점(street) 고정 상태에서 (주소Eng, 주소Local) 반환.
    좌표는 street 값으로 별도 부여되므로 여기서는 문자열 표기만 다룸."""
    clean_en, clean_local = clean_address(place, street)
    if not add_noise:
        return clean_en, clean_local

    region = place["admin"].split(": ")[1]
    kind = rng.choice(["no_postal", "typo", "abbrev", "partial", "spacing", "mixed"])
    en = clean_en
    if kind == "no_postal":
        en = f"{street['en']}, {place['city_en']}"
    elif kind == "typo":
        en = clean_en.replace("a", "@", 1) if "a" in clean_en else clean_en + " "
    elif kind == "abbrev":
        en = (clean_en.replace("Street", "St.").replace("Road", "Rd.")
              .replace("Avenue", "Ave.").replace("Drive", "Dr."))
    elif kind == "partial":
        en = f"{place['city_en']}, {region}"
    elif kind == "spacing":
        en = clean_en.replace(", ", "  ").replace(",", " ,")
    elif kind == "mixed":
        # 영문 필드에 로컬 도로명 혼용
        en = f"{street['local']}, {place['city_en']} {street['postal']}"

    return en, clean_local


def site_type_and_code(place):
    """Site 유형 결정 및 항구/공항 코드 반환."""
    r = rng.random()
    if r < 0.85:
        return "제조업체", ""
    if r < 0.93:
        codes = PORT_CODES.get(place["country"], ["XXXXX"])
        return "항구", codes[int(rng.integers(0, len(codes)))]
    codes = AIRPORT_CODES.get(place["country"], ["XXX"])
    return "공항", codes[int(rng.integers(0, len(codes)))]


# ---------------------------------------------------------------------------
# 3) 행 생성
# ---------------------------------------------------------------------------
def new_row(place, street_idx, add_noise):
    street = place["streets"][street_idx]
    company_disp, company_base = make_company_name(place, add_noise)
    addr_en, addr_local = make_addresses(place, street, add_noise)
    stype, code = site_type_and_code(place)
    return {
        "No.": None,  # 나중에 채움
        "Status": str(rng.choice(STATUS_POOL, p=STATUS_WEIGHTS)),
        "Site Code": gen_site_code(),
        "Site 유형": stype,
        "업체": company_disp,
        "항구/공항 코드": code,
        "기업식별 코드": gen_corp_id(),
        "Duns No.": gen_duns(),
        "국가/지역": place["country"],
        "행정구역": place["admin"],
        "주소(Eng)": addr_en,
        "주소(Local)": addr_local,
        "위도": f"{street['lat']:.6f}",   # 지점(도로명)의 실제 좌표
        "경도": f"{street['lon']:.6f}",
        "관련 협력사 코드": gen_partner_code(),
        "수정일": gen_date(),
        "Site 출처": str(rng.choice(SOURCE_POOL)),
        "STD 주소": "",
        "STD 업체명": "",
        # 내부 메타(출력 제외)
        "_place": place,
        "_street_idx": street_idx,
        "_company_base": company_base,
        "_noise": add_noise,
    }


def make_duplicate(base_row):
    """base_row 와 '동일 Site 다른 표기'인 near-duplicate 행 생성.
    동일 지점(같은 도로/좌표)을 공유하되 업체명/주소 표기·Site Code·출처만 다르게."""
    place = base_row["_place"]
    street = place["streets"][base_row["_street_idx"]]
    company_base = base_row["_company_base"]
    lang = place["lang"]

    # 같은 업체(base_en 유지)의 다른 표기
    base_local = next(
        (loc for en, loc in COMPANY_POOL[lang] if en == company_base), company_base
    )
    suffixes = COMPANY_SUFFIX.get(lang, COMPANY_SUFFIX["en"])
    dup_variants = [
        f"{company_base} {suffixes[int(rng.integers(0, len(suffixes)))]}",
        base_local,
        company_base.upper(),
        f"{base_local}{suffixes[0]}" if lang in ("ko", "zh", "ja") else f"{company_base} {suffixes[0]}",
    ]
    dup_company = dup_variants[int(rng.integers(0, len(dup_variants)))]

    # 동일 지점에 대한 다른 주소 표기(노이즈 on) — 좌표는 동일
    addr_en, addr_local = make_addresses(place, street, add_noise=True)

    row = dict(base_row)
    row["Site Code"] = gen_site_code()
    row["기업식별 코드"] = gen_corp_id()
    row["Duns No."] = gen_duns()
    row["관련 협력사 코드"] = gen_partner_code()
    row["업체"] = dup_company
    row["주소(Eng)"] = addr_en
    row["주소(Local)"] = addr_local
    # 위도/경도는 base 와 동일(같은 지점) — 그대로 유지
    row["Site 출처"] = str(rng.choice(SOURCE_POOL))
    row["Status"] = str(rng.choice(STATUS_POOL, p=STATUS_WEIGHTS))
    row["수정일"] = gen_date()
    row["STD 주소"] = ""
    row["STD 업체명"] = ""
    row["_noise"] = True
    return row


def generate():
    n_base = N_ROWS - N_DUPLICATE
    rows = []

    place_indices = rng.choice(len(PLACES), size=n_base, p=PLACE_WEIGHTS)
    noise_flags = rng.random(n_base) < NOISE_RATE
    for i in range(n_base):
        place = PLACES[int(place_indices[i])]
        street_idx = int(rng.integers(0, len(place["streets"])))
        rows.append(new_row(place, street_idx, bool(noise_flags[i])))

    # near-duplicate: 기존 base 행에서 선택하여 동일 지점의 다른 표기 생성
    dup_source_idx = rng.choice(n_base, size=N_DUPLICATE, replace=False)
    for src in dup_source_idx:
        rows.append(make_duplicate(rows[int(src)]))

    # 순서 섞기 후 No. 부여
    order = rng.permutation(len(rows))
    rows = [rows[i] for i in order]
    for i, row in enumerate(rows, start=1):
        row["No."] = i

    return rows


def write_csv(rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    rows = generate()
    write_csv(rows)
    n_noise = sum(1 for r in rows if r["_noise"])
    print(f"생성 완료: {OUT_PATH}")
    print(f"- 총 {len(rows)}건, 노이즈(불완전) {n_noise}건 ({n_noise/len(rows)*100:.0f}%)")
    print(f"- near-duplicate 주입: {N_DUPLICATE}건")
