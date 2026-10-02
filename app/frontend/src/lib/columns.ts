// schema.py(BASE_COLUMNS/EXTRA_COLUMNS)와 수동 동기화되는 컬럼 상수.
// 백엔드가 한국어 컬럼 키를 그대로 주고받으므로 프론트도 동일 키를 사용한다.
import type { SiteRow } from "./types";

export const BASE_COLUMNS = [
  "No.", "Status", "Site Code", "Site 유형", "업체", "항구/공항 코드",
  "기업식별 코드", "Duns No.", "국가/지역", "행정구역", "주소(Eng)", "주소(Local)",
  "위도", "경도", "관련 협력사 코드", "수정일", "Site 출처", "STD 주소", "STD 업체명",
  "STD 업체명(Eng)", "업체명 언어",
];

export const EXTRA_COLUMNS = [
  "표준화", "분류 코드", "비고", "표준 위도", "표준 경도",
  "place_id", "참조 URL", "addressComponents",
];

export const OUT_COLUMNS = [...BASE_COLUMNS, ...EXTRA_COLUMNS];

// 화면 입력/편집용 핵심 컬럼(부분집합). 업로드·수기 입력에서 사용.
export const INPUT_COLUMNS = [
  "업체", "기업식별 코드", "Duns No.", "국가/지역", "주소(Eng)", "위도", "경도",
];

// 표준화 결과에서 강조(STD 셀)로 표시할 컬럼.
export const STD_COLUMNS = [
  "표준화", "STD 업체명", "STD 업체명(Eng)", "STD 주소", "표준 위도", "표준 경도", "참조 URL",
];

// 업로드 매핑 타겟: process_row/후속 로직이 읽는 표준 입력 컬럼명.
// (주소(Local)도 표준화 Case 분기에서 사용되므로 포함)
export const MAP_TARGETS = [
  "업체", "기업식별 코드", "Duns No.", "국가/지역", "주소(Eng)", "위도", "경도",
];

// 원본 컬럼명 → 표준 컬럼명 자동 추정 별칭 (TF 러너 COLUMN_MAP과 동일 규칙).
const COLUMN_ALIASES: Record<string, string> = {
  "업체명 (Eng)": "업체",
  "업체명(Eng)": "업체",
  "업체명": "업체",
  "주소": "주소(Eng)",
};

// 원본 컬럼명에 대한 매핑 타겟 추정. 표준명과 같으면 그대로, 별칭이면 매핑,
// 그 외에는 ""(사용 안 함).
export function guessTarget(col: string): string {
  if (MAP_TARGETS.includes(col)) return col;
  return COLUMN_ALIASES[col] || "";
}

// 매핑을 적용해 원본 행을 표준 컬럼명 행으로 변환.
// 매핑된 표준 컬럼(MAP_TARGETS 순) + 매핑되지 않은 원본 컬럼(참고용 보존) 순서.
export function applyMapping(rows: SiteRow[], mapping: Record<string, string>): SiteRow[] {
  return rows.map((row) => {
    const out: SiteRow = {};
    MAP_TARGETS.forEach((tgt) => {
      const src = Object.keys(mapping).find((s) => mapping[s] === tgt);
      if (src !== undefined) out[tgt] = row[src] ?? "";
    });
    for (const [k, v] of Object.entries(row)) {
      if (k === "No." || mapping[k]) continue; // 매핑된 원본은 표준명으로 이동됨
      if (!(k in out)) out[k] = v;
    }
    return out;
  });
}
