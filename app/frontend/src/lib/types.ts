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
