# -*- coding: utf-8 -*-
"""유사 Site 검색 (신규 얇은 래퍼).

중복 제거(SIM_260926_dedup.py)의 단계적 게이트 철학을 그대로 재사용하되,
결과는 "확정/의심/무관 분류"가 아니라 **종합 순위 점수**로 산출한다.

설계(프로세스 문서 "유사 Site 검색" 참조):
  - 코드/Duns 게이트 = 필터 + 강신호. DIFFERENT면 감점(veto)하되 목록엔 남긴다.
  - 주소/좌표 게이트 = 중복 제거처럼 처리. DIFFERENT는 soft(veto 없음).
  - 각 게이트의 EQUAL 근접도(EQUAL 1.0 / SIMILAR 0.6 / DIFFERENT 0 / SKIP 제외)를
    가중 평균하고, 업체명 SIM과 max-blend로 결합해 강신호가 결측에도 지배하게 한다.

코어 로직(scripts/*.py)은 수정하지 않고 게이트 함수를 호출만 한다.
"""

import deps  # noqa: F401

import SIM_260926_dedup as dd
import STD_VLD_260917_geo_common as gc
from STD_VLD_260917_std_company import SIM

# 게이트 근접도(EQUAL 근접도). SKIP은 집계에서 제외하므로 여기 없음.
CLOSENESS = {dd.EQUAL: 1.0, dd.SIMILAR: 0.6, dd.DIFFERENT: 0.0}
# 게이트별 신뢰도 가중치(코드/Duns가 강신호).
GATE_WEIGHTS = {"duns": 0.35, "code": 0.30, "coord": 0.20, "addr": 0.15}
ALPHA = 0.6              # 게이트 근거 G vs 업체명 N 결합 비중
VETO_FACTOR = 0.35       # 식별자(코드/Duns) 충돌 시 곱셈 패널티
WEAK_NAME_FACTOR = 0.6   # 업체명이 약한 유사(게이트 DIFFERENT, SIM<임계)일 때 기여 감쇄

COORD_NEAR_M = 100.0     # 좌표 표시용 감쇠: 이 거리 이내 100점
COORD_FAR_M = 5000.0     # 이 거리 이상 0점


def _relax_id_gate(verdict, a_norm, b_norm):
    """코드/Duns 게이트 완화: DIFFERENT라도 편집거리 ≤ 임계면 SIMILAR로 본다.

    코어 게이트(_code_like_gate)는 `len(a)==len(b)`(자릿수 동일)일 때만 SIMILAR를
    허용해, 숫자 1개 삽입·삭제 오타(예: 56789↔5678, 편집거리 1)를 DIFFERENT로 떨군다.
    유사 검색은 dirty data 오타로 진짜 후보를 veto·누락시키지 않도록 자릿수 조건 없이
    편집거리만으로 SIMILAR를 인정한다(코어 수정 없이 래퍼에서 재분류).

    Args:
        verdict (str): 코어 게이트 판정(EQUAL/SIMILAR/DIFFERENT/SKIP).
        a_norm (str | None): 정규화된 쿼리 식별자.
        b_norm (str | None): 정규화된 기준 식별자.

    Returns:
        str: 완화된 판정. DIFFERENT가 편집거리 임계 이내면 SIMILAR, 아니면 원본.
    """
    if verdict == dd.DIFFERENT and a_norm and b_norm:
        if dd.Levenshtein.distance(a_norm, b_norm) <= dd.CODE_SIMILAR_MAX_EDITS:
            return dd.SIMILAR
    return verdict


def _gate_display(verdict):
    """게이트 판정 → 표시용 서브점수. SKIP은 None(프론트에서 '—').

    Args:
        verdict (str): 게이트 판정(EQUAL/SIMILAR/DIFFERENT/SKIP).

    Returns:
        int | None: 0~100 서브점수. SKIP이면 None.
    """
    if verdict == dd.SKIP:
        return None
    return int(round(CLOSENESS[verdict] * 100))


def _coord_display(coord_a, coord_b):
    """좌표 표시용 연속 점수. 결측이면 None.

    Args:
        coord_a (tuple | None): 쿼리 좌표 (lat, lon).
        coord_b (tuple | None): 기준 좌표 (lat, lon).

    Returns:
        int | None: 거리 기반 0~100 점수(가까울수록 높음). 좌표 결측이면 None.
    """
    if not coord_a or not coord_b:
        return None
    dist = gc.haversine(coord_a, coord_b)
    if dist <= COORD_NEAR_M:
        return 100
    if dist >= COORD_FAR_M:
        return 0
    return int(round(100 * (1 - (dist - COORD_NEAR_M) / (COORD_FAR_M - COORD_NEAR_M))))


