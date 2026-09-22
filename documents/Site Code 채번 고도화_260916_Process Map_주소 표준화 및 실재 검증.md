# 업체 주소 표준화 및 실재 검증 프로세스

## 0. 서브루틴 정의

반복되는 API 호출/판정 로직을 아래 5개 서브루틴으로 정의하고, A/B/C 케이스는 이를 조합하는 형태로 구성한다.

| 서브루틴 | 내용 | 출력 |
|---|---|---|
| **G**(query) | Geocoding API 실행 (**주소 문자열만** 입력값으로 사용 — 업체명은 제외) | `found`, `address_std`(표준화된 주소), `coord_std`(표준 위/경도), `place_id_g`, `address_components_g`, **`location_type`**(좌표 정밀도) |
| **TS**(업체명, 중심좌표, precise) | 좌표를 중심(locationBias)으로 하는 업체명 기반 TextSearch. 1차 실패 시 반경(locationBias)을 완화하여 1회 재시도. **`precise=True`(정밀 지오코딩 좌표)면 이름 매칭 실패 시 좌표 근접 보강(0-1장) 수행** | `found`, `relaxed`(완화 재시도 여부), **`proximity`(좌표 근접 보강 매칭 여부)**, `place_id_t`, `coord_t`(검색된 업체의 실제 위/경도), `address_components_t` |
| **TSA**(업체명, 주소텍스트) | 좌표 없이 업체명+주소 텍스트를 결합해 TextSearch 실행. 실패 시 주소 레벨을 상위(광역)로 축약하여 1회 재시도 | `found`, `level`(상세/광역), `place_id_t`, `address_components_t` |
| **CMP**(id_1, id_2, coord_1, coord_2) | 두 후보(place_id, 좌표)를 비교하여 동일 업체 여부 판정 (아래 1장 참고) | `MATCH` / `PROXIMITY_MATCH` / `MISMATCH` |
| **RG**(좌표) | Reverse Geocoding으로 좌표에 대응하는 주소만 산출 (실재 검증 수단은 아니며, 다른 모든 방법이 실패했을 때의 최후 수단) | `address_rg`, `address_components_rg` |
| **SIM**(업체명, 후보명) | 비-임베딩 문자열 유사도로 두 업체명이 동일 업체인지 판정 (아래 1-1장 참고) | 유사도 점수 (0~1), `is_match`(임계치 이상 여부) |

> **G 입력에서 업체명을 제외하는 이유**: Geocoding에 "업체명+주소"를 결합해 넣으면 파서가 상호명 토큰에 이끌려 좌표를 도시 레벨(APPROXIMATE)로 떨어뜨리는 현상이 실측으로 확인되었다. 순수 주소만 입력하면 도로/번지 레벨의 정밀 좌표를 얻을 확률이 높아지므로, G는 주소 문자열만 사용한다. (실재 검증에 필요한 업체명 매칭은 TS/TSA가 담당)

> **G의 `location_type`(좌표 정밀도)**: Geocoding 응답의 `geometry.location_type`으로, 반환 좌표가 얼마나 정밀한지를 나타낸다. `ROOFTOP`/`RANGE_INTERPOLATED`/`GEOMETRIC_CENTER`는 도로·번지 레벨의 **정밀** 좌표, `APPROXIMATE`는 도시·구역 중심의 **부정확** 좌표다. 이 값에 따라 뒤 단계의 거리 게이트·CMP·표준좌표 채택이 분기한다(0-2장 참고).

> **TS/TSA의 `found` 정의**: `found = True`는 "① Places API가 place_id를 1건 이상 반환" AND "② 반환된 후보의 displayName과 입력 업체명(불용어 제거 기준) 간 `SIM` 유사도가 임계치 이상" AND "③ 후보가 실재 업체(POI)일 것 — `locality`/`sublocality`/`political`/`administrative_area_level_N`/`postal_code`/`country` 등 행정구역 타입은 제외"를 모두 만족할 때로 정의한다. place_id 존재만으로는 `found = True`로 간주하지 않는다. (③의 근거: 업체명 접두사가 도시·성 이름과 겹칠 때 — 예 'SUZHOU POSTEL'→'Suzhou' — TextSearch가 도시 자체를 반환하고 SIM이 접두사 유사도로 오매칭하는 것을 차단)
>
> **단, TS의 `precise=True` 경로에서는 예외**: 정밀 지오코딩 좌표에 근접한 유일 POI는 ②(SIM 임계치)를 만족하지 못해도 `found=True`로 인정한다(0-1장 좌표 근접 보강). 교차언어 표기 차이로 SIM이 낮은 실재 업체를 좌표로 구제하기 위함이다.

