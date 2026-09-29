# 유사 검색 / 중복 제거 성능 평가 — Golden Dataset 설계

표준화·실재검증을 마친 Site(업체) 정보에서 동작하는 **유사 검색(4번 메뉴)**과
**중복 제거(3번 메뉴)**의 매칭 성능을 정량 평가하기 위한 Golden Dataset 설계 명세다.
두 메뉴는 모두 `scripts/SIM_260926_dedup.py`의 **5-gate 매칭 파이프라인**을 근간으로
동작하므로(similarity는 `app/backend/find_similar.py` 래퍼 경유), 본 데이터셋 하나로
두 로직을 동시에 평가한다.

관련 모듈: `scripts/SIM_260926_dedup.py`, `app/backend/find_similar.py`
seed 데이터: `data/STD_VLD_260926_site_master_TF_2_std.xlsx` (시트 `TF_std_2`, 38행)

---

## 0. 설계 목표와 배경

현재 매칭 로직의 임계값은 경험적으로 설정돼 있고(아래), 이를 검증·재튜닝할 정량 근거가 없다.
`std_company.py`에도 "Golden Dataset으로 튜닝 필요" 주석이 남아 있다.

| 임계값 | 위치 | 기본값 | 의미 |
|---|---|---|---|
| `SIM_THRESHOLD` | `std_company.py` | 0.85 | 업체명 유사 판정 |
| `COORD_EQUAL_M` | `dedup.py` | 100.0 m | 좌표 동일 판정 반경 |
| `ADDR_LOWER_JACCARD` | `dedup.py` | 0.5 | 주소 하위 레벨 토큰 겹침 |
| `ADDR_UPPER_MAX_EDITS` | `dedup.py` | 1 | 주소 상위 레벨 편집거리 허용 |
| `CODE_SIMILAR_MAX_EDITS` | `dedup.py` | 1 | 코드/Duns 오타 허용 |
| 기준 점수 `T` | `find_similar` (프론트) | 60 | 코드매핑 vs 신규채번 판정 |

**목표**: seed 데이터에 자동 변형(perturbation)과 Hard Negative(FP trap)를 적용해
정답(ground truth)이 부착된 데이터셋을 만들고, 이를 통해 검색 품질·판정 품질·클러스터
품질·gate 단위 진단·임계값 재튜닝 근거를 산출한다.

---

## 1. 핵심 설계 원칙

### 1-1. 매칭 로직만 평가한다 (표준화는 고정)

Site 정보의 최종 품질은 **표준화 × 매칭** 두 단계의 곱이다. 그러나 본 평가는
**매칭 로직만** 대상으로 한다. 이유:
- 유사 검색은 표준화 **이후**의 필드(`STD 업체명`, `표준 위도/경도`, `addressComponents`)
  위에서 동작한다.
- seed(`TF_std_2`)에 표준화 결과가 이미 고정(frozen)돼 있으므로, 이를 직접 로직에 주입하면
  **Google API 없이 결정적·반복 가능**하게 평가할 수 있다(비용 0).
- 이렇게 분리하면 오류 원인을 "표준화가 잘못했나 vs 임계값이 나빴나"로 명확히 귀속할 수 있다.

### 1-2. 표준화 이후 데이터 불변식 (가장 중요)

> **변형은 "표준화 이후에도 정당하게 남는 변이"만 모델링한다.**
> 표준화가 제거했을 오탈자 주소·미표준 주소는 생성하지 않는다.

유사 검색은 표준화된 데이터끼리 비교하므로, 두 중복 레코드의 차이는 표준화 과정에서
정당하게 발생할 수 있는 것이어야 한다. 필드별 정책:

