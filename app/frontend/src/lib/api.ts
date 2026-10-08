// NEXT_PUBLIC_API_BASE 기반 fetch 래퍼.
import type {
  DedupResult, DedupThresholds, QueryResult, SavedTable, SimilarityWeights, SiteRow, TableMeta,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Dedup/Similarity Search는 계산(게이트 비교)과 화면 표시에 쓰이는 필드만 필요하다.
// "참조 URL"(긴 place_id 문자열), "비고", "분류 코드" 등 업로드 메타 컬럼까지 그대로
// 실어 보내면 요청 본문이 커지는데, 일부 사내망의 보안장비가 큰 POST 본문을 차단하는
// 사례가 확인되어(작은 데이터는 통과, 큰 데이터만 403) 전송 직전에 덜어낸다.
// 저장(saveTable)에는 적용하지 않음 — 원본 전체를 보존해야 함.
const COMPUTE_FIELDS = [
  "업체", "STD 업체명", "STD 업체명(Eng)", "업체명 언어",
  "기업식별 코드", "Duns No.", "국가/지역",
  "주소(Eng)", "STD 주소", "위도", "경도", "표준 위도", "표준 경도",
  "addressComponents", "표준화",
];
function trimForCompute(rows: SiteRow[]): SiteRow[] {
  return rows.map((r) => {
    const out: SiteRow = {};
    COMPUTE_FIELDS.forEach((c) => { if (r[c] !== undefined) out[c] = r[c]; });
    return out;
  });
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch { /* noop */ }
    // res.statusText는 HTTP/2 응답에서 항상 빈 문자열일 수 있어(브라우저 스펙),
    // 그 경우 상태 코드만이라도 남겨 "빈 에러 메시지로 인한 무의미한 toast"를 막는다.
    if (!detail) detail = res.statusText || `HTTP ${res.status}`;
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

export const api = {
  // 공통 테이블
  listTables: (menu: string) =>
    jsonFetch<{ tables: TableMeta[] }>(`/api/tables?menu=${encodeURIComponent(menu)}`),
  loadTable: (menu: string, name: string) =>
    jsonFetch<SavedTable>(`/api/tables/${menu}/${encodeURIComponent(name)}`),
  saveTable: (menu: string, body: { name: string; columns: string[]; rows: SiteRow[]; overwrite?: boolean }) =>
    jsonFetch<{ meta: TableMeta }>(`/api/tables/${menu}`, {
      method: "POST", body: JSON.stringify(body),
    }),
  deleteTable: (menu: string, name: string) =>
    jsonFetch<{ ok: boolean }>(`/api/tables/${menu}/${encodeURIComponent(name)}`, { method: "DELETE" }),

  // 업로드 파싱 (multipart — JSON 헤더 미사용)
  parseUpload: async (file: File): Promise<{ columns: string[]; rows: SiteRow[] }> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(BASE + "/api/upload/parse", { method: "POST", body: fd });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
      throw new Error(detail);
    }
    return res.json();
  },

  standardize: (rows: SiteRow[]) =>
    jsonFetch<{ columns: string[]; rows: SiteRow[] }>(`/api/standardize`, {
      method: "POST", body: JSON.stringify({ rows }),
    }),
  dedup: (rows: SiteRow[], thresholds?: DedupThresholds) =>
    jsonFetch<DedupResult>(`/api/dedup`, {
      method: "POST", body: JSON.stringify({ rows: trimForCompute(rows), thresholds }),
    }),
  similarity: (query_rows: SiteRow[], reference_rows: SiteRow[], top_k = 8, weights?: SimilarityWeights) =>
    jsonFetch<{ results: QueryResult[] }>(`/api/similarity`, {
      method: "POST", body: JSON.stringify({
        query_rows: trimForCompute(query_rows),
        reference_rows: trimForCompute(reference_rows),
        top_k,
        weights,
      }),
    }),
};