def score_pair(q_gate: dict, ref_gate: dict) -> dict:
    """게이트 입력 dict 두 개(_to_rows 변환 결과)를 받아 종합 순위 점수 산출.

    q_gate/ref_gate: {code, duns, std_name, coord, components, ...}

    Args:
        q_gate (dict): 쿼리 행의 게이트 입력.
        ref_gate (dict): 기준 행의 게이트 입력.

    Returns:
        dict: 표시용 서브점수(nameSim/corpSim/dunsSim/addrSim/coordSim),
            종합 점수(avg, 0~100), 원본 게이트 판정(gates), 식별자 충돌 여부(vetoed).
    """
    verdicts = {
        "code": _relax_id_gate(dd.code_gate(q_gate, ref_gate),
                               dd.normalize_code(q_gate.get("code")),
                               dd.normalize_code(ref_gate.get("code"))),
        "duns": _relax_id_gate(dd.duns_gate(q_gate, ref_gate),
                               dd.normalize_duns(q_gate.get("duns")),
                               dd.normalize_duns(ref_gate.get("duns"))),
        "addr": dd.address_gate(q_gate, ref_gate),
        "coord": dd.coord_gate(q_gate, ref_gate),
    }
    # 업체명 게이트: 쿼리·기준의 언어가 같으면(둘 다 존재) 원본 표준명끼리, 다르거나
    # 결측이면 영문 표기끼리 비교한다(동일 언어 우선, 교차 시 영문 폴백).
    q_lang, ref_lang = q_gate.get("lang"), ref_gate.get("lang")
    if q_lang and ref_lang and q_lang == ref_lang:
        name_a, name_b = q_gate.get("std_name"), ref_gate.get("std_name")
    else:
        name_a, name_b = q_gate.get("name_eng"), ref_gate.get("name_eng")
    name_verdict, name_raw = dd.name_gate({"std_name": name_a}, {"std_name": name_b})
    name_sim = name_raw if name_raw is not None else None

    # A. 게이트 근거 G (SKIP 아닌 게이트만 분모에 포함)
    num = den = 0.0
    for g, v in verdicts.items():
        if v == dd.SKIP:
            continue
        w = GATE_WEIGHTS[g]
        num += w * CLOSENESS[v]
        den += w
    G = (num / den) if den else None

    # B. 업체명 항 N — 약한 유사(게이트 DIFFERENT, SIM<임계)면 결합 기여를 감쇄한다.
    #    'test' vs 'LT Metal Co'(SIM 0.73)처럼 우연히 겹치는 약한 이름 유사가 상위권을
    #    잠식하지 않도록. 표시용 nameSim은 원점수 유지, 결합용 N만 감쇄.
    N = name_sim
    if N is not None and name_verdict == dd.DIFFERENT:
        N = N * WEAK_NAME_FACTOR

    # C. 강신호 dominance
    if verdicts["code"] == dd.EQUAL or verdicts["duns"] == dd.EQUAL:
        g_strong = 1.0
    elif verdicts["addr"] == dd.EQUAL or verdicts["coord"] == dd.EQUAL:
        g_strong = 0.85
    else:
        g_strong = 0.0

    # D. 결합 (evidence-dominant max-blend)
    if G is None and N is None:
        base = 0.0
    elif G is None:
        base = N
    elif N is None:
        base = G
    else:
        base = max(ALPHA * G + (1 - ALPHA) * N, g_strong, N)

    # E. veto(식별자 충돌) + 0~100 스케일
    vetoed = verdicts["code"] == dd.DIFFERENT or verdicts["duns"] == dd.DIFFERENT
    v_factor = VETO_FACTOR if vetoed else 1.0
    score = int(round(100 * v_factor * base))

    return {
        "nameSim": int(round(name_sim * 100)) if name_sim is not None else None,
        "corpSim": _gate_display(verdicts["code"]),
        "dunsSim": _gate_display(verdicts["duns"]),
        "addrSim": _gate_display(verdicts["addr"]),
        "coordSim": _coord_display(q_gate.get("coord"), ref_gate.get("coord")),
        "avg": score,
        "gates": {**verdicts, "name": name_verdict},
        "vetoed": vetoed,
    }


def _prep(row: dict) -> dict:
    """한국어 키 dict → 게이트 입력 dict. _to_rows를 재사용하되, 업체명은
    'STD 업체명'이 비면 원본 업체명(label)으로 보완한다.

    쿼리는 사용자 수기 입력이라 표준화 전이라 'STD 업체명'이 비고 '업체'만 있는 경우가
    대부분이다. _to_rows의 std_name은 'STD 업체명'만 읽으므로, 폴백을 담고 있는 label로
    채워 업체명 게이트(name_gate)가 SKIP되지 않게 한다.

    언어별 비교(동일 언어 우선, 교차 시 영문 폴백)를 위해 'STD 업체명(Eng)'·'업체명 언어'도
    담는다. 영문명이 비면 std_name으로 폴백한다.

    Args:
        row (dict): 한국어 컬럼 키를 가진 원본 행.

    Returns:
        dict: 게이트 입력 dict(std_name/name_eng/lang 보완 포함).
    """
    g = dd._to_rows([row])[0]
    if not g.get("std_name"):
        g["std_name"] = g.get("label") or ""
    g["name_eng"] = (row.get("STD 업체명(Eng)") or "").strip() or g["std_name"]
    g["lang"] = (row.get("업체명 언어") or "").strip()
    return g


def find_similar(query_row: dict, reference_rows: list, top_k: int = 8) -> list:
    """쿼리 1건(한국어 키 dict)에 대한 상위 top_k 후보(avg 내림차순).

    쿼리·기준 행을 dedup의 _to_rows로 게이트 입력 형식으로 변환해 정규화 일관성을 맞춘다.

    Args:
        query_row (dict): 한국어 컬럼 키를 가진 쿼리 행.
        reference_rows (list): 비교 기준 행 목록.
        top_k (int, optional): 반환할 상위 후보 수. 기본 8.

    Returns:
        list: {ref_index, ref_row, ...점수} dict를 avg 내림차순 top_k개.
    """
    q_gate = _prep(query_row)
    ref_gates = [_prep(r) for r in reference_rows]
    scored = []
    for ri, (ref, ref_gate) in enumerate(zip(reference_rows, ref_gates)):
        s = score_pair(q_gate, ref_gate)
        scored.append({"ref_index": ri, "ref_row": ref, **s})
    scored.sort(key=lambda m: m["avg"], reverse=True)
    return scored[:top_k]
