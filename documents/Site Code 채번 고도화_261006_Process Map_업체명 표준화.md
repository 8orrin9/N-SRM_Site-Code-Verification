# 업체명 표준화 프로세스 (불용어 제거 → 영문 표기 생성 → 유사 비교)

> 본 문서는 「Site Code 채번 고도화」 과제에서 **업체명**을 다루는 세 단계
> ― ① 저장용 표준화(법인형태 불용어 제거), ② 영문 표기·언어 생성(LLM),
> ③ 유사 Site 검색 시 언어별 업체명 비교 ― 가 어떻게 연결되는지를 정리한다.
>
> **배경(2026-10-02 고객 협의):** 유사 비교(SIM)에서 업종 일반명사(예: "정밀",
> "메탈")까지 제거하면 `"동탄 정밀" → "동탄"`, `"LT 메탈" → "LT"`처럼 비교 불가
> 수준으로 짧아지는 업체명이 많다. 이에 **법인형태 표기 제거까지만** 적용하고
> 업종 일반명사는 보존하기로 마무리 협의했다. 또한 언어가 다른 업체명(한글↔중국어
> 등)은 직접 비교가 무의미하므로 **영문 표기를 생성해 교차 비교**하기로 했다.

---

## 1. 전체 흐름 한눈에

```
원본 업체명 (예: '경인화학주식회사', '上海精密有限公司', 'LT 메탈 Co.,Ltd.')
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ ① 저장용 표준화  standardize_company()                        │
│    법인형태 불용어만 제거 (업종 일반명사·원언어·대소문자 보존) │
│    → 'STD 업체명' 컬럼                                         │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ ② 영문 표기·언어 생성  detect_and_translate()  (LLM)          │
│    ISO 639-1 언어코드 + 영문 표기(공식명/음역)                 │
│    → 'STD 업체명(Eng)', '업체명 언어' 컬럼                     │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ 유사 Site 검색  score_pair() → name_gate() → SIM()         │
│    같은 언어끼리는 원표준명, 다르면 영문명으로 비교            │
│    comparison_key()로 비교 정규화(법인형태 제거까지만)         │
└─────────────────────────────────────────────────────────────┘
```

**적용 경로의 일원화:** ①·②는 `run_verification.process_row` 한 곳에서 수행되고,
Standardization 메뉴와 Similarity Search의 "확인할 데이터" 표준화가 **모두 같은
`/api/standardize` 경로**를 거친다. 즉 Site 배치든 사용자 쿼리든 동일 로직을 탄다.

---

## 2. 단계 ① — 저장용 표준화 (법인형태 불용어 제거)

### 2-1. 목적

저장되는 `STD 업체명`은 **원 언어·표기·대소문자를 보존**하되, 비교·식별에 노이즈가
되는 **법인형태 표기만** 제거한다. 업종 일반명사는 식별력의 핵심이므로 **보존**한다.

| 원본 | STD 업체명 | 설명 |
|---|---|---|
| `경인화학주식회사` | `경인화학` | `주식회사` 제거 |
| `Summit ElectronicsLtd.` | `Summit Electronics` | `Ltd.` 제거 |
| `LT 메탈 Co.,Ltd.` | `LT 메탈` | 법인표기만, **"메탈" 보존** |
| `日本精密` | `日本精密` | 변화 없음 |

### 2-2. 제거 대상 — `LEGAL_SUFFIXES` (법인형태만)

다국어 법인형태 표기를 상수로 둔다. **긴 표기부터** 치환해 부분 겹침을 방지한다
(`_LEGAL_SORTED = sorted(..., key=len, reverse=True)`).

```
한국   주식회사 / 유한회사 / (주) / ㈜
중국   股份有限公司 / 有限公司
일본   株式会社 / 有限会社
영어   Co., Ltd. / Corp. / Inc. / Ltd. / LLC / Co. …
독일   GmbH / AG
태국   บริษัท / จำกัด
베트남 Công ty TNHH / Công ty Cổ phần / Cổ phần
```

> **업종 일반명사는 제거하지 않는다.** (과거 비교키 전용으로 두었던
> `INDUSTRY_STOPWORDS` 제거 단계는 10/02 협의로 **롤백**했다.)

### 2-3. 처리 로직 — `standardize_company(name)`

1. `strip()` 후 `LEGAL_SUFFIXES`를 **대소문자 무시**(`re.IGNORECASE`)로 공백 치환.
2. 중복 공백 정리(`\s+ → ' '`).
3. 양끝 문장부호/구분자 다듬기(`_TRIM_CHARS = " \t.,·-·㈜、，"`). **괄호는 상호명의
   일부일 수 있어 제외**한다.

---

## 3. 단계 ② — 영문 표기·언어 생성 (LLM)

### 3-1. 목적

언어가 다른 업체명은 직접 비교가 무의미하다. 비교 시 **공통 축(영문)**을 확보하기
위해, 비영어 업체명마다 **ISO 639-1 언어코드 + 영문 표기**를 생성한다.

