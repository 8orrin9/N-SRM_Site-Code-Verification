# 업체 주소 표준화 및 실재 검증 프로세스

## 0. 서브루틴 정의

반복되는 API 호출/판정 로직을 아래 5개 서브루틴으로 정의하고, A/B/C 케이스는 이를 조합하는 형태로 구성한다.

| 서브루틴 | 내용 | 출력 |
|---|---|---|
| **G**(query) | Geocoding API 실행 (업체명+주소 결합 문자열을 입력값으로 사용) | `found`, `address_std`(표준화된 주소), `coord_std`(표준 위/경도), `place_id_g`, `address_components_g` |
| **TS**(업체명, 중심좌표) | 좌표를 중심(locationBias)으로 하는 업체명 기반 TextSearch. 1차 실패 시 반경(locationBias)을 완화하여 1회 재시도 | `found`, `relaxed`(완화 재시도 여부), `place_id_t`, `coord_t`(검색된 업체의 실제 위/경도), `address_components_t` |
| **TSA**(업체명, 주소텍스트) | 좌표 없이 업체명+주소 텍스트를 결합해 TextSearch 실행. 실패 시 주소 레벨을 상위(광역)로 축약하여 1회 재시도 | `found`, `level`(상세/광역), `place_id_t`, `address_components_t` |
| **CMP**(id_1, id_2, coord_1, coord_2) | 두 후보(place_id, 좌표)를 비교하여 동일 업체 여부 판정 (아래 1장 참고) | `MATCH` / `PROXIMITY_MATCH` / `MISMATCH` |
| **RG**(좌표) | Reverse Geocoding으로 좌표에 대응하는 주소만 산출 (실재 검증 수단은 아니며, 다른 모든 방법이 실패했을 때의 최후 수단) | `address_rg`, `address_components_rg` |
| **SIM**(업체명, 후보명) | 비-임베딩 문자열 유사도로 두 업체명이 동일 업체인지 판정 (아래 1-1장 참고) | 유사도 점수 (0~1), `is_match`(임계치 이상 여부) |

> **TS/TSA의 `found` 정의**: `found = True`는 "① Places API가 place_id를 1건 이상 반환" AND "② 반환된 후보의 displayName과 입력 업체명(불용어 제거 기준) 간 `SIM` 유사도가 임계치 이상"을 모두 만족할 때로 정의한다. place_id 존재만으로는 `found = True`로 간주하지 않는다.

> **addressComponents 확보 원칙**: G/TS/TSA/RG 모두 FieldMask(또는 기본 응답)에 `address_components`/`addressComponents`를 포함해 함께 수신하며, 최종적으로 채택된 위치(서브루틴)의 addressComponents가 그 레코드의 표준 addressComponents로 확정된다. 소스별 스키마 차이는 1-3장의 정규화 매핑을 거쳐 통일된 구조로 저장한다.

---

## 1. CMP(Compare) 로직 상세

C 케이스에서 "표준좌표 기준 후보"와 "기존좌표 기준 후보"가 서로 다른 지점을 가리킬 때, 두 후보가 **같은 업체인지** 판정하기 위한 서브루틴.

**입력값**

| 파라미터 | 의미 |
|---|---|
| `G.place_id_g` | Geocoding API가 반환한 place_id (표준좌표 쪽) |
| `TS_old.place_id_t` | 기존좌표를 중심으로 TextSearch를 실행해 찾은 업체의 place_id |
| `G.coord_std` | 표준좌표 (Geocoding 결과의 위/경도) |
| `TS_old.coord_t` | TextSearch로 찾은 업체의 실제 위/경도 |

**판정 로직**

```
CMP(id_1, id_2, coord_1, coord_2):
    if id_1 == id_2:
        return MATCH                # place_id가 완전히 동일 → 확실히 같은 업체
    else:
        dist = Haversine(coord_1, coord_2)
        if dist ≤ 허용범위(예: 50m):
            return PROXIMITY_MATCH  # place_id는 다르지만 위치가 사실상 같은 자리
        else:
            return MISMATCH         # place_id도 다르고 위치도 멀리 떨어짐 → 다른 업체로 판단
```