| 필드 | 표준화가 하는 일 | 표준화 후 남는 정당한 변이 | 오탈자 변형 |
|---|---|---|---|
| **주소** (`addressComponents`) | Google Geocoding → 깨끗한 계층 구조 | granularity 차이, long/short·로마자 표기 변이, 인접 premise | **금지** (Google 출력엔 오탈자 없음) |
| **좌표** (`표준 위도/경도`) | Geocoding | 독립 지오코딩 편차·정밀도·결측 | 해당 없음 (연속값) |
| **업체명** (`STD 업체명`) | 법인격 접미사만 제거, 철자 원본 유지 | 영↔현지어, 약어↔정식, 대소문자/구두점/어순, **원본 오탈자 잔존** | **허용** (이름 표준화는 철자 교정 안 함) |
| **식별자** (code/duns) | **표준화 대상 아님** | 하이픈/공백/오탈자/결측 | **허용** (원본 데이터 그대로) |

핵심 귀결: 주소 상위 레벨 경계(`ADDR_UPPER_MAX_EDITS=1`)를 자극할 때 "오탈자"가 아니라
**로마자 표기 변이**(예: `Gyeonggi-do` ↔ `Gyeonggido`, 편집거리 1)로 모델링한다.
seed의 "확인 필요" 24행은 coarse 지오코딩 결과이므로 granularity/결측 변이의 실제 근거로 쓴다.

### 1-3. 정답 라벨은 로직에 노출하지 않는다

`entity_id`, `variant_type`, `expected_*_verdict` 등 정답 메타는 별도 파일에 분리하고,
로직에 입력되는 업무 컬럼과는 hidden `row_uid`로 조인한다. 로직이 정답을 엿볼 수 없게 한다.

---

## 2. 데이터셋 구성

### 2-1. 파일 구성

| 파일 | 내용 | 로직 입력? |
|---|---|---|
| `data/SIM_260929_golden_reference.{xlsx,csv}` | 기준 DB (기존 코드 DB 역할) | O |
| `data/SIM_260929_golden_queries.xlsx` | 유사 검색 쿼리 (신규채번 negative 포함) | O |
| `data/SIM_260929_golden_labels.csv` | 정답 메타 | **X (분리)** |

### 2-2. entity_id 라벨 스키마 — 설계의 근간

모든 행에 **실세계 정체성**(`entity_id`)을 부여한다. Site = "특정 물리적 업체 소재지"로 정의하면
아래 4가지 관계가 명확히 구분되며, 이것이 정답의 기준이 된다.

| 관계 | 같은 entity_id? | 병합해야? | 케이스 분류 |
|---|---|---|---|
| 같은 업체 + 같은 위치 (단일 필드 변형) | 동일 | **예 (TP)** | `TP_variant` |
| 같은 업체 + 같은 위치 (여러 필드 동시 열화) | 동일 | **예 (TP)** | `TP_composite` |
| 다른 업체 + 같은 위치 (같은 건물 입주사) | 다름 | 아니오 | `FP_adjacent` |
| 같은 업체 + 다른 위치 (서울/부산 공장) | 다름 | 아니오 | `FP_branch` |
| 유사 업체명 + 무관 (OO전자 vs OO전자부품) | 다름 | 아니오 | `FP_similar_name` |
| 다른 업체가 같은 code/duns 오입력 | 다름 | 아니오 | `identifier_collision` |
| 완전 무관 | 다름 | 아니오 | `TN_random` |
| 기준 DB에 없는 신규 업체 | (신규) | (신규채번) | `new_numbering` |

### 2-3. 라벨 메타 컬럼 (labels.csv 전용)

`row_uid`(조인키), `entity_id`, `seed_id`(원본 seed 행), `variant_type`(적용 변형),
`perturbed_fields`(변형 필드 목록), `case_class`(위 표), `difficulty`(easy/med/hard),
`expected_gate`/`expected_verdict`(단일 변형의 정답 gate·판정), `component_gates`(복합 변형의
결정적 성분들을 `gate:verdict;…`로 직렬화), `compare_uid`(gate 진단 비교 상대),
`expected_match_entity`(쿼리가 매핑돼야 할 entity, 신규면 공란), `is_new_numbering`.

### 2-4. 식별자 합성

