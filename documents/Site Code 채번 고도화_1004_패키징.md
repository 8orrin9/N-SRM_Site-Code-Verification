# Site Code 채번 고도화 — 프로젝트 패키징 문서

> 작성일: 2026-10-04
> 대상: N-SRM Site Code 채번 고도화 PoC 전체 소스 디렉토리

---

## 1. 프로젝트 개요

공급망 Site 마스터의 **채번(Site Code 부여) 품질을 고도화**하기 위한 PoC다. 핵심 흐름은
다음 네 단계로 구성된다.

1. **표준화·실재검증(STD_VLD)** — 흔들린 업체명·주소 표기를 Google Maps/행안부(Juso) API로
   정규화하고, 좌표·주소가 실재하는지 검증한다.
2. **중복 제거(SIM / dedup)** — 표준화된 Site들 사이의 near-duplicate를 5-gate 매칭
   (code/duns/address/coord/name)으로 식별해 클러스터링한다.
3. **유사 검색(SIM / find_similar)** — 신규 등록 쿼리에 대해 기존 DB에서 유사 Site를 찾아
   **기존 코드 연결 vs 신규 채번**을 판정한다.
4. **웹앱(app/)** — 위 로직을 FastAPI 백엔드 + Next.js 프론트엔드로 감싼 4단계 업무 화면
   (Upload → Standardize → Dedup → Similarity).

이와 별도로 로직 품질을 측정하는 **Golden Dataset 자동 생성·평가 파이프라인**과, 시연용
**HTML 목업 데이터 생성기**가 포함되어 있다.

---

## 2. 최상위 디렉토리 구조

```
N-SRM_Site-Code-Verification/
├── app/                 # 풀스택 웹앱 (FastAPI 백엔드 + Next.js 프론트)
│   ├── backend/         #   FastAPI: 라우터 → 서비스 → scripts 코어 로직
│   └── frontend/        #   Next.js 15 + React 19 SPA (4단계 업무 화면)
├── scripts/             # 코어 로직 & 배치 (표준화/검증/중복/유사/평가/목업)
│   └── temp/            #   진단·테스트용 (커밋 대상 아님, 문서화 제외)
├── config/              # 설정 (country_lang.yaml — 국가→언어 매핑)
├── data/                # 입력/산출 데이터 (site_master, golden dataset, 테이블 저장소)
│   └── tables/          #   웹앱 파일 기반 테이블 영속화 (menu별 JSON)
├── docs/                # 자동 생성 리포트
│   └── reports/         #   SIM 평가 리포트/CSV
├── documents/           # 설계·프로세스 문서 (Process Map, Golden Dataset 설계 등)
├── mockup/              # HTML 목업 프로토타입 + mock_data.json
├── assets/              # 정적 리소스 (브랜드 이미지 등)
├── requirements.txt         # 전체 개발 환경 의존성 (크롤러·LLM 등 포함)
├── requirements-deploy.txt  # 배포용 최소 의존성 (FastAPI 런타임)
├── Dockerfile           # 배포 컨테이너 빌드
├── render.yaml          # Render 배포 설정
├── CLAUDE.md            # 코딩 가이드라인
└── .env                 # 환경변수 (API 키 등, 커밋 제외)
```

---

## 3. app/ — 풀스택 웹앱

### 3.1 app/backend/ (FastAPI)

라우터 → 서비스 → `scripts/` 코어 모듈로 이어지는 3계층 구조다. 코어 로직
(STD_VLD_*, SIM_*)은 **수정하지 않고 재사용**하며, `deps.py`가 `scripts/`를 `sys.path`에
추가해 bare import를 가능하게 한다.