**출력값 의미**

- **MATCH**: Geocoding이 반환한 place_id와 TextSearch가 반환한 place_id가 동일 → 완전히 동일한 업체로 확정
- **PROXIMITY_MATCH**: place_id 문자열은 다르지만(예: Geocoding은 "주소/건물" 단위 place_id를, TextSearch는 "그 안의 업체" 단위 place_id를 반환하는 등 ID 체계 차이), 두 지점 간 거리가 허용범위 이내 → 사실상 같은 자리로 판단
- **MISMATCH**: place_id도 다르고 거리도 허용범위를 벗어남 → 동명이업체 등 서로 다른 업체일 가능성

> 별도의 "Geocoding 결과가 업체(establishment) 단위로 매칭됐는지"를 사전 확인하는 단계는 두지 않는다. PROXIMITY_MATCH의 거리 폴백이 이 역할을 포함하므로, place_id 체계가 다르더라도 실제 위치가 가까우면 자동으로 구제된다.

---

## 1-1. SIM(Similarity) 로직 상세

Places API 응답의 `displayName`이 우리가 가진 업체명과 "동일 업체"로 볼 수 있는지 비-임베딩 방식으로 판정하는 서브루틴. Geocoding/TextSearch 요청·응답은 모두 영문(English)으로 설정하는 것을 전제로 하므로, 스크립트(언어) 불일치로 인한 문자 비교 실패는 고려하지 않는다.

**전제**: 두 문자열 모두 비교 전에 아래 정규화를 거친 상태(업체명_STD)라고 가정한다.
- 소문자 변환
- 법인형태 표기(Inc., Co., Ltd., Corp. 등) 및 지점/조직 구분자 등 불용어 제거
- 특수문자/여분 공백 제거

**판정 로직**: 아래 3개 지표를 계산해 최댓값을 최종 유사도로 사용한다.

| 지표 | 특징 | 대응하는 표기 차이 |
|---|---|---|
| Jaro-Winkler 유사도 | 문자 단위 비교, 짧은 접두어 일치에 가중치 | 오탈자, 약어 |
| Token Sort Ratio (토큰 정렬 후 Levenshtein 비율) | 단어를 정렬한 뒤 비교 | 어순 차이 |
| 문자 단위 Levenshtein 비율 | 전체 문자열 편집거리 기반 | 일반적인 표기 차이 |

```
SIM(업체명_STD, 후보명_STD):
    score = max(
        JaroWinkler(업체명_STD, 후보명_STD),
        TokenSortRatio(업체명_STD, 후보명_STD),
        LevenshteinRatio(업체명_STD, 후보명_STD)
    )
    is_match = score ≥ 임계치(예: 0.85, Golden Dataset으로 튜닝 필요)
    return score, is_match
```

> 임계치는 확정값이 아니며, Dirty/Golden Dataset 실측을 통해 조정한다.

---

## 1-2. 입력 전처리 — 영문 주소 + Local 주소 동시 입력 처리

주소 필드가 영문/현지어 2종으로 각각 존재하는 레코드에 한해, Case A/C의 **1단계(G 실행)를 아래 로직으로 대체**한다. 이는 별도의 "조기 종료" 단계가 아니라 **A/C의 이후 단계(2번 스텝 이하)로 무엇을 들고 진입할지를 결정하는 라우팅**이며, 최종 판정은 반드시 A/C의 나머지 단계를 거친 뒤 확정된다.

