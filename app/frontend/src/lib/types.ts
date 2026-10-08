// 백엔드 wire format과 일치하는 타입. 행은 한국어 컬럼 키 dict.

export type SiteRow = Record<string, string>;

export interface TableMeta {
  name: string;
  menu: string;
  slug: string;
  row_count: number;
  saved_at: string;
}

export interface SavedTable {
  name: string;
  menu: string;
  columns: string[];
  rows: SiteRow[];
  saved_at: string;
}

export interface Cluster {
  member_indices: number[];
  representative: number;
}

export interface Suspect {
  pair: [number, number];
  reason: string;
  name_score: number | null;
}

export interface DedupResult {
  clusters: Cluster[];
  suspects: Suspect[];
}

// 게이트 판정값(중복 제거와 동일). SKIP=정보없음, DIFFERENT=모순.
export type GateVerdict = "EQUAL" | "SIMILAR" | "DIFFERENT" | "SKIP";

export interface SimMatch {
  ref_index: number;
  ref_row: SiteRow;
  // 서브점수: SKIP(정보없음)이면 null → 화면에서 "—"로 표시(모순 0점과 구분).
  nameSim: number | null;
  corpSim: number | null;
  dunsSim: number | null;
  addrSim: number | null;
  coordSim: number | null;
  avg: number;                       // 종합 순위 점수(0~100)
  gates?: Record<string, GateVerdict>;
  vetoed?: boolean;                  // 식별자(코드/Duns) 충돌 패널티 적용 여부
}

export interface QueryResult {
  query_index: number;
  matches: SimMatch[];
}

export interface DedupThresholds {
  name_threshold?: number;
  addr_jaccard?: number;
  coord_m?: number;
  code_max_edits?: number;
}

// Similarity Search 종합 점수 산출용 가중치. find_similar.score_pair의
// weights 파라미터와 키를 맞춘다. 전부 선택값 — 없으면 백엔드 기본값 사용.
export interface SimilarityWeights {
  gate_weights?: { duns?: number; code?: number; addr?: number; coord?: number }; // 필터별 가중치
  g_strong_equal?: number;      // 고유성 우대(+) · Equal
  g_strong_similar?: number;    // 고유성 우대(+) · Similar
  veto_factor?: number;         // 고유성 우대(-)
  name_diff_threshold?: number; // 업체명 상이 판단 임계
  weak_name_factor?: number;    // 업체명 상이함에 따른 감쇄도
  f_weight?: number;            // Base: F 가중치
  n_weight?: number;            // Base: N 가중치
}