seed에 `기업식별 코드`/`Duns No.` 컬럼이 없으므로 entity별로 합성한다.
- `code`: `sha1(entity_id)[:6]` → 안정적 6자 alnum (동일 길이라 EQUAL / 1자 오타 SIMILAR / DIFFERENT 모두 자극).
- `duns`: 9자리 숫자를 `NN-NNN-NNNN` 형식 (실제 데이터의 `02-442-6764` 패턴 준수, 정규화 시 9자리로 환원).

---

## 3. 변형(Perturbation) 카탈로그 — gate별 설계

seed 1건에서 다수의 정당한 변형을 생성한다. 각 변형은 어느 gate가 어떤 판정을
내려야 하는지(EQUAL/SIMILAR/DIFFERENT/SKIP)를 함께 기록해, 최종 결과뿐 아니라
**gate 단위 회귀**도 검증한다.

### 3-1. 업체명 → `name_gate` (SIM ≥ 0.85)
- 법인격 표기차: `㈜` / `Co., Ltd.` / `株式会社` / `有限公司` 부착·제거 → EQUAL (comparison_key가 제거)
- 약어 ↔ 정식: `Elec.` ↔ `Electronics`
- 대소문자 / 구두점 / 띄어쓰기 차이 → EQUAL
- 오탈자 1자 → EQUAL / 2자 → SIMILAR 경계 (이름은 철자 교정을 안 하므로 정당)
- 어순 교환 → EQUAL (token_sort_ratio)
- 영문 ↔ 현지어 → 대개 DIFFERENT (알려진 약점, 단정 대신 관측만)

### 3-2. 주소 → `address_gate` (**주소 오탈자 금지**)
표준화 출력에 정당하게 존재할 수 있는 변이만:
- `drop_detail`: route/street_number 제거 (granularity 차, 입력 완성도 차이 반영) → 하위 SKIP
- `abbr_iso`: 동일 지오코딩의 long ↔ short 표기차 (`South Korea` ↔ `KR`) → cross-field EQUAL
- `upper_romanization`: 상위 레벨 로마자 표기 변이 (`Gyeonggi-do` ↔ `Gyeonggido`, 편집거리 1) → SIMILAR 경계 / 더 큰 표기차 → DIFFERENT
- `lower_reorder`: 하위 토큰 순서 (`26 Euljiro` ↔ `Euljiro 26`) → SIMILAR
- `lower_jaccard_boundary`: 하위 토큰 겹침 정확히 0.5 → SIMILAR / 0.25 → DIFFERENT
- `building_name_only`: 랜드마크/건물명 위주 입력의 지오코딩 (상위 레벨 부재) → SKIP

편집법: `addressComponents` JSON을 파싱 → `types`로 항목 매칭해 `long_text`/`short_text` 수정
또는 항목 삭제 → 재직렬화. 표시용 `주소` 문자열은 gate가 무시하므로 손대지 않는다.

### 3-3. 좌표 → `coord_gate` (100m)
- `none`: 결측 → SKIP
- `drift_{50,99,101,150}m`: inverse-haversine로 정확한 거리 이동 (50·99 → EQUAL, 101·150 → DIFFERENT, 100m 경계 양측 probe)
- `precision`: 소수점 절삭 → EQUAL

### 3-4. 식별자 → `code_gate` / `duns_gate`
- `hyphen_space`: 구분자 삽입 → 정규화로 EQUAL
- `typo1`: 동일 길이 1자 치환 (편집거리 1) → SIMILAR
- `typo2`: 동일 길이 2자 치환 (편집거리 2 > `CODE_SIMILAR_MAX_EDITS`) → DIFFERENT → **veto 발동** (복합 저점 프로파일용)
- `insdel1`: 길이 변하는 1자 삽입·삭제 → **dedup은 DIFFERENT, similarity는 relaxed SIMILAR** (두 메뉴의 의도된 차이를 문서화)
- `missing`: 결측 → SKIP

---

## 3-5. 복합(multi-field) 변형 — 점수 변별력 확보

### 왜 필요한가 (실측 근거)
단일 필드 변형만으로 평가하면 **TP 쿼리 점수가 전부 100점**으로 몰려 임계값 스윕이
무의미하다(모든 T에서 F1 동일). 원인은 `find_similar.score_pair`의 결합식이 **강신호 지배**
(evidence-dominant max-blend)이기 때문이다.