```
G_local = Geocoding(업체명 + Local 주소)
G_en    = Geocoding(업체명 + 영문 주소)

(a) 둘 다 성공
    result = CMP(G_local.place_id_g, G_en.place_id_g, G_local.coord_std, G_en.coord_std)

    - MATCH / PROXIMITY_MATCH
        → 두 결과가 사실상 같은 위치를 가리킴. 표준좌표를 하나로 합의(Local 우선 채택, 실패 시 영문)
        → 합의된 결과를 G로 간주하여 A(또는 C)의 "2. G.found = True" 단계로 정상 진입 (이후 절차는 원래 설계와 동일)

    - MISMATCH
        → 두 주소가 서로 다른 위치를 가리킴. G_local, G_en 각각을 독립적인 G로 간주해
          A(또는 C)의 "2. G.found = True" 단계부터 마지막 단계까지 **각각 완주**시켜
          두 개의 최종 결과 R_local, R_en(표준화 상태 + 사유코드 + place_id)을 만든다.
        → 두 결과를 아래 [통합 매트릭스]로 합쳐 이 레코드의 최종 표준화 상태를 확정한다.

(b) 한쪽만 성공
    → 성공한 쪽의 결과를 G로 채택해 A(또는 C)의 "2. G.found = True" 단계로 정상 진입 (신뢰도 낮음, 비고에 로그)

(c) 둘 다 실패
    → A(또는 C)의 "G.found = False" 분기(TSA)로 진입. Local 주소, 영문 주소 각각으로 TSA 시도
       - 어느 한쪽이라도 성공하면 채택 → "검증 완료"
       - 둘 다 실패하면 → "실패" (C는 이후 좌표 기반 폴백이 남아있으므로 해당 로직 계속 진행)
```

**[통합 매트릭스] MISMATCH 시 R_local × R_en 최종 판정**

MISMATCH는 G_local, G_en이 **둘 다 성공**한 상태에서만 발생하므로, R_local/R_en의 내부 판정은 각 Case의 "G.found = True" 서브트리 결과(검증 완료 또는 확인 필요)로만 한정되며 "실패" 상태는 이 매트릭스에 등장하지 않는다. ("둘 다 G 실패"는 아래 (c) 케이스로, 매트릭스와 무관하게 별도로 처리된다.)

| R_local \ R_en | 검증 완료 | 확인 필요 |
|---|---|---|
| **검증 완료** | place_id 재비교(CMP with TS 결과) → 동일/근접: **검증 완료**(`VERIFIED_ADDRESS_SOURCE_RESOLVED`, Local 우선 채택) / 상이: **확인 필요**(`UNVERIFIED_ADDRESS_SOURCE_CONFLICT`, 두 후보 모두 제시) | **검증 완료** (R_local의 내부 코드 그대로 채택, R_en 실패 사유는 비고에 로그) |
| **확인 필요** | **검증 완료** (R_en의 내부 코드 그대로 채택, R_local 실패 사유는 비고에 로그) | **확인 필요** (`UNVERIFIED_ADDRESS_SOURCE_CONFLICT`, 두 원인 모두 비고에 병기) |

> 표의 대각 반대 칸(검증완료 × 확인필요)은 좌우 대칭이며 표기를 생략함.
> "한쪽만 검증 완료"인 칸은 특수 코드로 대체하지 않고, 이긴 쪽의 내부 사유코드(예: `VERIFIED_GEOCODE_DIRECT`)를 최종 코드로 그대로 사용한다.

> 주소가 1개(영문 또는 현지어 단독)만 존재하는 레코드는 이 전처리를 거치지 않고 기존 Case A/C의 1단계(G 실행)를 그대로 수행한다.

---

## 1-3. addressComponents 스키마 정규화 매핑

G/RG(Geocoding API)와 TS/TSA(Places API 신규)는 응답 필드명 체계가 다르므로, 적재 전 아래 매핑을 거쳐 공통 스키마로 통일한다.