#### 코어 파일

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 초기화, 라우터 통합, CORS 설정, `/api/health`(adapter mode 반환), 프론트 정적 export 마운트 |
| `deps.py` | 부트스트랩: `scripts/`를 sys.path 추가 + `.env` 로드. 모든 모듈이 최상단에서 `import deps`로 코어 모듈을 bare name import 가능하게 함 |
| `schema.py` | 컬럼 상수 재수출(단일 진실원천): `BASE_COLUMNS`/`EXTRA_COLUMNS`/`OUT_COLUMNS` (STD_VLD_260917_run_verification에서 가져옴) |
| `storage.py` | 파일 기반 테이블 영속화: `data/tables/<menu>/<slug>.json` + `index.json`. 함수 `list_tables`/`load_table`/`save_table`/`delete_table` |
| `find_similar.py` | 유사 검색 래퍼: `score_pair`(두 행 게이트 기반 순위 점수), `find_similar`(쿼리 1건 top_k 후보). SIM_260926_dedup·geo_common·std_company 재사용 |

#### 라우터 (엔드포인트)

| 파일 | 메서드·경로 | 역할 |
|------|-------------|------|
| `routers/upload.py` | POST `/api/upload/parse` | xlsx/xls 업로드 → pandas 파싱 → BASE_COLUMNS 매핑 + No. 부여 |
| `routers/standardize.py` | POST `/api/standardize` | rows 표준화·실재검증 → OUT_COLUMNS 반환 |
| `routers/dedup.py` | POST `/api/dedup` | 중복 식별 (요청 thresholds 적용) → 클러스터/의심 엣지 |
| `routers/similarity.py` | POST `/api/similarity` | 유사 검색 (query_rows × reference_rows, top_k) |
| `routers/tables.py` | GET/POST/DELETE `/api/tables[/{menu}[/{name}]]` | 단계별 결과 테이블 CRUD |

#### 서비스 (코어 모듈 연결)

| 파일 | 하는 일 | import하는 scripts 모듈 |
|------|---------|------------------------|
| `services/verify_service.py` | `standardize_rows(rows)`: Maps 어댑터(real/mock 지연생성) + Juso 클라이언트로 행별 `process_row` 실행 | STD_VLD_260917_maps_adapter, STD_VLD_260917_run_verification, STD_VLD_260929_juso_adapter |
| `services/dedup_service.py` | `run_dedup(rows, thresholds)`: 요청 임계치로 코어 전역 상수 임시 오버라이드 후 `dd.dedup()` 실행 | SIM_260926_dedup, STD_VLD_260917_std_company |
| `services/similarity_service.py` | `search(query_rows, reference_rows, top_k)`: 쿼리행별 `find_similar()` 호출 | find_similar (로컬 모듈) |

#### 요청 흐름

```
[1 Upload]  POST /api/upload/parse   xlsx → {columns, rows}
                 ↓
[2 Standardize] POST /api/standardize  verify_service.standardize_rows()
                 ↓                       → process_row() (Maps/Juso 어댑터)
[3 Dedup]   POST /api/dedup           dedup_service.run_dedup()
                 ↓                       → SIM_260926_dedup.dedup()
[4 Similarity] POST /api/similarity    similarity_service.search()
                 ↓                       → find_similar.find_similar()
[저장]      POST /api/tables/{menu}    각 단계 결과를 data/tables 에 영속화
```

### 3.2 app/frontend/ (Next.js 15 + React 19)

4단계 워크플로우를 좌우 2분할 레이아웃으로 구현한 SPA. 추가 UI 라이브러리 없이 순수
React로 작성. 백엔드는 `NEXT_PUBLIC_API_BASE`(기본 `http://localhost:8000`) 환경변수로 호출.

#### 페이지 (src/app/)

