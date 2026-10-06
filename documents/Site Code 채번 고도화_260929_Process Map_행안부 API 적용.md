# 행안부(Juso) 도로명주소 API 적용 프로세스

> 본 문서는 「Site Code 채번 고도화_260916_Process Map_주소 표준화 및 실재 검증」의 후속으로,
> **한국(KR) 주소를 도로명주소로 통일**하기 위해 행안부 도로명주소 검색 API를 주소 표준화
> 파이프라인에 어떻게 삽입했는지, 그로 인해 결과가 어떻게 달라지는지를 정리한다.
>
> **개정 이력(2026-10-02):** 초기 설계는 Geocoding *이전*에 행안부를 호출하는 **선(先)처리**
> 방식이었으나, 실재검증(Case C 등) 뒷단이 TextSearch POI의 주소로 `STD 주소`를 덮어써
> 지번/혼재 주소가 그대로 남는 문제가 확인되었다. 이에 **실재검증으로 `STD 주소`가 확정된
> *이후*에 행안부로 통일하는 후(後)처리 방식으로 전면 전환**했다. 본 문서는 후처리 설계를 기준으로 한다.

---

## 1. 배경 — 왜 행안부 API가 필요한가

한국의 주소체계는 **지번(地番)** 과 **도로명** 두 가지가 병존한다. 문제는 Google
Geocoding/Places API가 **출력 주소체계를 강제하는 파라미터를 제공하지 않는다**는 점이다.
채택되는 `formatted_address`는 입력이 지번이면 지번으로 남고, 실재검증 과정에서 TextSearch로
찾은 POI의 주소가 채택되면 **지번·혼재 표기**로 굳는다.

**실측 확인 사항:**

- Geocoding/Places에는 출력 체계를 도로명으로 강제하는 옵션이 없다.
- `language=ko` 파라미터는 **출력을 한글화할 뿐 지번↔도로명 변환은 하지 못한다.**
- 지번↔도로명 **주소체계 변환이 가능한 것은 행안부 API뿐**이다.
- `languageCode`를 지정하지 않으면 Google은 **번역 데이터가 있는 레벨만 영문, 세부 동(洞)은
  한글**로 조립해 **혼재 주소**를 만든다(예: `South Korea, …Yeongtong-gu, 원천동 471`).

> **메인 Geocoding은 KR이어도 language를 지정하지 않는다.** `RealMapsAdapter._geocode()`는
> `{"address": query}`만 넘기므로(`maps_adapter.py`), `STD 주소`의 **기본값**은 위의 혼재
> 표기 그대로다. "국가가 한국이면 Geocoding을 ko로 호출한다"는 분기는 **존재하지 않는다.**
> `verify_pipeline`을 타고 흐르는 `lang`(= `ko`)은 `adapter.G()`가 아니라 **`TS()`/`TSA()`에만**
> 전달되며, 그 용도도 "주소 표기 언어"가 아니라 **영어 업체명 매칭 실패 시 displayName을
> 현지어로 1회 재검색**하는 것이다(`maps_adapter.py` TS/TSA의 `if result is None and lang`).
> 따라서 혼재 표기는 **버그가 아니라 language 미지정의 당연한 결과**이며, 이를 한글 도로명으로
> 바로잡는 것이 아래 행안부 후처리의 역할이다(후처리 실패 시 이 혼재 표기가 폴백으로 남는다).

> **혼재 STD 주소는 행안부의 입력이 아니다.** 행안부에 넘기는 검색어는 혼재 `STD 주소`가 아니라
> `place_id`로 **별도 `language=ko` 재조회**(`address_ko`)한 순수 한글 주소에서 추출한다(4-2장).
> 즉 "STD 주소가 혼재라서 행안부가 실패한다"는 인과는 성립하지 않으며, 행안부 성패는 ko
> 재조회·검색어 추출·동명이동 교차검증 경로(4장)에 달려 있다.

| 실재검증 후 STD 주소(변환 없이) | 문제 |
|---|---|
| `South Korea, Incheon, Seo-gu, 가좌3동 548-1` | 지번 + 영/한 혼재 ❌ |
| `South Korea, Gyeonggi-do, Suwon, Yeongtong-gu, 원천동 471` | 지번 + 영/한 혼재 ❌ |