| 항목 | Geocoding API (G, RG) | Places API 신규 (TS, TSA) | 비고 |
|---|---|---|---|
| 유형(분류) | `types` (배열) | `types` (배열) | 필드명·값 체계 동일 → 변환 불필요 |
| 전체 명칭 | `long_name` | `longText` | 필드명만 상이 |
| 축약 명칭 | `short_name` | `shortText` | 필드명만 상이 |
| 언어코드 | 없음 (요청 파라미터로 응답 전체에 암묵 적용) | `languageCode` (컴포넌트별 개별 제공) | 레거시는 요청 시 지정한 언어값으로 대체 |

**공통 스키마**: 소스에 관계없이 아래 구조의 JSON 배열로 통일하여 저장한다.

```
[
  { "types": [...], "long_text": "...", "short_text": "...", "language_code": "en" },
  ...
]
```

- 원본 출처 추적을 위해 `source_api`(`geocoding` / `places_new`) 값을 레코드 단위로 함께 저장한다.
- 국가별 계층 깊이(administrative_area_level 단계 수) 차이는 정확매칭 시 Country 레벨에서 우선 걸러지므로 별도 보정 로직을 두지 않는다.

---

## 2. Case A — 주소 + 업체명이 존재하는 경우

```
0. (주소가 영문/현지어 2종 모두 존재하는 레코드에 한해) 1-2장의 전처리를 1단계(G 실행) 대신 수행
   - 합의(MATCH/PROXIMITY_MATCH) 또는 한쪽만 성공 → 그 결과를 G로 하여 아래 "2. G.found = True"로 진입
   - MISMATCH → Local/영문 각각 아래 "2" 이하를 완주 후 1-2장 [통합 매트릭스]로 최종 판정
   - 둘 다 실패 → 아래 "3. G.found = False"로 진입 (Local/영문 각각 TSA 시도)

1. G = Geocoding(업체명+주소)   ※ 주소가 1개인 레코드에 적용되는 기본 스텝
   ※ address_components_g 함께 수신 (1-3장 정규화 매핑 적용)

2. G.found = True
   2-1. TS = TextSearch(업체명, center = G.coord_std)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
   2-2. TS.found = True  → 표준화: "검증 완료"
        - 사유: VERIFIED_GEOCODE_DIRECT (1차 성공) / VERIFIED_GEOCODE_RELAXED (완화 후 성공)
        - place_id 기반 Google Maps URL 제공
   2-3. TS.found = False → 표준화: "확인 필요"
        - 사유: UNVERIFIED_NOT_FOUND
        - 검색 쿼리형 Google Maps URL 제공 (place_id 없음)

3. G.found = False
   3-1. TSA = TextSearchByAddressText(업체명, 주소)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
   3-2. TSA.found = True  → 표준화: "검증 완료"
        - 사유: VERIFIED_TEXTSEARCH_ADDR_TEXT
        - place_id 기반 Google Maps URL 제공
   3-3. TSA.found = False → 표준화: "실패"
        - 사유: FAILED_ALL_METHODS
        - (Geocoding, TextSearch 모두 실패하여 주소·좌표 어느 것도 확보하지 못함)
```

**addressComponents 확정 규칙**: 2-2 성공 시 `address_components_t`(TS 결과), 3-2 성공 시 `address_components_t`(TSA 결과)를 최종 채택한다. 2-3(확인 필요)은 `address_components_g`(G 결과)를 잠정 채택하되 비고에 미검증 표기, 3-3(실패)은 값 없음.

---

## 3. Case B — 좌표 + 업체명이 존재하는 경우

```
1. TS = TextSearch(업체명, center = 기존좌표)  ※ address_components_t 함께 수신
   ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치

2. TS.found = True → 표준화: "검증 완료"
   - 사유: VERIFIED_COORD_DIRECT (1차 성공) / VERIFIED_COORD_RELAXED (완화 후 성공)
   - place_id 기반 Google Maps URL 제공

3. TS.found = False
   3-1. RG = ReverseGeocode(기존좌표)  ※ address_components_rg 함께 수신
   3-2. 표준화: "확인 필요"
        - 사유: UNVERIFIED_REVERSE_GEOCODE_ONLY
        - (Reverse Geocoding으로 주소는 최소 확보하되, 실재 검증 자체는 불가)
```

