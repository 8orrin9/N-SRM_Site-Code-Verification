# 일본·대만 행정구역 ↔ Google 주소체계 매핑 결과

- 모드: 실행
- 일본 기준일: 2024-01-01 (출처: https://www.soumu.go.jp/main_content/000925835.xlsx)
- 대만 출처: https://api.nlsc.gov.tw/other/ListCounty (縣市/鄉鎮市區 코드서비스, 기준일 표시 없음)
- 언어: 판정(MATCH 등)은 주 언어(JP=ja, TW=zh-TW)에만 적용. en은 영문명 수집 전용(판정=N/A)이며 아래 통계에서 제외.

## 국가·레벨별 쿼리 건수(주 언어 기준)

- JP / muni: 1747건
- JP / pref: 47건
- JP / ward: 171건
- TW / county: 22건
- TW / township: 368건

## 판정 분포(주 언어 기준)

- MATCH: 2334건 (99.1%)
- PARTIAL: 0건 (0.0%)
- TYPE_DIFF: 0건 (0.0%)
- NAME_DIFF: 21건 (0.9%)
- NOT_FOUND: 0건 (0.0%)

## 일본 기대 매핑 MATCH율

- 1944/1965 (98.9%)

## 대만 Google 반환 타입 분포(실측, zh-TW 기준)


### county (22건)

- administrative_area_level_1: 22건

### township (368건)

- administrative_area_level_2: 353건
- locality: 15건

## 영문명 수집(참고, 판정 제외)

- 2355/2355건에서 영문 명칭 확보
