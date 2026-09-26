// 화면 공용 표시 헬퍼.
import type { SiteRow } from "./types";

// 유사도 점수(0~100) → 배지 색상 클래스.
export function avgClass(v: number): string {
  return v >= 70 ? "avg-hi" : v >= 40 ? "avg-mid" : "avg-lo";
}

// 게이트 서브점수 배지. null(SKIP=정보없음)이면 색 없는 "—".
export function scoreBadge(v: number | null): { text: string; cls: string } {
  if (v == null) return { text: "—", cls: "avg-na" };
  return { text: String(v), cls: avgClass(v) };
}

// 행의 참조 URL에서 지도 링크 배열 추출. 표준/원본 주소가 다르면 " | "로 병존
// (표준 → 원본 순). Standardization의 참조 URL 렌더와 동일 규칙.
export function mapUrls(r: SiteRow): string[] {
  return (r["참조 URL"] || "").split(" | ").map((s) => s.trim()).filter(Boolean);
}

// 행에서 대표 라벨(이름 + 부가정보) 추출.
export function rowLabel(r: SiteRow): { name: string; sub: string } {
  const name = r["STD 업체명"] || r["업체"] || "(이름없음)";
  const bits: string[] = [];
  if (r["기업식별 코드"]) bits.push("코드 " + r["기업식별 코드"]);
  if (r["Duns No."]) bits.push("Duns " + r["Duns No."]);
  if (r["주소(Eng)"]) bits.push(r["주소(Eng)"]);
  return { name, sub: bits.join(" · ") };
}