**addressComponents 확정 규칙**: 2 성공 시 `address_components_t`, 3-2(확인 필요) 시 `address_components_rg`를 채택한다.

---

## 4. Case C — 주소 + 좌표 + 업체명이 모두 존재하는 경우

```
0. (주소가 영문/현지어 2종 모두 존재하는 레코드에 한해) 1-2장의 전처리를 1단계(G 실행) 대신 수행
   - 합의(MATCH/PROXIMITY_MATCH) 또는 한쪽만 성공 → 그 결과를 G로 하여 아래 "2. G.found = True"로 진입
   - MISMATCH → Local/영문 각각 아래 "2" 이하를 완주 후 1-2장 [통합 매트릭스]로 최종 판정
   - 둘 다 실패 → 아래 "3. G.found = False"로 진입 (Local/영문 각각 TSA 시도)

1. G = Geocoding(업체명+주소)   ※ 주소가 1개인 레코드에 적용되는 기본 스텝
   ※ address_components_g 함께 수신

2. G.found = True
   2-1. dist = Haversine(G.coord_std, 기존좌표)

   2-2. dist ≤ 허용범위 (위치 정합)
        TS = TextSearch(업체명, center = G.coord_std)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
        - TS.found = True  → 표준화: "검증 완료"
          사유: VERIFIED_GEOCODE_DIRECT / VERIFIED_GEOCODE_RELAXED
        - TS.found = False → 표준화: "확인 필요"
          사유: UNVERIFIED_NOT_FOUND

   2-3. dist > 허용범위 (위치 불일치)
        TS_old = TextSearch(업체명, center = 기존좌표)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치

        - TS_old.found = True
          result = CMP(G.place_id_g, TS_old.place_id_t, G.coord_std, TS_old.coord_t)
          - result = MATCH 또는 PROXIMITY_MATCH → 표준화: "검증 완료" (표준좌표 채택, address_components_g 채택)
            사유: VERIFIED_PLACEID_MATCH / VERIFIED_PROXIMITY_MATCH
          - result = MISMATCH → 표준화: "확인 필요" (표준·기존 두 후보의 addressComponents 모두 제시)
            사유: UNVERIFIED_PLACEID_MISMATCH

        - TS_old.found = False
          TS_std = TextSearch(업체명, center = G.coord_std)  ※ 2-2에서 미실행 시 여기서 수행, address_components_t 함께 수신
          ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
          - TS_std.found = True  → 표준화: "검증 완료" (기존좌표 신뢰도 낮음, 로그 기록. address_components_g 채택)
            사유: VERIFIED_GEOCODE_DIRECT / VERIFIED_GEOCODE_RELAXED
          - TS_std.found = False → 표준화: "확인 필요"
            사유: UNVERIFIED_NOT_FOUND

3. G.found = False
   3-1. TS_old = TextSearch(업체명, center = 기존좌표)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
   3-2. TS_old.found = True → 표준화: "검증 완료"
        사유: VERIFIED_COORD_DIRECT / VERIFIED_COORD_RELAXED
   3-3. TS_old.found = False
        3-3-1. TSA = TextSearchByAddressText(업체명, 주소)  ※ address_components_t 함께 수신
               ※ found = (place_id 존재) AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
        3-3-2. TSA.found = True  → 표준화: "검증 완료"
               사유: VERIFIED_TEXTSEARCH_ADDR_TEXT
        3-3-3. TSA.found = False
               RG = ReverseGeocode(기존좌표) → 표준화: "확인 필요"  ※ address_components_rg 함께 수신
               사유: UNVERIFIED_REVERSE_GEOCODE_ONLY
```