목표는 **최종 STD 주소를 한글 도로명주소로 통일**하는 것이다.

---

## 2. 결정사항 (사용자 확정, 2026-10-02)

| 항목 | 결정 |
|---|---|
| **적용 대상** | `국가/지역`이 KR **이면서 STD 주소가 확정된** 레코드 (한글 입력 여부 무관) |
| **적용 시점** | **실재검증 후(後)처리** — `STD 주소` 확정 이후 도로명으로 통일 |
| **깨끗한 한글 주소 확보** | 확정된 `place_id`(없으면 좌표)로 **`language=ko` Geocoding 재조회** |
| **행안부 검색 입력** | ko 주소에서 **시도·시군구·꼬리(건물명·층·호·국가코드)를 제거한 "동/도로명~번지"** |
| **동명이동 처리** | 후보 다건 조회 후 **시도 일치 필수 + 시군구 일치 선호**로 교차검증 채택 |
| **STD 주소 표기** | **한글 도로명**(괄호 참고항목 제거)으로 교체 |
| **컬럼 반영** | `도로명주소`/`지번주소` 컬럼에 행안부 원본 저장 |
| **실패/오류 시** | 기존 Google STD 주소로 폴백(파이프라인 중단 없음) |

> **"후처리"로 바꾼 이유**: 선처리는 Geocoding *입력*만 도로명으로 바꿀 뿐, Case C에서 좌표
> 정합 시 TextSearch POI의 `formattedAddress`가 `STD 주소`로 채택되는 뒷단 덮어쓰기를 막지
> 못한다. 최종 `STD 주소`가 확정된 뒤에 통일해야 지번/혼재가 남지 않는다.

> **`language=ko` 재조회가 필요한 이유**: 행안부 검색 API는 영문/혼재 주소를 매칭하지 못한다
> (실측). 확정된 place_id/좌표를 ko로 재조회하면 **전부 한글인 주소**를 얻어 행안부에 넘길 수 있다.

---

## 3. 행안부 API 서브루틴 — J(Juso)

기존 서브루틴(G/TS/TSA/CMP/RG/SIM)에 더해, 아래 **J** 서브루틴을 정의한다.

| 서브루틴 | 내용 | 출력 |
|---|---|---|
| **J**(keyword, count) | 행안부 도로명주소 검색 API 실행 (`addrLinkApi.do`). 지번/도로명 어느 keyword로 검색하든 응답의 `roadAddr`를 반환하며, **동명이동 교차검증을 위해 후보 다건**과 각 후보의 **시도(`siNm`)·시군구(`sggNm`)**를 함께 반환 | 후보 리스트: `road_addr`, `jibun_addr`, `zip_no`, `eng_addr`, `si_nm`, `sgg_nm` |

**API 사양**

- 엔드포인트: `GET https://business.juso.go.kr/addrlink/addrLinkApi.do`
- 파라미터: `confmKey`(승인키), `keyword`, `currentPage=1`, `countPerPage=N`, `resultType=json`
- 응답: `results.common.errorCode`(`"0"`=정상), `results.juso[]`에
  `roadAddr` / `jibunAddr` / `zipNo` / `engAddr` / `siNm` / `sggNm`
- 실패 처리: `errorCode != "0"`, `juso` 비어있음, 네트워크/타임아웃/파싱 예외 → **빈 리스트** 반환
  (호출부가 기존 Google STD 주소로 폴백)
- 좌표는 반환하지 않음 → **좌표·실재검증은 여전히 Geocoding/Places가 담당**

**클라이언트 메서드**

- `JusoClient.resolve_candidates(keyword, count=10)` → 후보 리스트(교차검증용, 신규)
- `JusoClient.resolve(keyword)` → `resolve_candidates(..., count=1)[0]` 래퍼(하위호환)

> **승인키 미설정 시**: `make_juso_client(None)` → 클라이언트 `None` → KR 후처리 자동 비활성.
> 기존 동작(Google STD 주소 그대로)으로 완전 폴백된다. 즉 **행안부 적용은 완전 옵트인(opt-in)**이다.