```
base  = max(ALPHA·G + (1-ALPHA)·N,  g_strong,  N)   # G=게이트근거, N=업체명유사
score = 100 · v_factor · base
```

- 업체명이 canonical이면 `N=1.0` → `max(…, N)=1.0` → **100점**
- code/duns 중 하나라도 EQUAL이면 `g_strong=1.0` → **100점** (addr/coord EQUAL이면 0.85)

즉 **한 필드만 열화해도 나머지 canonical 강신호가 점수를 100으로 복원**한다. 이 bimodal
특성 자체가 리포트할 발견이며, 점수를 중간대로 낮추려면 **업체명 N을 떨어뜨리면서 동시에
EQUAL 게이트(g_strong)를 제거**해야 한다.

### 프로파일 (목표 점수 구간별)
각 entity에 `--combos-per-entity`개(기본 2)를 배정하며 단일 변형과 **병존**한다.

| 프로파일 | 구성 | 겨냥 점수 | 난이도 |
|---|---|---|---|
| `combo_mid_high` | 이름 2자 오타 + code·duns 결측 (addr/coord EQUAL 유지 → g_strong=0.85) | ~85~99 | med |
| `combo_mid` | 이름 오타 + 좌표 이탈(DIFFERENT) + 주소 상위 큰 표기차(DIFFERENT) + 식별자 결측 (EQUAL 게이트 전무 → base≈N) | ~49~96 | hard |
| `combo_low_veto` | 이름 오타 + code 2자 오타(DIFFERENT → veto) → `v_factor=0.35` | ~35 | hard |

`combo_low_veto`는 **진짜 같은 entity인데 식별자 오타로 veto되어 누락되는 위험 케이스**를
정량화한다(관측 전용, verdict 단정 안 함).

### 구현·검증
- `SIM_260929_perturb.py::compose(rec, steps)`가 변형 함수를 순차 적용(각 함수가 record를
  반환해 체이닝)하고 결정적 성분의 gate 판정을 `component_gates`로 집계한다.
- 이름 열화는 `name_typo2`(마지막 두 알파넘 치환)로 SIM을 0.85 아래로 떨어뜨린다. SIM 값이
  데이터 의존적이라 verdict를 단정하지 않고 점수만 관측한다.
- Oracle self-check와 per-gate 진단은 **결정적 성분**(coord/code/duns/addr)만 검증한다.

---

## 4. Hard Negative (FP Trap) — 경계를 정의하는 핵심

TP(진짜 중복)만으로는 임계값을 튜닝할 수 없다. 경계를 정의하는 것은 negative다.
각 트랩은 로직의 특정 약점을 겨냥한다.

| 트랩 | 구성 | 겨냥하는 약점 | 정답 |
|---|---|---|---|
| **FP_adjacent** | 좌표·주소 EQUAL, 업체명만 무관 | addr/coord EQUAL로 confirm 후 **name_gate만이 오병합을 막음** | dedup NONE / similarity 신규채번 |
| **FP_branch** | 업체명 EQUAL, 좌표·주소 DIFFERENT, code/duns 결측·상이 | **업체명 과의존** | dedup NONE / similarity 신규채번 |
| **FP_similar_name** | `Foo Electronics` vs `Foo Electronic Components`, 같은 도시 | `comparison_key`가 industry stopword 제거 → 다른 업체가 동일해 보임 | **의도적으로 실패 노출** (오병합으로 리포트) |
| **identifier_collision** | 다른 업체가 같은 code, name·좌표 상이 | **식별자 gate 맹신** | dedup NONE 기대 / similarity 위험 정량화 |
| **TN_random** | 공유 블록키 없는 무관 쌍 | 특이도(specificity), 잘못된 blocking | 후보쌍 미생성 / 낮은 점수 |

`FP_similar_name`과 `identifier_collision`은 SUT가 실패할 수 있는 알려진 위험 케이스로,
**합격이 아니라 노출이 목적**이다. 리포트에서 오병합으로 개별 나열한다.

