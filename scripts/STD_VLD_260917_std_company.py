# -*- coding: utf-8 -*-
"""업체명 표준화 + 유사도(SIM) 서브루틴.

- standardize_company(name): 저장용 표준 업체명. 법인형태 표기(불용어)만 제거하고
  원 언어/표기/대소문자는 보존한다. → 산출물 "STD 업체명" 컬럼값.
- comparison_key(name): SIM 비교 전용 정규화 키(미저장). 법인형태 제거까지만 적용하고
  소문자/특수문자 정규화하여 유사도 비교를 수행한다. (업종 일반명사는 제거하지 않는다 —
  "동탄 정밀", "LT 메탈"처럼 일반명사를 떼면 비교 불가 수준으로 짧아지는 업체명이 많아
  법인 표기 제거까지만 활용하기로 협의.)
- SIM(a, b): 설계 문서 1-1장. Jaro-Winkler / Token Sort Ratio / Levenshtein 비율의
  최댓값을 유사도로 사용, 임계치 이상이면 동일 업체로 판정.
"""

import re
import unicodedata

from rapidfuzz.distance import JaroWinkler
from rapidfuzz.fuzz import ratio, token_sort_ratio

SIM_THRESHOLD = 0.85  # 설계 문서 예시값. Golden Dataset으로 튜닝 필요.

# ---------------------------------------------------------------------------
# 불용어: LEGAL_SUFFIXES(법인형태만). 저장값(STD 업체명)과 비교키 모두에서 제거하고
# 업종 일반명사는 양쪽 모두 보존한다(협의: 법인 표기 제거까지만).
# ---------------------------------------------------------------------------
LEGAL_SUFFIXES = [
    # 한국
    "주식회사", "유한회사", "(주)", "㈜",
    # 중국
    "股份有限公司", "有限公司",
    # 일본
    "株式会社", "有限会社",
    # 영어
    "Co., Ltd.", "Co.,Ltd.", "Co., Ltd", "Co. Ltd.", "Corp.", "Inc.",
    "Ltd.", "Ltd", "LLC", "Corp", "Inc", "Co.",
    # 독일
    "GmbH", "AG",
    # 태국
    "บริษัท", "จำกัด",
    # 베트남
    "Công ty TNHH", "Công ty Cổ phần", "Cổ phần",
]

# 저장값에서 제거하는 순서: 긴 것부터(부분 겹침 방지)
_LEGAL_SORTED = sorted(LEGAL_SUFFIXES, key=len, reverse=True)

# 양끝에서 다듬을 문장부호/구분자(괄호는 상호명 내용의 일부이므로 제외)
_TRIM_CHARS = " \t.,·-·㈜、，"


def standardize_company(name: str) -> str:
    """저장용 표준 업체명. 법인형태 불용어·특수문자·중복공백만 제거하고
    원 언어/표기/대소문자는 보존한다.

    예) '경인화학주식회사' → '경인화학', 'Summit ElectronicsLtd.' → 'Summit Electronics'
        '日本精密' → '日本精密'(변화 없음)
    """
    if name is None:
        return ""
    s = name.strip()
    # 법인형태 표기 제거(대소문자 무시, 긴 것부터)
    for suf in _LEGAL_SORTED:
        s = re.sub(re.escape(suf), " ", s, flags=re.IGNORECASE)
    # 중복 공백 정리 및 양끝 문장부호 제거
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(_TRIM_CHARS).strip()
    return s


def comparison_key(name: str) -> str:
    """SIM 비교 전용 정규화 키(미저장). NFKC + 소문자 + 법인형태 제거 +
    특수문자/공백 정규화. 업종 일반명사는 보존한다.
    예) 'Summit Electronics' → 'summitelectronics'
    """
    if name is None:
        return ""
    # 저장 표준화(법인형태 제거)를 먼저 거친 뒤 소문자/유니코드 정규화
    s = standardize_company(name)
    s = unicodedata.normalize("NFKC", s).lower()
    # 영문/숫자 사이 구분기호 제거, CJK/타 문자는 보존
    s = re.sub(r"[^\w぀-ヿ一-鿿가-힣฀-๿]+", "", s)
    return s.strip()


def SIM(name_std: str, candidate_std: str):
    """설계 문서 1-1장. 세 지표의 최댓값(0~1)과 임계치 판정을 반환.

    입력은 표준화 업체명(원표기)이며, 내부에서 comparison_key로 비교 정규화한다.
    반환: (score: float 0~1, is_match: bool)
    """
    a = comparison_key(name_std)
    b = comparison_key(candidate_std)
    if not a or not b:
        return 0.0, False
    jw = JaroWinkler.similarity(a, b)          # 0~1
    tsr = token_sort_ratio(a, b) / 100.0       # 0~100 → 0~1
    lev = ratio(a, b) / 100.0                  # 0~100 → 0~1 (Levenshtein 비율)
    score = max(jw, tsr, lev)
    return score, score >= SIM_THRESHOLD