---

## 4. 파이프라인 삽입 위치 — 실재검증 결과 확정 직후

행안부 통일은 `process_row` 안에서 **Case A/B/C 실재검증이 끝나 `result`(VerifyResult)가
확정된 직후**에 수행된다. 기존 서브루틴/케이스 로직은 **일절 변경하지 않으며**, 확정된
`result.std_address`만 한글 도로명으로 교체한다.

```
process_row(row):
   case = pick_case(주소, 좌표)           ← (선처리 제거됨: 원본 주소로 바로 라우팅)
                              │
                              ▼
   ┌──────────── 기존 파이프라인 (변경 없음) ────────────┐
   │  Case A/B/C → G/TS/TSA/CMP/RG/SIM 수행              │
   │  → result (status/code/std_address/place_id/좌표)   │
   └─────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ [신규] 행안부 후처리 (KR AND result.std_address 있을 때만)     │
  │                                                               │
  │   if juso_client AND _is_kr(국가/지역) AND result.std_address: │
  │       ko = adapter.address_ko(place_id=result.place_id,       │
  │                               coord=(std_lat, std_lon))        │
  │       sido, sgg, keyword = _split_ko_address(ko)              │
  │       cands = J(keyword)                 ← 후보 다건           │
  │       pick  = _pick_by_region(cands, sido, sgg)  ← 교차검증     │
  │       if pick.road_addr:                                      │
  │           result.std_address = _strip_road_paren(road_addr)   │
  │           도로명주소 = pick.road_addr     ← 컬럼 저장(원본)    │
  │           지번주소   = pick.jibun_addr    ← 컬럼 저장(원본)    │
  └─────────────────────────────────────────────────────────────┘
```

### 4-1. KR 판정 — `_is_kr`

`국가/지역` 값이 한국인지 판정한다. `KR: 한국` 형식의 콜론 앞 코드뿐 아니라, `한국`처럼
**코드 없이 국가명으로만 적힌 경우도** KR로 인식한다.

```
_KR_ALIASES = {KR, KOR, 한국, 대한민국, SOUTH KOREA, KOREA, REPUBLIC OF KOREA}
```

### 4-2. 깨끗한 한글 주소 확보 — `adapter.address_ko`

확정된 `place_id`(우선, 없으면 `(표준 위도, 표준 경도)` 좌표)로 **`language=ko` Geocoding
재조회**해 순수 한글 주소를 얻는다. 혼재/영문 STD 주소를 그대로 행안부에 넘기면 매칭이
깨지므로(실측), 반드시 ko 재조회 결과를 쓴다.

| STD 주소(기본, 혼재) | `address_ko` 재조회(한글) |
|---|---|
| `South Korea, Incheon, Seo-gu, 가좌3동 548-1` | `대한민국 인천광역시 서구 가좌동 548-1` |

> `RealMapsAdapter`만 실제 ko Geocoding을 수행하며, Mock/기타 어댑터는 `None`을 반환해
> 후처리가 자동 스킵된다(mock 회귀 영향 없음).

### 4-3. 행안부 검색어 추출 — `_split_ko_address`

행안부 검색 API는 **(a) 시도·시군구를 앞에 붙이거나 (b) 번지 뒤 건물명·층·호·국가코드
꼬리가 붙으면 매칭이 깨진다**(실측). 따라서 ko 주소를 세 부분으로 분해한다:

```
'대한민국 인천광역시 서구 가좌동 548-1'
   → sido='인천광역시', sgg=['서구'], keyword='가좌동 548-1'

'대한민국 경기도 화성시 석우동 삼성1로5길 6 원희캐슬동탄 10층 KR'
   → sido='경기도', sgg=['화성시'], keyword='석우동 삼성1로5길 6'   (꼬리 제거)
```