> **addressComponents 확보 원칙**: G/TS/TSA/RG 모두 FieldMask(또는 기본 응답)에 `address_components`/`addressComponents`를 포함해 함께 수신하며, 최종적으로 채택된 위치(서브루틴)의 addressComponents가 그 레코드의 표준 addressComponents로 확정된다. 소스별 스키마 차이는 1-3장의 정규화 매핑을 거쳐 통일된 구조로 저장한다.

---

## 0-1. 좌표 근접 보강 (TS의 `precise` 경로)

업체명 유사도(SIM)만으로는 **교차언어(CJK ↔ 라틴) 표기 차이**를 넘지 못해, 실재하는 업체를 놓치는 문제가 실측으로 확인되었다. Google Places의 `displayName`은 Google이 보유한 표기(현지어 등)로 반환되며 요청 언어(`languageCode`)로 강제 영문화되지 않는다(예: 'LT Metal' 입력 ↔ 'LT메탈 주안공장' 반환, SIM 0.51 / '达成包装制品' 입력 ↔ 'Dacheng Packing Products' 반환, SIM 0.00).

이를 좌표로 우회한다. **G가 정밀 좌표(0-2장)를 반환한 경우, 그 좌표는 곧 "그 주소의 정확한 위치"** 이므로, 다음 조건을 모두 만족하는 후보는 SIM 임계치 미달이어도 실재 업체로 인정한다(`found=True`, `proximity=True`).

```
좌표 근접 보강 성립 조건:
  ① G.location_type 이 정밀(APPROXIMATE 아님)      ← 앵커 좌표를 신뢰할 수 있을 때만
  ② TS 후보(POI) 중 G.coord_std 로부터 근접반경(예: 100m) 이내
  ③ 그 근접 후보가 유일(1건)                        ← 한 좌표에 복수 POI면 오인 방지
```

- **근접반경 근거**: 실측상 진짜 업체는 17·27·32m, 이름만 비슷한 오매칭은 22km 이상으로 뚜렷이 갈렸다. 100m는 "같은 부지" 판정에 충분하며, 확정값이 아니라 Golden Dataset으로 튜닝한다.
- **유일성 조건**: 한 정밀 좌표 반경 내에 여러 업체(예: 복합 빌딩)가 잡히면 어느 것인지 특정할 수 없으므로 보강을 적용하지 않고 일반 경로(SIM 매칭)로만 판정한다.
- 이 경로로 매칭된 건은 사유코드 `VERIFIED_GEOCODE_PROXIMITY`로 구분 기록한다(5장).

---

## 0-2. Geocoding 정밀도(location_type) 기반 프로세스 분기

G가 반환하는 `location_type`(0장)에 따라, **동일한 Case A/C의 뒤 단계라도 좌표를 신뢰하는 방식이 달라진다.** 도로/번지 주소를 Google이 찾지 못하면 도시·구역 중심을 `APPROXIMATE`로 반환하는데(예: 'FUTE NORTH ROAD…'→'Shanghai', '1 San Qian Road…'→'Suzhou'), 이 부정확한 좌표를 정밀 좌표와 똑같이 취급하면 실재 업체를 놓치거나(재현율 손실) 엉뚱한 판정을 내린다.

| G 정밀도 | 좌표의 의미 | 거리 게이트 | 표준좌표 채택 | Case C의 CMP |
|---|---|---|---|---|
| **정밀** (ROOFTOP / RANGE_INTERPOLATED / GEOMETRIC_CENTER) | 도로·번지 레벨로 정확 | **ON** — TS 매칭 POI가 G 좌표에서 게이트 반경(예: 2km)을 벗어나면 이름만 비슷한 **오매칭**으로 보고 무효화 | G.coord_std(정밀) | 정상 수행(G를 대등한 증인으로) |
| **APPROXIMATE** | 도시·구역 중심(부정확) | **OFF** — 진짜 업체가 도시 중심에서 수 km 떨어진 것이 정상이므로 거리로 거르지 않음 | TS가 찾은 실제 POI 좌표(`coord_t`) | **생략** — G의 place_id/좌표는 "어느 업체인지"의 증인이 될 수 없어 거부권(veto) 박탈 |