### new_numbering (신규 채번 쿼리)
기준 DB에 없는 신규 업체 쿼리(신규 name+code+duns, 실재하나 먼 좌표)를 포함한다.
`is_new_numbering=True`. 이들은 임계값 `T` 이하로 "신규 채번" 판정돼야 하며,
**기준점수 임계값 튜닝의 핵심**(P/R/F1, ROC의 negative 클래스)이다.

---

## 5. 평가 지표

### 5-1. Menu 4 (유사 검색, 최우선)
- **검색 품질**: Top-1 정확도, Recall@k (k=1/3/5/8), MRR
- **판정 품질**: 기준점수 T에서 코드매핑 vs 신규채번의 정밀도/재현율/F1
  (신규채번 쿼리를 negative 클래스로). T=0~100 스윕 → PR/ROC 곡선 →
  **현재 기본값 60의 최적성 검증 및 재설정 권고** (F1 최대 T, precision≥0.95 최소 T)
- **점수 분포 진단**: TP 쿼리 top1 점수를 case_class(TP_variant/TP_composite)·variant·난이도별
  요약(min/p25/median/p75/max/mean). 복합 변형이 실제로 점수를 중간대로 분산시켜
  임계값 변별력을 만드는지(더 이상 모든 T에서 동일 F1이 아닌지) 검증한다.

### 5-2. Menu 3 (중복 제거)
- **Pairwise 정밀도/재현율/F1**: CONFIRMED 병합 쌍 vs 동일 entity_id 쌍
- **클러스터 지표**: ARI, homogeneity/completeness/V-measure (`sklearn.metrics`)
- **오병합(false merge) 건수**: 다른 entity가 병합된 쌍 — 심각도 최상, 개별 나열
- **SUSPECT 버킷 분석**: 의심 큐의 TP/FP 비율 + 사유 분포 (휴먼 리뷰 큐 품질)

### 5-3. Gate 단위 진단
expected verdict를 가진 행마다 개별 gate를 직접 호출해 정답 대비 혼동행렬
(expected × actual over {EQUAL, SIMILAR, DIFFERENT, SKIP})을 gate별로 산출.
E2E 실패 시 어느 gate 책임인지 격리한다.

### 5-4. 임계값 튜닝 스윕
`SIM_THRESHOLD`, `COORD_EQUAL_M`, `ADDR_LOWER_JACCARD`, (독립) `T`를 one-at-a-time 스윕해
파라미터별 dedup F1·Menu4 F1 최대값을 리포트 → 기본값 재설정 근거 제공.

---

## 6. 산출물

- **Golden Dataset**: reference / queries / labels 3종
- **평가 리포트** (`docs/reports/SIM_260929_eval_report.md`): 데이터셋 manifest,
  Menu4·Menu3 헤드라인 지표, 오병합 목록, gate 혼동 요약, 임계값 튜닝 권고표
- **실패 케이스 CSV**: 케이스별 expected vs actual, 판정 gate — 수동 점검용
- **스윕/혼동 CSV**: 임계값 곡선, gate 혼동행렬
- **콘솔 요약**: 헤드라인 지표 + baseline 대비 PASS/FAIL

---

## 7. 데이터셋 자기검증

생성기는 다음을 assert 해 데이터 자체의 정합성을 보장한다.
- 행 카운트·case_class별 카운트가 manifest와 일치
- 합성 code/duns가 정규화 규칙을 만족 (code 비공란, duns 9자리)
- 모든 `addressComponents`가 유효 JSON으로 round-trip
- 각 변형이 의도 필드만 바꾸고 나머지 보존
- **Oracle spot-check**: 결정적 변형(hyphen/space, missing, coord 경계, addr cross-field)은
  생성기가 gate를 직접 호출해 정답과 일치 확인 (영↔현지어·오탈자2자 등 경계 케이스는 로깅만).
  복합 변형은 `component_gates`의 결정적 성분별 gate 판정을 개별 assert 한다.