| STD 업체명 | 업체명 언어 | STD 업체명(Eng) |
|---|---|---|
| `경인화학` | `ko` | `Gyeongin Chemical` |
| `上海精密` | `zh` | `Shanghai Precision` |
| `Summit Electronics` | `en` | `Summit Electronics` (LLM 미호출) |

### 3-2. 처리 로직 — `detect_and_translate(name)` (`SIM_261002_translate.py`)

```
detect_and_translate(name):
   s = name.strip()
   if 캐시에 있으면 → 반환                       # 모듈 레벨 dict 캐시(배치 중복 억제)
   if _is_ascii_latin(s):                        # 영문/숫자/기호 위주면
       return {"lang": "en", "name_eng": s}      # LLM 생략(비용·결정성)
   r = _llm_translate(s)                          # OpenAI 호출(JSON 모드)
   return r or {"lang": _heuristic_lang(s), "name_eng": s}   # 실패 시 폴백
```

- **LLM 호출(`_llm_translate`)**: OpenAI Chat Completions(`response_format=json_object`,
  `temperature=0`)로 `{"lang", "name_eng"}` 수신·파싱. 모델은 환경변수
  `OPENAI_TRANSLATE_MODEL`(기본 `gpt-4o-mini`).
- **영어 단축경로(`_is_ascii_latin`)**: 비ASCII 글자가 없으면 영어로 간주해 LLM을
  건너뛴다. 결정성 + 비용 절감.
- **폴백(옵트인 철학)**: `OPENAI_API_KEY` 미설정, `openai` 미설치, 호출 실패 중
  어느 경우든 **원본을 그대로 영문명 자리에** 두고 휴리스틱(`_heuristic_lang`:
  한글/가나/한자/라틴 블록)으로 언어만 판정한다. LLM 없이도 서비스는 동작한다.
- **관측성**: 키 미설정·클라이언트 생성 실패·호출 실패 시 `logging.warning`을
  남겨, 조용한 폴백이 배포 로그(Render Logs)에 드러나게 한다.

> **배포 주의(실측):** `openai` 패키지가 배포 requirements에 없으면 ImportError로
> 조용히 폴백해 **번역이 전혀 안 되는 것처럼** 보인다. `requirements-deploy.txt`에
> `openai`를 포함하고, Render 환경변수에 **유효한** `OPENAI_API_KEY`를 설정해야 한다.

---

## 4. 단계 ③ — 유사 Site 검색 시 업체명 비교

업체명 비교는 유사 검색의 여러 게이트(코드/Duns/주소/좌표/업체명) 중 **업체명 게이트**에
해당한다. 핵심은 **언어로 비교 대상을 고르는 것**과 **비교 정규화(비교키)**다.

### 4-1. 비교할 이름 선택 — 동일 언어 우선, 교차 시 영문 폴백

`find_similar.score_pair()`에서 `name_gate` 호출 직전에 결정한다.

```
q_lang, ref_lang = 쿼리 언어, 기준 언어
if q_lang and ref_lang and q_lang == ref_lang:
    비교쌍 = (쿼리 STD 업체명, 기준 STD 업체명)        # 같은 언어 → 원표준명
else:
    비교쌍 = (쿼리 STD 업체명(Eng), 기준 STD 업체명(Eng))  # 다름/결측 → 영문
```

| 쿼리 | 기준 | 비교 축 |
|---|---|---|
| `경인화학`(ko) | `경인화학공업`(ko) | 원표준명끼리 |
| `경인화학`(ko) | `上海精密`(zh) | 영문명끼리(`Gyeongin Chemical` ↔ `Shanghai Precision`) |

> 영문명이 비어 있으면 `_prep()`에서 `std_name`으로 폴백해 게이트가 SKIP되지 않게 한다.
> 쿼리는 사용자 수기 입력이라 `STD 업체명`이 비고 `업체`만 있는 경우가 많아, `label`로도
> 보완한다.

### 4-2. 비교 정규화 — `comparison_key(name)`

비교 전용(미저장) 키. **저장 표준화(법인형태 제거)를 먼저 거친 뒤** 추가 정규화한다.

```
comparison_key(name):
   s = standardize_company(name)          # 법인형태 제거(업종명사 보존)
   s = NFKC(s).lower()                    # 유니코드 정규화 + 소문자
   s = 영숫자/CJK/한글/타이 외 구분기호 제거
   return s
```

예) `'Summit Electronics' → 'summitelectronics'`.
**업종 일반명사는 유지**된다(`'동탄 정밀' → '동탄정밀'`).

### 4-3. 유사도 산출 — `SIM(a, b)`

`comparison_key`로 양쪽을 정규화한 뒤 **세 지표의 최댓값**을 유사도로 쓴다.

| 지표 | 설명 |
|---|---|
| Jaro-Winkler | 접두 일치에 가중(오타·축약 강건) |
| Token Sort Ratio | 토큰 순서 차이 흡수(`'A B' ↔ 'B A'`) |
| Levenshtein 비율 | 편집거리 기반 전반 유사 |

`score = max(jw, tsr, lev)`, `is_match = score ≥ SIM_THRESHOLD(0.85)`.