- 선두 **국가명 접두(`대한민국`/`한국`) 제거** — 안 떼면 행안부 매칭 실패(실측).
- **시도**(첫 토큰), **시군구**(동/도로명 전까지의 `…시/군/구` 토큰) 수집 → 교차검증용.
- **검색어**: 동/도로명 시작 토큰(`…동|읍|면|리|가|로|길`)부터 **번지/건물번호
  (`숫자[-숫자][번지]`) 하나까지**만. 그 뒤 상세(건물명·층·호·국가코드)는 버린다.

| keyword(검색어) | 행안부 매칭 |
|---|---|
| `석우동 삼성1로5길 6 원희캐슬동탄 10층 KR` (꼬리 포함) | ❌ 0건 |
| `석우동 삼성1로5길 6` (꼬리 제거) | ✅ |
| `인천광역시 서구 가좌동 548-1` (시도·시군구 포함) | ❌ |
| `가좌동 548-1` (동+지번만) | ✅ |

### 4-4. 동명이동 교차검증 — `_pick_by_region`

동+지번만으로 검색하면 **같은 이름의 동이 여러 시군구에 존재**해 오매칭 위험이 있다.
후보를 다건 조회한 뒤 **ko 주소의 시도·시군구로 교차검증**해 올바른 후보를 고른다.

- **시도 일치 필수**: `siNm`이 ko 시도와 같은 후보만 남긴다. 없으면 변환 실패(STD 주소 유지).
- **시군구 일치 선호**: 남은 후보 중 시군구가 일치하면 우선 채택, 없으면 시도만 맞는 첫 후보.
  - 행안부 `sggNm`은 `수원시 영통구`처럼 합쳐진 형태 → **부분 포함(⊇)** 으로 비교.
  - **시군구는 "필수"가 아님**: ko 주소와 행안부의 시군구 **명칭이 다를 수 있다**
    (예: 인천 **서구 → 서해구** 명칭 변경). 시도만 필수로 보아 이런 케이스를 수용한다.

### 4-5. 괄호 참고항목 제거 — `_strip_road_paren`

행안부 `roadAddr`는 끝에 **괄호 참고항목**(법정동·건물명)을 붙여 반환한다.
예: `서울특별시 강동구 천호대로167길 26 (천호동, 하이브2)`

`STD 주소`에는 **순수 도로명만** 남기고(괄호 제거), **`도로명주소` 컬럼에는 행안부
원본(괄호 포함)을 그대로** 보존한다.

| 용도 | 값 |
|---|---|
| `STD 주소` | `서울특별시 강동구 천호대로167길 26` (괄호 제거) |
| `도로명주소` 컬럼 | `서울특별시 강동구 천호대로167길 26 (천호동, 하이브2)` (원본 보존) |

---

## 5. 결과 변화 — Before / After

실호출 검증 결과:

### Before (행안부 미적용 — 혼재/지번 STD)

| 레코드 | STD 주소 |
|---|---|
| LT Metal | `South Korea, Incheon, Seo-gu, 가좌3동 548-1` ❌ |
| AUTO SENSOR KOREA | `South Korea, …Yeongtong-gu, 원천동 471` ❌ |

### After (행안부 후처리 적용 — 한글 도로명 통일)

| 레코드 | STD 주소 | 도로명주소 | 비고 |
|---|---|---|---|
| LT Metal | `인천광역시 서해구 가재울로 14` ✅ | `…가재울로 14 (가좌동)` | 서구→**서해구** 명칭변경 반영 |
| AUTO SENSOR KOREA | `경기도 수원시 영통구 중부대로448번길 97` ✅ | `…97 (원천동)` | |
| HANA TECH | `서울특별시 서초구 언남16길 12` ✅ | `…12 (양재동)` | 지번→도로명 |
| 제일써보테크 | `경기도 부천시 원미구 도약로308번길 33` ✅ | | |

**핵심 효과: 지번/혼재 어느 형태로 나오든 최종 STD 주소가 한글 도로명으로 수렴한다.**

### 신규 산출물 컬럼

| 컬럼 | 내용 |
|---|---|
| **도로명주소** | 행안부가 반환한 한글 도로명주소 원본(괄호 참고항목 포함). 변환 성공 시에만 채움 |
| **지번주소** | 행안부가 반환한 한글 지번주소. 변환 성공 시에만 채움 |

