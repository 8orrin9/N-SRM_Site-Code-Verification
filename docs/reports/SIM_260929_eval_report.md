# 유사 검색 / 중복 제거 성능 평가 리포트

- 대상 로직: `scripts/SIM_260926_dedup.py` (dedup + find_similar)
- 쿼리 230건, top_k=8, 기준점수 T=60

## 무엇을, 어떻게 평가했나

**평가 대상**: 3번(중복 제거)·4번(유사 검색) 메뉴가 공유하는 5-gate 매칭 파이프라인(`code/duns/addr/coord/name` gate). 표준화는 seed(`TF_std_2`)에 이미 고정돼 있어 Google API 없이 결정적으로 재현 평가한다(Layer A).

**Golden Dataset(자동 생성)**: 표준화 완료 seed 38행에 entity_id·합성 식별자(코드/Duns)를 부여해 **기준 DB**를 만들고, 각 entity에 자동 변형(perturbation)을 가해 **쿼리**를 생성한다. 모든 변형은 *표준화 이후 데이터 불변식*을 지킨다 — 주소는 Google 지오코딩 출력이라 오탈자 없이 표기·granularity·순서·결측만, 업체명·식별자는 오탈자까지 허용.
- **단일 변형(TP_variant)**: 한 필드만 열화(이름 접미사/오타, 주소 표기/결측, 좌표 이탈/결측, 식별자 하이픈/오타/결측). 각 변형은 목표 gate 판정(EQUAL/SIMILAR/DIFFERENT/SKIP)을 갖는다.
- **복합 변형(TP_composite)**: 여러 필드를 동시 열화. 스코어링이 강신호 지배(`base=max(αG+(1-α)N, g_strong, N)`)라 단일 변형은 나머지 canonical 신호가 점수를 100으로 복원한다. 이름·식별자를 함께 떨어뜨려 점수를 중간대로 분산시켜 임계값 변별력을 만든다.
- **Hard Negative**: FP_adjacent(같은 좌표·다른 업체), FP_branch(같은 이름·다른 지역), FP_similar_name(stopword만 다른 유사명), identifier_collision(남의 코드 오입력) — 매칭되면 안 되는 함정. **new_numbering**(기준 DB에 없는 신규)·TN_random은 '신규 채번'이 정답인 negative.
**정답 라벨**은 별도 `labels.csv`(entity_id 등)에 두고 SUT엔 업무 컬럼만 입력, `row_uid`로 조인해 정보 누출을 막는다.

**측정 지표**:
- Menu4 검색: Top-1 정확도 / Recall@k / MRR (정답 entity가 상위에 오는가).
- Menu4 판정: top1 점수 ≥ T & 정답 entity면 코드매핑, 아니면 신규채번으로 보고 P/R/F1 + 임계값 스윕(T=0~100)으로 최적 T 탐색. new_numbering이 negative.
- Menu3 중복: pairwise P/R/F1 + 클러스터 지표(ARI/V-measure) + **오병합 건수**(다른 entity를 한 클러스터로 묶은 쌍, 심각도 최상).
- Gate 단위: 각 변형을 상대와 직접 비교해 gate별 기대×실제 혼동행렬 산출 → E2E 실패 시 책임 gate 격리.
- 임계값 스윕: `SIM_THRESHOLD`/`COORD_EQUAL_M`/`ADDR_LOWER_JACCARD`를 one-at-a-time로 바꿔가며 두 메뉴 F1 변화 관측 → 기본값 재튜닝 근거.

## Menu 4 — 유사 검색

### 검색 품질 (TP 쿼리)
- 대상 TP 쿼리: 204건
- **Top-1 정확도: 0.975**
- Recall@k: @1=0.975, @3=0.995, @5=1.000, @8=1.000
- **MRR: 0.986**

### 코드매핑 vs 신규채번 판정 (T=60)
- TP=179 FP=10 FN=25 TN=20
- **정밀도 0.947 / 재현율 0.877 / F1 0.911**
- 임계값 스윕: F1 최대 T=32 (F1=0.941), precision≥0.95 최소 T=86

### TP 점수 분포 (top1 avg)
복합(TP_composite) 변형이 점수를 중간대로 분산시켜 임계값 변별력을 만든다.