**(a) 거리 게이트** — 정밀 G에서만 작동하는 오매칭 차단 장치. 정밀 좌표는 "그 주소의 정확한 위치"이므로, 업체명으로 찾은 TS 결과가 거기서 멀리 떨어져 있으면 이름만 유사한 다른 업체(오매칭)로 판단해 `found`를 무효화한다.
- 예: 'SUZHOU POSTEL'(G=ROOFTOP, 利达路4号) → TS가 13km 밖 'Suzhou Postal Hub'(postel↔postal 유사) 반환 → 게이트 탈락 → 오매칭 차단, `확인 필요` + 정확한 G 주소 유지.

**(b) APPROXIMATE 시 게이트 OFF + TS 좌표 채택** — G 좌표 자체가 도시 중심이라 앵커로 쓸 수 없으므로, 거리 게이트를 끄고 TS가 찾은 실제 POI의 좌표를 표준좌표로 채택한다.
- 예: 'Suzhou Kematek'(G=APPROXIMATE, Suzhou 중심) → TS가 17km 밖 실제 Kematek 반환 → 게이트 통과 → `검증 완료`, TS 실좌표 채택.

**(c) APPROXIMATE 시 CMP 거부권 박탈(Case C)** — 4장 2-3 참고. 도시레벨 G의 place_id를 기존좌표 TS 결과와 대등 비교하면 진짜 업체가 `MISMATCH`로 기각되므로, APPROXIMATE면 CMP를 생략하고 기존좌표 TS 결과를 채택한다.

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

Places API 응답의 `displayName`이 우리가 가진 업체명과 "동일 업체"로 볼 수 있는지 비-임베딩 방식으로 판정하는 서브루틴.

> **언어(스크립트) 불일치 문제**: 당초 "요청·응답을 모두 영문으로 설정하면 언어 불일치는 없다"고 전제했으나, 실측 결과 **이 전제는 성립하지 않는다.** Google Places의 `displayName`은 Google이 보유한 표기로 반환되며, 요청 언어(`languageCode=en`)로 강제 영문화되지 않는다(예: 'LT Metal'↔'LT메탈 주안공장', '达成包装制品'↔'Dacheng Packing Products'). 따라서 원 언어/표기를 보존한 채 SIM을 계산하되, **교차언어로 SIM이 임계치에 못 미치는 실재 업체는 좌표 근접 보강(0-1장)으로 구제**한다. SIM 알고리즘 자체는 언어 통일을 시도하지 않는다.

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
G_local = Geocoding(Local 주소)      ※ 업체명 제외(0장 참고)
G_en    = Geocoding(영문 주소)        ※ 업체명 제외

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
| 언어코드 | 없음 (요청 파라미터로 응답 전체에 암묵 적용) | `languageCode` (컴포넌트별 개별 제공) | 응답 언어를 지정하지 않고 원문(현지 표기)으로 수신하므로, Geocoding 측은 응답에 실린 표기 언어를 그대로 기록(없으면 null) |

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

1. G = Geocoding(주소)   ※ 업체명 제외(0장). 주소가 1개인 레코드에 적용되는 기본 스텝
   ※ address_components_g, location_type 함께 수신 (1-3장 정규화 매핑 적용)

2. G.found = True
   precise = (G.location_type ≠ APPROXIMATE)     ※ 좌표 정밀 여부(0-2장)
   2-1. TS = TextSearch(업체명, center = G.coord_std, precise)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND POI 타입 AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
        ※ precise=True면 SIM 미달이어도 좌표 근접 유일 POI를 보강 수용(0-1장, proximity=True)
   2-2. TS.found = True  AND 거리 게이트 통과 → 표준화: "검증 완료"
        ※ 거리 게이트(0-2a): precise일 때만 적용. TS 매칭 POI가 G 좌표에서 게이트 반경 밖이면 오매칭으로 무효화(→ 2-3)
        - 사유: VERIFIED_GEOCODE_DIRECT (1차 성공) / VERIFIED_GEOCODE_RELAXED (완화 후 성공)
                / VERIFIED_GEOCODE_PROXIMITY (좌표 근접 보강으로 매칭, 0-1장)
        - 표준좌표: precise면 G.coord_std, APPROXIMATE면 TS.coord_t 채택(0-2b)
        - place_id 기반 Google Maps URL 제공
   2-3. TS.found = False (또는 거리 게이트 탈락) → TSA 병행 보강
        TSA = TextSearchByAddressText(업체명, 주소)  ※ 안전망: 좌표로는 못 찾았으나 주소텍스트로 실재 확인되는 경우 구제
        - TSA.found = True  → 표준화: "검증 완료" (사유: VERIFIED_TEXTSEARCH_ADDR_TEXT)
        - TSA.found = False → 표준화: "확인 필요" (사유: UNVERIFIED_NOT_FOUND)
          · 검색 쿼리형 Google Maps URL 제공 (place_id 없음), address_components_g(상세) 채택