> `STD 주소`는 실재검증(G/TS/TSA)에서 확정된 뒤 **행안부 후처리가 한글 도로명으로 교체**한다.
> 사유코드·실재검증·좌표 로직에는 관여하지 않는다(변환 실패 시 Google STD 주소 그대로 유지).

---

## 6. 구현 매핑 (코드 위치)

| 구성요소 | 파일 | 역할 |
|---|---|---|
| 행안부 클라이언트 (`J` 서브루틴) | `scripts/STD_VLD_260929_juso_adapter.py` | `JusoClient.resolve_candidates()`(다건+시도/시군구), `resolve()`(래퍼), `make_juso_client()` |
| ko 재조회 (`address_ko`) | `scripts/STD_VLD_260917_maps_adapter.py` | `MapsAdapter.address_ko()`(기본 None), `RealMapsAdapter.address_ko()`(language=ko Geocoding) |
| 후처리 훅 + 헬퍼 | `scripts/STD_VLD_260917_run_verification.py` | `process_row` 내 후처리 블록, `_unify_kr_road`/`_split_ko_address`/`_pick_by_region`/`_strip_country_prefix`/`_strip_road_paren`/`_is_kr`, `BASE_COLUMNS`에 컬럼 2개 |
| 웹 경로 주입 | `app/backend/services/verify_service.py` | `_get_juso_client()`(지연 생성+캐시), `process_row(row, adapter, juso)` |
| 승인키 설정 | `.env`, `render.yaml`(`JUSO_CONFM_KEY`, `sync: false`) | 미설정 시 자동 비활성 |

> 코어 로직(G/TS/TSA/CMP/RG/SIM 및 Case A/B/C)은 **수정하지 않았다.** 행안부는
> 코어와 분리된 얇은 후처리 레이어로, 확정된 `result.std_address`만 교체한다.
> (`address_ko`는 어댑터 인터페이스에 추가된 조회 메서드로, 기존 서브루틴 동작은 불변.)

---

## 7. 검증 결과

1. **실호출(혼재/지번→한글 도로명):** LT Metal/AUTO SENSOR/HANA TECH/제일써보테크 모두
   한글 도로명으로 수렴 ✅
2. **동명이동 교차검증:** 시도 일치 필수로 타 지역 오매칭 차단, 시군구 명칭변경
   (서구→서해구) 케이스 수용 ✅
3. **꼬리 제거:** 건물명·층·호·국가코드가 붙은 ko 주소에서 "동/도로명~번지"만 추출해 매칭 ✅
4. **회귀(폴백):**
   - `juso_client=None`(승인키 미설정) → 도로명/지번 공란, 기존 Google STD 주소와 동일 ✅
   - 비KR 레코드(중국/싱가포르 등) → 행안부 미호출, 원본 유지 ✅
   - Mock 어댑터(`address_ko=None`) → 후처리 자동 스킵, mock 회귀 동일 ✅
   - 시도 일치 후보 없음/행안부 오류 → STD 주소 그대로 유지 ✅

---

## 8. 주의사항

- **내부망 차단 가능성:** 행안부 API는 일부 내부망에서 차단될 수 있다. 배포 환경(Render 등)에서
  접근 가능 여부를 확인해야 한다. 차단/오류 시 후보 조회가 빈 리스트를 반환해 기존 Google
  STD 주소로 자동 폴백된다.
- **승인키 배포:** `JUSO_CONFM_KEY`는 `.env`(로컬)와 Render 대시보드(배포) **양쪽에** 입력해야
  배포 환경에서 도로명 변환이 활성화된다. (`render.yaml`은 `sync: false`로 키 이름만 선언)
- **KR 레코드당 Google 호출 1회 추가:** 후처리의 `address_ko`(language=ko Geocoding)가
  KR·STD 주소 보유 레코드마다 1회 발생한다(실재검증 호출과 별개).
- **적용 범위:** `process_row` 한 곳 수정으로 **Standardization 메뉴**와 **Similarity Search의
  "확인할 데이터" 표준화** 양쪽에 반영된다(둘 다 `/api/standardize` 경로를 공유).