| 그룹 | n | min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|---|---|
| class:TP_variant | 136 | 100 | 100 | 100 | 100 | 100 | 100.0 |
| class:TP_composite | 68 | 35 | 35 | 93 | 96 | 99 | 76.4 |
| variant:combo:combo_mid | 23 | 49 | 90 | 93 | 95 | 99 | 89.0 |
| variant:combo:combo_mid_high | 26 | 85 | 95 | 96 | 98 | 99 | 95.4 |
| variant:combo:combo_low_veto | 19 | 35 | 35 | 35 | 35 | 35 | 35.0 |
| difficulty:easy | 50 | 100 | 100 | 100 | 100 | 100 | 100.0 |
| difficulty:med | 93 | 85 | 99 | 100 | 100 | 100 | 98.7 |
| difficulty:hard | 61 | 35 | 35 | 93 | 100 | 100 | 75.6 |

## Menu 3 — 중복 제거

- 클러스터 수: 1
- **Pairwise 정밀도 1.000 / 재현율 1.000 / F1 1.000** (TP=1 FP=0 FN=0)
- 클러스터 지표: ARI=1.000, V-measure=1.000 (homo=1.000, comp=1.000)
- **오병합(false merge): 0건** (심각도 최상)
- 의심(SUSPECT) 엣지: 0건 (TP=0 FP=0), 사유={}

## Gate 단위 진단

결정적 변형의 기대 판정 대비 실제 판정 (행=기대, 열=실제):

### code (정합 103/103)
| 기대\실제 | EQUAL | SIMILAR | DIFFERENT | SKIP |
|---|---|---|---|---|
| EQUAL | 14 | 0 | 0 | 0 |
| SIMILAR | 0 | 12 | 0 | 0 |
| DIFFERENT | 0 | 0 | 19 | 0 |
| SKIP | 0 | 0 | 0 | 58 |

### addr (정합 52/52)
| 기대\실제 | EQUAL | SIMILAR | DIFFERENT | SKIP |
|---|---|---|---|---|
| EQUAL | 17 | 0 | 0 | 0 |
| SIMILAR | 0 | 12 | 0 | 0 |
| DIFFERENT | 0 | 0 | 23 | 0 |

### duns (정합 66/66)
| 기대\실제 | EQUAL | SIMILAR | DIFFERENT | SKIP |
|---|---|---|---|---|
| EQUAL | 5 | 0 | 0 | 0 |
| SIMILAR | 0 | 12 | 0 | 0 |
| SKIP | 0 | 0 | 0 | 49 |

### name (정합 29/29)
| 기대\실제 | EQUAL | SIMILAR | DIFFERENT | SKIP |
|---|---|---|---|---|
| EQUAL | 29 | 0 | 0 | 0 |

### coord (정합 24/41)
| 기대\실제 | EQUAL | SIMILAR | DIFFERENT | SKIP |
|---|---|---|---|---|
| EQUAL | 4 | 0 | 0 | 5 |
| DIFFERENT | 0 | 0 | 11 | 12 |
| SKIP | 0 | 0 | 0 | 9 |

## 임계값 튜닝 스윕 (one-at-a-time)

| 파라미터 | 값 | dedup F1 | Menu4 결정 F1 |
|---|---|---|---|
| SIM_THRESHOLD | 0.8 | 1.0 | 0.9165 |
| SIM_THRESHOLD | 0.82 | 1.0 | 0.9109 |
| SIM_THRESHOLD | 0.85 | 1.0 | 0.9109 |
| SIM_THRESHOLD | 0.88 | 1.0 | 0.9054 |
| SIM_THRESHOLD | 0.9 | 1.0 | 0.8923 |
| SIM_THRESHOLD | 0.92 | 1.0 | 0.8808 |
| COORD_EQUAL_M | 50 | 1.0 | 0.9109 |
| COORD_EQUAL_M | 75 | 1.0 | 0.9109 |
| COORD_EQUAL_M | 100 | 1.0 | 0.9109 |
| COORD_EQUAL_M | 150 | 1.0 | 0.9109 |
| COORD_EQUAL_M | 200 | 1.0 | 0.9165 |
| ADDR_LOWER_JACCARD | 0.4 | 1.0 | 0.9109 |
| ADDR_LOWER_JACCARD | 0.5 | 1.0 | 0.9109 |
| ADDR_LOWER_JACCARD | 0.6 | 1.0 | 0.9109 |