| 파일 | 역할 |
|------|------|
| `layout.tsx` | 루트 레이아웃: 헤더(브랜드 + GNB) + 전역 Toaster |
| `page.tsx` | 홈(`/`) → `/upload` 리다이렉트 |
| `upload/page.tsx` | 파일/수기 입력 → 파싱 → 컬럼 매핑 → 테이블 정제 → 저장 |
| `standardize/page.tsx` | 업로드 테이블 로드 → 국내/해외 표준화(좌표·기업명·주소) → 지도 검증 → 저장 |
| `dedup/page.tsx` | 표준화 테이블 로드 → 임계치 자동 클러스터링 + 수동 클러스터 → 대표 선택 → Apply → 저장 |
| `similarity/page.tsx` | 기준(좌) + 쿼리(우) → 표준화 → 유사도 매칭 → 기존 코드/신규 채번 판정 |

#### 컴포넌트 (src/components/)

| 컴포넌트 | 역할 |
|---------|------|
| `ColumnMapModal` | 원본 컬럼 → 표준 컬럼 매핑 UI(자동 추정 + 수동 조정) |
| `DataTable` | 편집 그리드: 행 선택·인라인 셀 편집·상태 배지·링크 |
| `Drawer` | 우측 슬라이드 패널(리사이징): 유사 검색 상세 랭킹 |
| `Nav` | 상단 네비게이션(Upload→Standardization→Deduplication→Similarity) |
| `PaneBox` | 좌/우 공통 박스: 헤더 + 본문 + 로딩 오버레이 |
| `ResultDock` | 하단 슬라이드 결과 패널(중복/유사 결과) |
| `SaveModal` | 테이블 저장 모달(이름 입력 + 덮어쓰기 옵션) |
| `TableList` | 저장 테이블 목록(멀티셀렉트 + 삭제) |
| `Toaster` | 전역 토스트 메시지 |
| `TwoPane` | 좌/우 2분할 레이아웃(드래그 리사이징, 7:3↔3:7) |

#### 라이브러리 (src/lib/)

| 모듈 | 역할 |
|------|------|
| `api.ts` | REST 클라이언트(파싱·표준화·중복·유사·테이블 CRUD). `trimForCompute()`로 계산 불필요 컬럼 제거 |
| `types.ts` | 타입 정의(SiteRow, TableMeta, Cluster, QueryResult, DedupResult 등) |
| `toast.ts` | 전역 토스트 싱글턴(구독자 패턴) |
| `columns.ts` | 컬럼 스키마 상수 + 매핑 로직(BASE_COLUMNS, guessTarget, applyMapping) |
| `ui.ts` | 화면 헬퍼(avgClass, scoreBadge, mapUrls, rowLabel) |

주요 버전: `next 15.1.6`, `react 19.0.0`, `typescript 5.7.3`.

---

## 4. scripts/ — 코어 로직 & 배치

### 4.1 네이밍 규칙

`{영역}_{날짜코드}_{모듈명}.py` 형식.

- **STD_VLD_** — 주소 표준화 및 실재검증(Standardization & Validation)
- **SIM_** — 중복 제거 / 유사 검색 / 평가(Similarity)
- **html_** — HTML 목업용 데이터 생성
- **날짜코드** — `260917` = 2026-09-17 (작업 시점)

모듈 간 import는 `deps.py` 또는 각 배치가 `sys.path`에 `scripts/`를 추가하므로 bare name으로
이뤄진다.

### 4.2 STD_VLD — 표준화·실재검증 (8개)

| 파일 | 역할 |
|------|------|
| `STD_VLD_260917_locale.py` | 국가 → 언어 매핑(`lang_for_country`). config/country_lang.yaml 사용 |
| `STD_VLD_260917_geo_common.py` | 지오 공통 유틸(결과 구조 `make_result`, 좌표/주소 레벨 등 공통 상수·함수) |
| `STD_VLD_260917_std_company.py` | 업체명 표준화(`standardize_company`, `comparison_key`) + 유사도(`SIM`) |
| `STD_VLD_260917_maps_adapter.py` | Google Maps 어댑터(Real/Mock). `make_adapter`로 모드 선택 |
| `STD_VLD_260917_verify_pipeline.py` | 실재검증 파이프라인: Case A/B/C 결정트리, dual-address, combine_matrix |
| `STD_VLD_260917_run_verification.py` | 배치 오케스트레이터: 행별 `process_row`, 좌표/주소 파싱, 지역 선택, 도로명 통일 |
| `STD_VLD_260922_run_verification_TF.py` | TF(True/False) 검증용 변형 배치(`_map_row`, `_read_rows`, `main`) |
| `STD_VLD_260929_juso_adapter.py` | 행안부(Juso) 도로명주소 API 어댑터(`make_juso_client`, `resolve`) |

