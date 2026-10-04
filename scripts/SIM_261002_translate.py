# -*- coding: utf-8 -*-
"""업체명 언어 판정 + 영문 표기 생성 (LLM 기반).

detect_and_translate(name): 업체명 1건에 대해 ISO 639-1 언어코드와 영문 표기를
단일 LLM 호출로 산출한다. 유사 검색에서 "동일 언어끼리 비교, 교차 시 영문 폴백"을
수행하기 위한 근간.

- Site 정보 표준화 과정(배치)과 사용자 쿼리 표준화(실시간) 양쪽에서 호출된다.
- OPENAI_API_KEY 미설정·호출 실패 시 휴리스틱으로 폴백한다(LLM 없이도 서비스가
  돌아가야 함 — verify_service의 real→mock 폴백과 동일 철학).
- 모듈 레벨 캐시로 동일 입력 반복 호출을 막는다(배치에서 중복 업체명 다수).

사용:
  python scripts/SIM_261002_translate.py "경인화학"   # {"lang": "ko", "name_eng": "..."}
"""

import json
import logging
import os

_LOG = logging.getLogger(__name__)

_MODEL = os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini")

# (lang, name_eng) 캐시. 키는 원본 업체명 문자열.
_CACHE: dict = {}
_CLIENT = None
_CLIENT_INIT = False


def _get_client():
    """OpenAI 클라이언트 지연 생성 + 캐시. 키 없거나 SDK 미설치면 None(→휴리스틱 폴백).

    Returns:
        OpenAI | None: 생성된 클라이언트. 키 없음·생성 실패면 None.
    """
    global _CLIENT, _CLIENT_INIT
    if not _CLIENT_INIT:
        _CLIENT_INIT = True
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            _LOG.warning("OPENAI_API_KEY 미설정 → 업체명 번역 비활성(원본 폴백)")
        else:
            try:
                from openai import OpenAI
                _CLIENT = OpenAI(api_key=key)
            except Exception as e:
                _LOG.warning("openai 클라이언트 생성 실패 → 번역 비활성(원본 폴백): %s", e)
                _CLIENT = None
    return _CLIENT


def _is_ascii_latin(s: str) -> bool:
    """영문/숫자/기호 위주(비ASCII 글자가 없음)인지. 영어로 간주해 LLM을 생략한다.

    Args:
        s (str): 판정할 문자열.

    Returns:
        bool: 비ASCII 글자가 없으면 True.
    """
    return not any(c for c in s if ord(c) > 0x7F and c.isalpha())


def _heuristic_lang(s: str) -> str:
    """LLM 폴백용 간단 언어 판정. 문자 블록 기반(한글/일본가나/한자/라틴).

    Args:
        s (str): 판정할 문자열.

    Returns:
        str: ISO 639-1 코드("ko"/"ja"/"zh"/"en").
    """
    for c in s:
        if "가" <= c <= "힣":
            return "ko"
        if "぀" <= c <= "ヿ":  # 히라가나/가타카나
            return "ja"
        if "一" <= c <= "鿿":  # CJK 한자(중국어로 분류, 일본어 한자는 가나 우선 판정)
            return "zh"
    return "en"


def detect_and_translate(name: str) -> dict:
    """업체명의 언어코드와 영문 표기를 반환.

    반환: {"lang": ISO 639-1 코드, "name_eng": 영문 업체명}
    - 영문(ASCII) 업체명은 LLM 없이 {"lang": "en", "name_eng": name}.
    - 비영어는 LLM으로 언어코드 + 영문 음역/표기 생성. 실패 시 휴리스틱 폴백.

    Args:
        name (str): 원본 업체명.

    Returns:
        dict: {"lang": 언어코드, "name_eng": 영문 업체명}. 빈 입력이면 둘 다 "".
    """
    s = (name or "").strip()
    if not s:
        return {"lang": "", "name_eng": ""}
    if s in _CACHE:
        return _CACHE[s]

    if _is_ascii_latin(s):
        result = {"lang": "en", "name_eng": s}
        _CACHE[s] = result
        return result

    result = _llm_translate(s) or {"lang": _heuristic_lang(s), "name_eng": s}
    _CACHE[s] = result
    return result


def _llm_translate(name: str):
    """OpenAI 호출로 {"lang", "name_eng"} 산출. 실패/키없음이면 None.

    Args:
        name (str): 비영어 원본 업체명.

    Returns:
        dict | None: {"lang", "name_eng"}. 키 없음·호출 실패·빈 응답이면 None.
    """
    client = _get_client()
    if client is None:
        return None
    prompt = (
        "You are given a company name in its original language. "
        "Return a JSON object with two keys: "
        '"lang" (the ISO 639-1 language code of the name, e.g. "ko", "zh", "ja", "en") '
        'and "name_eng" (the company name written in English — use the official '
        "English name if commonly known, otherwise a romanized/transliterated form). "
        "Do not add any commentary.\n"
        f"Company name: {name}"
    )
    try:
        resp = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content)
        lang = str(data.get("lang") or "").strip().lower()[:5]
        name_eng = str(data.get("name_eng") or "").strip()
        if not name_eng:
            return None
        return {"lang": lang or _heuristic_lang(name), "name_eng": name_eng}
    except Exception as e:
        _LOG.warning("업체명 번역 호출 실패 → 원본 폴백 (%r): %s", name, e)
        return None


def main(argv=None):
    """CLI 인자로 받은 업체명의 언어·영문 표기를 JSON으로 출력한다.

    Args:
        argv (list, optional): CLI 인자 리스트. 기본 None(sys.argv 사용).

    Returns:
        int: 종료 코드(정상 0, 인자 없음 1).
    """
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python SIM_261002_translate.py <company_name>")
        return 1
    print(json.dumps(detect_and_translate(args[0]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
