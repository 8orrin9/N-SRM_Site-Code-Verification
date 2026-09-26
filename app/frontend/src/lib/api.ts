// NEXT_PUBLIC_API_BASE 기반 fetch 래퍼.
import type {
  DedupResult, DedupThresholds, QueryResult, SavedTable, SiteRow, TableMeta,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
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
      method: "POST", body: JSON.stringify({ rows, thresholds }),
    }),
  similarity: (query_rows: SiteRow[], reference_rows: SiteRow[], top_k = 8) =>
    jsonFetch<{ results: QueryResult[] }>(`/api/similarity`, {
      method: "POST", body: JSON.stringify({ query_rows, reference_rows, top_k }),
    }),
};