**의존 그래프(STD_VLD)**:
```
run_verification ──┬─> geo_common
                   ├─> verify_pipeline ──> geo_common
                   ├─> maps_adapter ──> geo_common, std_company
                   ├─> std_company
                   ├─> locale
                   ├─> juso_adapter
                   └─> SIM_261002_translate
run_verification_TF ─> maps_adapter, run_verification
```

### 4.3 SIM — 중복/유사/평가 (7개)

| 파일 | 역할 |
|------|------|
| `SIM_260926_dedup.py` | 핵심 매칭 엔진: 5-gate(code/duns/addr/coord/name), 블로킹, Union-Find 클러스터링, `dedup` |
| `SIM_261002_translate.py` | 업체명 언어 판정 + 영문 표기(`detect_and_translate`). LLM 호출 + 휴리스틱 폴백, 캐시 |
| `SIM_260929_build_golden.py` | Golden Dataset 자동 생성(기준 DB + 변형 쿼리 + 라벨), Oracle self-check |
| `SIM_260929_perturb.py` | 변형(perturbation) 라이브러리(name/addr/coord/code 변형 + 복합 `compose`) |
| `SIM_260929_eval_common.py` | 평가 공통(임계치 오버라이드, gate verdict 산출, find_similar 재수출) |
| `SIM_260929_eval_metrics.py` | 평가 지표(ranking, decision@T, threshold_sweep, dedup, gate_confusion) |
| `SIM_260929_run_eval.py` | 평가 오케스트레이터: Golden Dataset 로드 → 검색/중복/gate 평가 → 리포트/CSV |

**의존 그래프(SIM)**:
```
run_eval ──> eval_common ──┬─> dedup ──> geo_common, std_company
             eval_metrics  ├─> std_company, geo_common
                           └─> find_similar(app/backend)
build_golden ──> eval_common, perturb, std_company
perturb ──> eval_common
dedup ──> geo_common, std_company
```

### 4.4 html — 목업 데이터 생성 (2개)

| 파일 | 역할 |
|------|------|
| `html_260908_generate_site_master.py` | `data/site_master.csv`(100건, near-duplicate 포함) 생성. 참조 풀 기반 실좌표 + 표기 노이즈 주입 |
| `html_260908_build_mockup_data.py` | site_master에서 near-duplicate를 high/mid/low 대역으로 분류한 `mockup/mock_data.json` 생성 |

의존: `build_mockup_data` → `generate_site_master`(COMPANY_POOL, PLACES, clean_address 재사용).

### 4.5 scripts/temp/ (문서화 제외)

진단·일회성 테스트용 스크립트(`make_sim_test_data.py`, `test_dedup.py`, `_diag_*.py`,
`_make_light_csv.py`). 커밋/패키징 대상이 아니며 독스트링 작업에서도 제외.

---

## 5. config / data / docs / documents / mockup / assets

| 디렉토리 | 내용 |
|---------|------|
| `config/` | `country_lang.yaml` — 국가 코드 → 언어 매핑(locale 모듈이 사용) |
| `data/` | 입력·산출 데이터. `site_master` 계열 CSV/XLSX, `SIM_260929_golden_*`(reference/queries/labels), `STD_VLD_*` 표준화 산출물 |
| `data/tables/` | 웹앱 테이블 영속화. `upload/`·`standardized/`·`deduped/` + `index.json` |
| `docs/reports/` | SIM 평가 자동 산출물: `SIM_260929_eval_report.md`, `eval_failures.csv`, `gate_confusion.csv`, `threshold_sweep.csv` |
| `documents/` | 설계·프로세스 문서(Process Map 3종, Golden Dataset 설계, 본 패키징 문서) |
| `mockup/` | HTML 목업(`html_260908_site_code_verification.html`, `html_260926_srm_service_prototype.html`) + `mock_data.json` |
| `assets/` | 정적 리소스(브랜드 워드마크 이미지 등) |