> `name_gate`는 `SIM`을 재사용해 `(EQUAL/DIFFERENT, score)`를 반환한다. 유사 검색은
> 이 `score`를 표시용 `nameSim`으로 쓰고, 종합 점수(avg)에 결합한다. 게이트가
> DIFFERENT이고 SIM이 임계 미만인 **약한 이름 유사**는 `WEAK_NAME_FACTOR(0.6)`로
> 감쇄해 상위권 잠식을 막는다(표시 점수는 원점수 유지).

---

## 5. 산출물 컬럼

| 컬럼 | 생성 단계 | 내용 |
|---|---|---|
| `STD 업체명` | ① | 법인형태 제거한 저장용 표준명(원표기 보존) |
| `STD 업체명(Eng)` | ② | 영문 표기(공식명 우선, 없으면 음역). 영어 입력은 원본 그대로 |
| `업체명 언어` | ② | ISO 639-1 언어코드(`ko`/`zh`/`ja`/`en`…) |

> ③(유사 비교)은 산출 컬럼을 만들지 않고, 위 세 컬럼을 **입력으로 소비**한다.

---

## 6. 구현 매핑 (코드 위치)

| 구성요소 | 파일 | 역할 |
|---|---|---|
| 저장 표준화·비교키·SIM | `scripts/STD_VLD_260917_std_company.py` | `standardize_company()`, `comparison_key()`, `SIM()`, `LEGAL_SUFFIXES` |
| 영문 표기·언어 생성 | `scripts/SIM_261002_translate.py` | `detect_and_translate()`, `_llm_translate()`, 휴리스틱·캐시·폴백 로그 |
| 배치 적재(①②) | `scripts/STD_VLD_260917_run_verification.py` | `process_row`에서 `standardize_company`→`detect_and_translate` 호출, 3개 컬럼 채움 |
| 업체명 게이트 | `scripts/SIM_260926_dedup.py` | `name_gate()`(SIM 재사용), `_to_rows()` |
| 언어별 비교·종합점수 | `app/backend/find_similar.py` | `score_pair()`(언어 분기), `_prep()`(name_eng/lang 보완) |
| 프론트 스키마/전송 | `app/frontend/src/lib/columns.ts`, `app/frontend/src/lib/api.ts` | 신규 2컬럼 등록·유사검색 전송 |
| 배포 설정 | `requirements-deploy.txt`(`openai`), `render.yaml`(`OPENAI_API_KEY`, `sync: false`) | 미설정 시 번역 자동 비활성(폴백) |

> 코어 로직(`scripts/*`)은 수정하지 않고, 언어별 비교 분기는 서비스 레이어
> (`find_similar.py`)에서만 처리한다.

---

## 7. 결과 변화 — Before / After

### 7-1. 불용어 제거 롤백 (업종 일반명사 보존)

| 업체명 | Before(업종명사 제거) | After(법인표기만) |
|---|---|---|
| `동탄 정밀 주식회사` | `동탄`(비교 불가) ❌ | `동탄 정밀` ✅ |
| `LT 메탈 Co.,Ltd.` | `LT`(과매칭) ❌ | `LT 메탈` ✅ |

### 7-2. 언어별 비교 (영문 폴백)

| 쿼리 | 기준 | Before | After |
|---|---|---|---|
| `경인화학`(ko) | `上海精密`(zh) | 글자 안 겹쳐 0점 | `Gyeongin Chemical` ↔ `Shanghai Precision` 비교로 정상 랭킹 ✅ |

---

## 8. 검증 포인트

1. **표준화(①):** `standardize_company('경인화학주식회사') == '경인화학'`,
   `'日本精密'`은 불변.
2. **롤백:** `comparison_key('동탄 정밀 주식회사')`에 "정밀"이 남는지(`'동탄정밀'`).
3. **번역(②):** 영어 입력은 LLM 미호출(`en`/원본), 한글 입력은 `ko` + 영문 표기.
   키 없음/오류 시 원본 폴백 + 경고 로그.
4. **언어별 비교(③):** 한글↔한글은 원표준명끼리, 한글↔중국어는 영문명끼리 비교되는지
   drawer 상세 랭킹으로 확인.
5. **회귀:** 영어 업체명은 LLM 미호출로 결정적, Mock/키 미설정 환경에서도 서비스 동작.

---

## 9. 주의사항

- **번역 비용·결정성:** 영어 업체명은 LLM을 건너뛰고, 동일 입력은 캐시로 재사용한다.
  배치의 중복 업체명이 많아 캐시 효과가 크다.
- **배포 키·패키지:** `OPENAI_API_KEY`(유효 키)와 `openai` 패키지가 **둘 다** 있어야
  번역이 활성화된다. 하나라도 없으면 조용히 원본 폴백한다(로그로 확인).
- **비교키는 저장하지 않는다:** `comparison_key`는 유사도 계산용 임시값이며, 저장
  컬럼은 원표기를 보존한 `STD 업체명`이다.
- **적용 범위:** `process_row` 한 곳으로 Standardization 메뉴와 Similarity Search의
  "확인할 데이터" 표준화 양쪽에 ①②가 반영된다.