3. G.found = False
   3-1. TSA = TextSearchByAddressText(업체명, 주소)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND POI 타입 AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치
   3-2. TSA.found = True  → 표준화: "검증 완료"
        - 사유: VERIFIED_TEXTSEARCH_ADDR_TEXT
        - place_id 기반 Google Maps URL 제공
   3-3. TSA.found = False → 표준화: "실패"
        - 사유: FAILED_ALL_METHODS
        - (Geocoding, TextSearch 모두 실패하여 주소·좌표 어느 것도 확보하지 못함)
```

**addressComponents 확정 규칙**: 2-2 성공 시 `address_components_t`(TS 결과), 3-2 성공 시 `address_components_t`(TSA 결과)를 최종 채택한다. 2-3(확인 필요)은 `address_components_g`(G 결과)를 잠정 채택하되 비고에 미검증 표기, 3-3(실패)은 값 없음.

**표준 주소 선택 규칙**: 2-2(TS 매칭 성공)의 표준 주소는 TS/G 중 무조건 한쪽이 아니라, **addressComponents 개수가 더 많은(더 상세한) 쪽**을 채택한다. 실재 POI가 등재된 경우 대개 TS가 상세하나(도로+번지), 업체 미등재로 상위 행정구역이 잡히면 G(주소 파싱)가 더 상세할 수 있어 상세도를 기준으로 고른다.

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

1. G = Geocoding(주소)   ※ 업체명 제외(0장). 주소가 1개인 레코드에 적용되는 기본 스텝
   ※ address_components_g, location_type 함께 수신

2. G.found = True
   precise = (G.location_type ≠ APPROXIMATE)     ※ 좌표 정밀 여부(0-2장)
   2-1. dist = Haversine(G.coord_std, 기존좌표)

   2-2. dist ≤ 허용범위 (위치 정합)
        TS = TextSearch(업체명, center = G.coord_std, precise)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND POI 타입 AND SIM ≥ 임계치 (precise면 좌표 근접 보강 포함, 0-1장)
        - TS.found = True AND 거리 게이트 통과 → 표준화: "검증 완료"
          사유: VERIFIED_GEOCODE_DIRECT / VERIFIED_GEOCODE_RELAXED / VERIFIED_GEOCODE_PROXIMITY
        - TS.found = False (또는 게이트 탈락) → 표준화: "확인 필요"
          사유: UNVERIFIED_NOT_FOUND

   2-3. dist > 허용범위 (위치 불일치)
        TS_old = TextSearch(업체명, center = 기존좌표)  ※ address_components_t 함께 수신
        ※ found = (place_id 존재) AND POI 타입 AND SIM(업체명_STD, 후보명_STD).is_match ≥ 임계치

        - TS_old.found = True
          [G가 APPROXIMATE인 경우] → CMP 생략(거부권 박탈, 0-2c) → 표준화: "검증 완료"
            · 도시레벨 G의 place_id는 '어느 업체인지'의 증인이 될 수 없으므로 비교하지 않고,
              기존좌표 TS_old가 찾은 실제 POI를 채택(TS_old.coord_t / address_components_t)
            · 사유: VERIFIED_COORD_DIRECT / VERIFIED_COORD_RELAXED
          [G가 정밀인 경우] → result = CMP(G.place_id_g, TS_old.place_id_t, G.coord_std, TS_old.coord_t)
          - result = MATCH 또는 PROXIMITY_MATCH → 표준화: "검증 완료" (표준좌표 채택, address_components_g 채택)
            사유: VERIFIED_PLACEID_MATCH / VERIFIED_PROXIMITY_MATCH
          - result = MISMATCH → 표준화: "확인 필요" (표준·기존 두 후보의 addressComponents 모두 제시)
            사유: UNVERIFIED_PLACEID_MISMATCH

        - TS_old.found = False
          TS_std = TextSearch(업체명, center = G.coord_std, precise)  ※ 2-2에서 미실행 시 여기서 수행, address_components_t 함께 수신
          ※ found = (place_id 존재) AND POI 타입 AND SIM ≥ 임계치 (precise면 좌표 근접 보강 포함, 0-1장)
          - TS_std.found = True AND 거리 게이트 통과 → 표준화: "검증 완료" (기존좌표 신뢰도 낮음, 로그 기록)
            · 표준좌표: precise면 G.coord_std, APPROXIMATE면 TS_std.coord_t 채택(0-2b)
            사유: VERIFIED_GEOCODE_DIRECT / VERIFIED_GEOCODE_RELAXED / VERIFIED_GEOCODE_PROXIMITY
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
| 검증 완료 | `VERIFIED_GEOCODE_PROXIMITY` | A, C | O | O | 업체명 유사도(SIM)는 임계치 미달이나 정밀 좌표 근접으로 실재 확인 | 지오코딩이 정밀 좌표(비-APPROXIMATE)를 반환하고, 그 좌표 근접반경 내 유일 POI가 존재 → 교차언어 등 표기 차이로 이름은 안 맞아도 '그 주소에 있는 업체'로 판단(0-1장) | 조치 불필요 — 단, 이름 유사도가 아닌 위치로 판정한 건이므로 일부 샘플을 추출해 업체명 대응 관계 점검 권장 |
| 검증 완료 | `VERIFIED_COORD_DIRECT` | B, C | O | O | 표준주소는 TS 결과에서 확보(G 미사용) | 지오코딩 없이(또는 실패), 기존좌표 기준 TextSearch 1차 시도에서 매칭 | 조치 불필요 — 표준값 그대로 site_db_std에 반영 |
| 검증 완료 | `VERIFIED_COORD_RELAXED` | B, C | O | O | 표준주소는 TS 결과에서 확보(G 미사용) | 기존좌표 기준 TextSearch가 반경 완화 후 매칭 | 조치 불필요 — 단, 완화 재시도 건이므로 일부 샘플을 무작위 추출해 품질 점검 권장 |
| 검증 완료 | `VERIFIED_TEXTSEARCH_ADDR_TEXT` | A, C | O | O | 표준주소는 TSA 결과에서 확보(G 실패) | 지오코딩 실패, 업체명+주소 텍스트 결합 TextSearch로 매칭 (주소 레벨 축약 포함) | 조치 불필요 — 단, 지오코딩이 실패했던 원본 주소 자체는 별도로 품질 개선 검토 권장 |
| 검증 완료 | `VERIFIED_PLACEID_MATCH` | C | O | O | | 표준·기존 좌표는 불일치했으나, 두 TextSearch 결과의 place_id가 동일 → 좌표 오차로 판단 | 조치 불필요 — 기존 좌표값 오류 가능성을 로그로만 남김 |
| 검증 완료 | `VERIFIED_PROXIMITY_MATCH` | C | O | O | | place_id는 다르지만 두 결과의 위치 간 거리가 허용범위 이내 → 동일 부지로 판단 | 조치 불필요 — 단, place_id 체계 차이로 자동 판정된 건이므로 일부 샘플 점검 권장 |
| 검증 완료 | `VERIFIED_ADDRESS_SOURCE_RESOLVED` | A, C | O | O | | 영문/현지어 주소를 각각 완주 검증한 결과, 두 후보 모두 검증 완료되었고 place_id도 동일/근접 → 표준으로 합의(Local 우선 채택) | 조치 불필요 — 표준값 그대로 site_db_std에 반영 |
| 확인 필요 | `UNVERIFIED_NOT_FOUND` | A, C | O | X | G(또는 TS_std)는 성공했으나 TS가 업체를 못 찾음 | 표준(또는 기존)좌표 기준 TextSearch를 반경 완화·좌표 근접 보강까지 포함해 시도하고(Case A는 업체명+주소텍스트 TSA 병행 보강까지) 모두 업체 미발견. 대개 Google Places에 해당 업체가 POI로 미등재된 경우 | 담당자가 제공된 검색 쿼리형 URL로 Google Maps에서 직접 검색해 업체 실재 여부 수동 확인 |
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