**addressComponents 확정 규칙**: 각 최종 상태에서 위 주석(※)에 표기된 소스의 addressComponents를 채택한다. 2-3의 MISMATCH만 예외적으로 두 소스(표준/기존)의 addressComponents를 모두 보존한다.

### 구조적 불변식

- **Case A만 최종적으로 "실패"에 도달할 수 있다.** 입력에 좌표가 없으므로, Geocoding과 TextSearch(텍스트 결합)가 모두 실패하면 위치 정보를 전혀 확보할 수 없다.
- **Case B, C는 원천적으로 "실패"에 도달하지 않는다.** 입력에 좌표가 이미 존재하므로, 다른 모든 방법이 실패해도 최소한 Reverse Geocoding으로 주소는 확보할 수 있어 "확인 필요"까지만 내려간다.

---

## 5. 사유 코드(Reason Code) 최종 버전

| 표준화 결과 | 사유 코드 | 해당 Case | 표준화 | 실재검증 | 비고 | Description | 사용자 Action |
|---|---|---|---|---|---|---|---|
| 검증 완료 | `VERIFIED_GEOCODE_DIRECT` | A, C | O | O | | 지오코딩 성공, 표준좌표 기준 TextSearch 1차 시도에서 업체 매칭 | 조치 불필요 — 표준값 그대로 site_db_std에 반영 |
| 검증 완료 | `VERIFIED_GEOCODE_RELAXED` | A, C | O | O | | 지오코딩 성공, 표준좌표 기준 TextSearch가 반경 완화 후 매칭 | 조치 불필요 — 단, 완화 재시도 건이므로 일부 샘플을 무작위 추출해 품질 점검 권장 |
| 검증 완료 | `VERIFIED_COORD_DIRECT` | B, C | O | O | 표준주소는 TS 결과에서 확보(G 미사용) | 지오코딩 없이(또는 실패), 기존좌표 기준 TextSearch 1차 시도에서 매칭 | 조치 불필요 — 표준값 그대로 site_db_std에 반영 |
| 검증 완료 | `VERIFIED_COORD_RELAXED` | B, C | O | O | 표준주소는 TS 결과에서 확보(G 미사용) | 기존좌표 기준 TextSearch가 반경 완화 후 매칭 | 조치 불필요 — 단, 완화 재시도 건이므로 일부 샘플을 무작위 추출해 품질 점검 권장 |
| 검증 완료 | `VERIFIED_TEXTSEARCH_ADDR_TEXT` | A, C | O | O | 표준주소는 TSA 결과에서 확보(G 실패) | 지오코딩 실패, 업체명+주소 텍스트 결합 TextSearch로 매칭 (주소 레벨 축약 포함) | 조치 불필요 — 단, 지오코딩이 실패했던 원본 주소 자체는 별도로 품질 개선 검토 권장 |
| 검증 완료 | `VERIFIED_PLACEID_MATCH` | C | O | O | | 표준·기존 좌표는 불일치했으나, 두 TextSearch 결과의 place_id가 동일 → 좌표 오차로 판단 | 조치 불필요 — 기존 좌표값 오류 가능성을 로그로만 남김 |
| 검증 완료 | `VERIFIED_PROXIMITY_MATCH` | C | O | O | | place_id는 다르지만 두 결과의 위치 간 거리가 허용범위 이내 → 동일 부지로 판단 | 조치 불필요 — 단, place_id 체계 차이로 자동 판정된 건이므로 일부 샘플 점검 권장 |
| 검증 완료 | `VERIFIED_ADDRESS_SOURCE_RESOLVED` | A, C | O | O | | 영문/현지어 주소를 각각 완주 검증한 결과, 두 후보 모두 검증 완료되었고 place_id도 동일/근접 → 표준으로 합의(Local 우선 채택) | 조치 불필요 — 표준값 그대로 site_db_std에 반영 |
| 확인 필요 | `UNVERIFIED_NOT_FOUND` | A, C | O | X | G(또는 TS_std)는 성공했으나 TS가 업체를 못 찾음 | 표준(또는 기존)좌표 기준 TextSearch를 반경 완화까지 포함해 시도했으나 업체 미발견 | 담당자가 제공된 검색 쿼리형 URL로 Google Maps에서 직접 검색해 업체 실재 여부 수동 확인 |
| 확인 필요 | `UNVERIFIED_PLACEID_MISMATCH` | C | O | O(충돌) | 실재검증 자체는 성공(TS_old가 업체를 찾음)했으나, G와 다른 업체로 판정되어 충돌 | 표준·기존 좌표 각각에서 서로 다른 업체(place_id)가 발견됨 → 동명이업체/위치오류 의심 | 담당자가 제시된 두 후보(표준좌표 후보 / 기존좌표 후보) 중 실제 업체를 직접 선택 |
| 확인 필요 | `UNVERIFIED_REVERSE_GEOCODE_ONLY` | B, C | O | X | RG는 표준화만 수행, 업체명 매칭이 없어 실재검증 불가 | 지오코딩·TextSearch 모두 실패, Reverse Geocoding으로 주소만 최소 확보 (실재 검증 불가) | 담당자가 처음부터 수동으로 업체 실재 여부를 확인 (자동 검증 근거 전무) |
| 확인 필요 | `UNVERIFIED_ADDRESS_SOURCE_CONFLICT` | A, C | O | O 또는 X (경로별 상이) | 둘 다 검증완료 후 place_id 충돌 시 실재검증 O(충돌) / 둘 다 미검증 시 실재검증 X | 영문/현지어 주소를 각각 완주 검증했으나, (양쪽 다 검증 완료이면서 place_id 상이) 또는 (양쪽 다 확인 필요) → 두 후보(및 원인) 모두 제시 | 담당자가 제시된 영문/현지어 두 후보 중 어느 쪽이 맞는지, 혹은 서로 다른 Site인지 확인 |
| 실패 | `FAILED_ALL_METHODS` | A | X | X | 좌표·주소 자원이 전혀 없어 표준화 자체가 안 됨 | 좌표 자원이 전혀 없는 상태(Case A)에서 지오코딩·TextSearch(텍스트결합, 광역화 포함) 모두 실패 | 담당자가 원본 주소·업체명 데이터 자체의 오류 여부를 원천(계약서 등)에서 재확인 후 재입력 요청 |

