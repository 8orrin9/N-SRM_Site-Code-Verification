# -*- coding: utf-8 -*-
"""일본·대만 행정구역(도시·구) ↔ Google 주소체계 매핑 오케스트레이터.

실행 순서:
    1. 공식 목록 확보(일본 총무성 Excel + 대만 NLSC API) → master_official.csv
    2. 각 행 × 언어(일본 ja/en, 대만 zh-TW/en) 조합마다 Geocoding 쿼리 1건
    3. 판정(MATCH/TYPE_DIFF/NAME_DIFF/PARTIAL/NOT_FOUND) → mapping_result.csv,
       mismatch_report.csv(MATCH 이외), summary.md

기본은 dry-run(실호출 없음, 예상 호출 수만 출력)이다. 실제 호출은 --execute로만.
GOOGLE_MAPS_API_KEY는 환경변수로만 읽는다(코드에 하드코딩하지 않음).
"""

import argparse
import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import MASTER_261021_classify as clf
import MASTER_261021_geocode_client as gcc
import MASTER_261021_official_jp as jp
import MASTER_261021_official_tw as tw

LANGS = {"JP": ["ja", "en"], "TW": ["zh-TW", "en"]}
# 판정(MATCH/TYPE_DIFF/...)은 공식 명칭(현지 문자)과 같은 문자 체계로 응답하는
# 주 언어에만 적용한다. en은 작업지시서 4장이 명시한 대로 "영문명 수집용" 옵션일
# 뿐이라, 한자 공식명과 영문 long_name을 비교하면 전부 NAME_DIFF가 돼버린다.
PRIMARY_LANG = {"JP": "ja", "TW": "zh-TW"}
JUDGMENT_NA = "N/A"  # 보조 언어(en) 행 — 판정 대상이 아니라 참고 수집 전용.
COST_PER_CALL_USD = 0.005  # Geocoding API 표준 단가(요청 1건당, 참고용 추정치)


def build_official_rows(*, jp_excel_path: str | None = None) -> tuple[list[dict], dict]:
    """일본·대만 공식 행정구역 행을 모두 모은다.

    Args:
        jp_excel_path (str | None, optional): 로컬에 이미 받아둔 총무성 엑셀 경로.
            없으면 `fetch_jp_excel`로 새로 받는다.

    Returns:
        tuple: (전체 official 행 리스트, {"JP": as_of_date, "TW": None} 메타).
    """
    if jp_excel_path:
        with open(jp_excel_path, "rb") as f:
            jp_bytes = f.read()
        jp_url = jp_excel_path
    else:
        jp_bytes, jp_url = jp.fetch_jp_excel()
    jp_rows, jp_as_of = jp.parse_jp_excel(jp_bytes)
    tw_rows = tw.build_tw_official()

    rows = jp_rows + tw_rows
    meta = {"JP": {"as_of": jp_as_of, "source": jp_url},
            "TW": {"as_of": None, "source": tw.LIST_COUNTY_URL}}
    return rows, meta