---

## 6. 파이프라인 전체 흐름도

```
[데이터 생성]
 generate_site_master.py ──> data/site_master.csv
          │                        │
          └─> build_mockup_data.py ─> mockup/mock_data.json ─> HTML 목업 시연
                                   
[표준화·검증]  (STD_VLD)
 site_master ─> run_verification.py ─> process_row
                     │  ├─ maps_adapter (Google Maps real/mock)
                     │  ├─ juso_adapter (행안부 도로명)
                     │  ├─ std_company  (업체명 표준화)
                     │  ├─ translate    (언어판정·영문표기)
                     │  └─ verify_pipeline (Case A/B/C 실재검증)
                     └─> 표준화 산출 CSV/XLSX

[중복/유사]  (SIM)
 표준화 데이터 ─> dedup.py (5-gate 매칭 + Union-Find) ─> 클러스터
              └> find_similar (쿼리 top_k) ─> 코드연결/신규채번 판정

[평가]  (SIM)
 build_golden.py ─> golden reference/queries/labels
                      │
 run_eval.py ────────┴─> eval_common/metrics ─> docs/reports/*

[웹앱]  (app/)
 Next.js UI ──REST──> FastAPI ──> (verify/dedup/similarity service) ──> scripts 코어
   Upload → Standardize → Dedup → Similarity   (결과는 data/tables 저장)
```

---

## 7. 실행 방법

### 7.1 환경 준비

```powershell
# 가상환경 활성화 후
pip install -r requirements.txt          # 전체 개발 환경
# 또는 배포용 최소 의존성
pip install -r requirements-deploy.txt
```

### 7.2 백엔드 기동 (FastAPI)

```powershell
# app/backend 에서
uvicorn main:app --reload --port 8000
# health 확인: GET http://localhost:8000/api/health
```

### 7.3 프론트엔드 기동 (Next.js)

```powershell
# app/frontend 에서
npm install
npm run dev        # http://localhost:3000
```

### 7.4 주요 배치 스크립트

```powershell
# 목업 데이터 생성
python scripts/html_260908_generate_site_master.py
python scripts/html_260908_build_mockup_data.py

# 표준화·실재검증 배치
python scripts/STD_VLD_260917_run_verification.py

# Golden Dataset 생성 + 평가
python scripts/SIM_260929_build_golden.py
python scripts/SIM_260929_run_eval.py --sweep

# 중복 제거 단독 실행
python scripts/SIM_260926_dedup.py

# 업체명 번역 단건 테스트
python scripts/SIM_261002_translate.py "경인화학"
```

### 7.5 환경변수(.env)

| 변수 | 용도 |
|------|------|
| `GOOGLE_MAPS_API_KEY` | Google Maps 지오코딩(실재검증 real 모드) |
| `MAPS_ADAPTER_MODE` | `real` / `mock` 어댑터 선택 |
| `JUSO_CONFM_KEY` | 행안부 도로명주소 API 승인키 |
| `OPENAI_API_KEY` | 업체명 언어판정·영문표기(LLM). 미설정 시 휴리스틱 폴백 |
| `OPENAI_TRANSLATE_MODEL` | 번역 모델(기본 `gpt-4o-mini`) |
| `CORS_ORIGIN` | 백엔드 CORS 허용 오리진(기본 `http://localhost:3000`) |
| `NEXT_PUBLIC_API_BASE` | 프론트 → 백엔드 API 기본 URL(기본 `http://localhost:8000`) |
```