---

## 6. 산출물 컬럼 구성 (제안)

| 컬럼 | 내용 |
|---|---|
| 표준화 | 검증 완료 / 확인 필요 / 실패 (3단계) |
| 사유코드 | 위 5장의 코드값 (구조화된 값, 필터링/집계용) |
| 비고 | 판정 근거를 자유서술로 기재 (사람이 읽는 상세 설명) |
| 표준 주소 / 표준 위경도 | Geocoding 또는 TextSearch/Reverse Geocoding으로 확보한 최종 값 |
| **addressComponents** | 최종 채택된 표준 위치의 주소 구성요소(country, administrative_area_level_N, locality, route 등). 출처(G/TS/TSA/RG)에 따라 스키마(필드명)가 다르므로 적재 전 공통 스키마로 정규화 필요. "실패" 건은 값 없음 |
| **place_id** | 최종 채택된 place_id (검증 완료 시 존재, 확인 필요/실패는 NULL). 참조 URL 생성 및 향후 정확매칭 키로 활용 |
| 참조 URL | place_id 기반 Google Maps URL (검증 완료 시) 또는 검색 쿼리형 URL (확인 필요 시) |

> 업체명_STD(불용어 제거된 정규화 업체명)는 본 프로세스의 입력 전처리 단계에서 이미 생성되는 값으로 간주하며, 산출물에도 그대로 유지되어 다음 단계(중복/유사 Site 검색)의 매칭 키로 활용된다.