def write_master_official(rows: list[dict], by_code: dict, path: str) -> None:
    """master_official.csv를 쓴다(쿼리 경로 포함).

    Args:
        rows (list): official 행 리스트.
        by_code (dict): {(country, code): row} 조회 테이블.
        path (str): 출력 경로.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["country", "level", "code", "name", "kana", "parent_code",
                    "expected_type", "query_path"])
        for r in rows:
            w.writerow([r["country"], r["level"], r["code"], r["name"],
                        r.get("kana") or "", r.get("parent_code") or "",
                        r.get("expected_type") or "",
                        clf.build_query_path(by_code, r)])


def plan_calls(rows: list[dict], by_code: dict, client: gcc.GeocodeClient) -> list[dict]:
    """각 행 × 언어 조합의 호출 계획(캐시 여부 포함)을 만든다.

    Args:
        rows (list): official 행 리스트.
        by_code (dict): {(country, code): row} 조회 테이블.
        client (GeocodeClient): 캐시 상태 확인용.

    Returns:
        list: {row, query, language, cached} 목록(행 수 × 언어 수).
    """
    plans = []
    for r in rows:
        query = clf.build_query_path(by_code, r)
        for lang in LANGS[r["country"]]:
            p = client.plan(query, lang, r["country"])
            plans.append({"row": r, "query": query, "language": lang, "cached": p["cached"]})
    return plans


def run_mapping(rows: list[dict], by_code: dict, client: gcc.GeocodeClient,
                 *, dry_run: bool) -> list[dict]:
    """각 행 × 언어 조합을 지오코딩하고 판정까지 수행한다.

    Args:
        rows (list): official 행 리스트.
        by_code (dict): {(country, code): row} 조회 테이블.
        client (GeocodeClient): Geocoding 호출기.
        dry_run (bool): True면 실제 호출 없이(캐시 히트만 사용) 진행.

    Returns:
        list: mapping_result.csv 한 행씩에 대응하는 dict 목록.
    """
    results = []
    for r in rows:
        query = clf.build_query_path(by_code, r)
        for lang in LANGS[r["country"]]:
            data = client.geocode(query, language=lang, region_country=r["country"],
                                   dry_run=dry_run)
            api_status = data.get("status", "_DRY_RUN" if data.get("_dry_run") else "UNKNOWN")
            top = (data.get("results") or [None])[0] if not data.get("_dry_run") else None

            if lang == PRIMARY_LANG[r["country"]]:
                judged = clf.classify_result(r["name"], r.get("expected_type"), top)
            else:
                # 보조 언어(en): 영문명 수집만 — 공식명(한자)과 비교 판정하지 않는다.
                comps = (top or {}).get("address_components", [])
                judged = {"status": JUDGMENT_NA,
                          "matched_type": (comps[0].get("types") or [None])[0] if comps else None,
                          "matched_name": comps[0].get("long_name") if comps else None,
                          "place_id": (top or {}).get("place_id"),
                          "partial_match": bool((top or {}).get("partial_match"))}

            results.append({
                "country": r["country"], "level": r["level"], "code": r["code"],
                "name": r["name"], "parent_code": r.get("parent_code") or "",
                "query": query, "language": lang, "api_status": api_status,
                "judgment": judged["status"], "matched_type": judged["matched_type"] or "",
                "matched_name": judged["matched_name"] or "", "place_id": judged["place_id"] or "",
                "partial_match": judged["partial_match"],
            })
    return results


def write_mapping_csv(results: list[dict], path: str, *, only_mismatch: bool = False) -> None:
    """mapping_result.csv 또는 mismatch_report.csv를 쓴다.

    Args:
        results (list): `run_mapping`의 결과.
        path (str): 출력 경로.
        only_mismatch (bool, optional): True면 judgment != MATCH만 쓴다.
    """
    cols = ["country", "level", "code", "name", "parent_code", "query", "language",
            "api_status", "judgment", "matched_type", "matched_name", "place_id", "partial_match"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in results:
            # 보조 언어(en, JUDGMENT_NA)는 판정 대상이 아니므로 mismatch 리포트에서도 제외.
            if only_mismatch and row["judgment"] in (clf.STATUS_MATCH, JUDGMENT_NA):
                continue
            w.writerow({k: row[k] for k in cols})


def write_summary(results: list[dict], meta: dict, path: str, *, dry_run: bool) -> None:
    """summary.md를 쓴다: 국가·레벨별 건수, 판정 분포, 대만 타입 분포.

    Args:
        results (list): `run_mapping`의 결과.
        meta (dict): `build_official_rows`가 반환한 국가별 소스 메타(기준일 등).
        path (str): 출력 경로.
        dry_run (bool): dry-run 결과인지 표시용.
    """
    lines = ["# 일본·대만 행정구역 ↔ Google 주소체계 매핑 결과\n"]
    lines.append(f"- 모드: {'dry-run(실호출 없음)' if dry_run else '실행'}")
    lines.append(f"- 일본 기준일: {meta['JP']['as_of']} (출처: {meta['JP']['source']})")
    lines.append(f"- 대만 출처: {meta['TW']['source']} (縣市/鄉鎮市區 코드서비스, 기준일 표시 없음)")
    lines.append("- 언어: 판정(MATCH 등)은 주 언어(JP=ja, TW=zh-TW)에만 적용. "
                 "en은 영문명 수집 전용(판정=N/A)이며 아래 통계에서 제외.\n")

    # 판정 관련 통계는 전부 주 언어 행만 집계한다(en은 공식명과 다른 문자체계라
    # 비교 자체가 성립하지 않음 — JUDGMENT_NA로 별도 처리됨).
    primary_results = [r for r in results if r["judgment"] != JUDGMENT_NA]

    by_country_level = Counter((r["country"], r["level"]) for r in primary_results)
    lines.append("## 국가·레벨별 쿼리 건수(주 언어 기준)\n")
    for (country, level), n in sorted(by_country_level.items()):
        lines.append(f"- {country} / {level}: {n}건")

    lines.append("\n## 판정 분포(주 언어 기준)\n")
    judgment_counts = Counter(r["judgment"] for r in primary_results)
    total = len(primary_results) or 1
    for status in (clf.STATUS_MATCH, clf.STATUS_PARTIAL, clf.STATUS_TYPE_DIFF,
                   clf.STATUS_NAME_DIFF, clf.STATUS_NOT_FOUND):
        n = judgment_counts.get(status, 0)
        lines.append(f"- {status}: {n}건 ({n / total:.1%})")

    jp_results = [r for r in primary_results if r["country"] == "JP"]
    if jp_results:
        jp_match = sum(1 for r in jp_results if r["judgment"] == clf.STATUS_MATCH)
        lines.append(f"\n## 일본 기대 매핑 MATCH율\n")
        lines.append(f"- {jp_match}/{len(jp_results)} ({jp_match / len(jp_results):.1%})")

    tw_results = [r for r in primary_results if r["country"] == "TW"]
    if tw_results:
        lines.append("\n## 대만 Google 반환 타입 분포(실측, zh-TW 기준)\n")
        for level in ("county", "township"):
            sub = [r for r in tw_results if r["level"] == level]
            type_counts = Counter(r["matched_type"] or "(없음)" for r in sub)
            lines.append(f"\n### {level} ({len(sub)}건)\n")
            for t, n in type_counts.most_common():
                lines.append(f"- {t}: {n}건")

    en_results = [r for r in results if r["judgment"] == JUDGMENT_NA]
    if en_results:
        en_ok = sum(1 for r in en_results if r["api_status"] == "OK")
        lines.append(f"\n## 영문명 수집(참고, 판정 제외)\n")
        lines.append(f"- {en_ok}/{len(en_results)}건에서 영문 명칭 확보")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                         help="실제로 Google Geocoding API를 호출한다. 기본은 dry-run.")
    parser.add_argument("--out-dir", default=os.path.join(HERE, "..", "data"))
    parser.add_argument("--cache-dir",
                         default=os.path.join(HERE, "..", "data", "MASTER_261021_google_raw_cache"))
    parser.add_argument("--qps", type=float, default=5.0)
    parser.add_argument("--jp-excel", default=None,
                         help="이미 받아둔 총무성 엑셀 로컬 경로(테스트/재실행용). 없으면 새로 다운로드.")
    args = parser.parse_args()

    dry_run = not args.execute
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not dry_run and not api_key:
        raise SystemExit("GOOGLE_MAPS_API_KEY 환경변수가 없습니다(--execute에는 필수).")

    print("공식 목록 확보 중...")
    rows, meta = build_official_rows(jp_excel_path=args.jp_excel)
    by_code = {(r["country"], r["code"]): r for r in rows}
    print(f"  JP {sum(1 for r in rows if r['country']=='JP')}건, "
          f"TW {sum(1 for r in rows if r['country']=='TW')}건")

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    write_master_official(rows, by_code, os.path.join(out_dir, "MASTER_261021_master_official.csv"))

    client = gcc.GeocodeClient(api_key=api_key, cache_dir=args.cache_dir, qps=args.qps)

    if dry_run:
        plans = plan_calls(rows, by_code, client)
        cached = sum(1 for p in plans if p["cached"])
        to_call = len(plans) - cached
        print(f"\n[dry-run] 전체 쿼리: {len(plans)}건 (캐시 적중 {cached}건 / 신규 호출 필요 {to_call}건)")
        print(f"[dry-run] 신규 호출 예상 비용: 약 ${to_call * COST_PER_CALL_USD:.2f} "
              f"(건당 ${COST_PER_CALL_USD} 추정, 실제 단가는 Google 요금표 기준)")
        return

    print(f"\n실행 중... (QPS {args.qps})")
    results = run_mapping(rows, by_code, client, dry_run=False)

    write_mapping_csv(results, os.path.join(out_dir, "MASTER_261021_mapping_result.csv"))
    write_mapping_csv(results, os.path.join(out_dir, "MASTER_261021_mismatch_report.csv"),
                       only_mismatch=True)
    write_summary(results, meta, os.path.join(out_dir, "MASTER_261021_summary.md"), dry_run=False)
    print("완료 — mapping_result.csv / mismatch_report.csv / summary.md 작성됨")


if __name__ == "__main__":
    main()
