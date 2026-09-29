# -*- coding: utf-8 -*-
"""Golden Dataset 생성기.

seed(TF_std_2)의 표준화 완료 행을 기반으로 유사 검색/중복 제거 평가용 데이터셋을 만든다.
표준화 이후 데이터 불변식(설계 문서 §1-2)을 지키는 변형만 사용한다.

출력:
  data/SIM_260929_golden_reference.{xlsx,csv}  기준 DB (SUT 입력)
  data/SIM_260929_golden_queries.xlsx          유사 검색 쿼리 (SUT 입력)
  data/SIM_260929_golden_labels.csv            정답 메타 (SUT 미입력, row_uid 로 조인)

사용:
  .venv/Scripts/python.exe scripts/SIM_260929_build_golden.py \
      --seed data/STD_VLD_260926_site_master_TF_2_std.xlsx --sheet TF_std_2 \
      --variants-per-entity 4
"""

import argparse
import hashlib
import os
import random

import pandas as pd

import SIM_260929_eval_common as ec
import SIM_260929_perturb as pt
from STD_VLD_260917_std_company import comparison_key

SEED = 260929
# SUT(_to_rows/find_similar)가 읽는 업무 컬럼 + 라벨 조인용 hidden row_uid
BUSINESS_COLS = [
    "row_uid", "업체명 (Eng)", "업체", "국가/지역", "행정구역", "주소",
    "위도", "경도", "STD 업체명", "STD 주소", "표준화",
    "표준 위도", "표준 경도", "addressComponents", "기업식별 코드", "Duns No.",
]
LABEL_COLS = [
    "row_uid", "entity_id", "seed_id", "role", "case_class", "variant_type",
    "perturbed_fields", "difficulty", "compare_uid", "expected_gate", "expected_verdict",
    "component_gates", "expected_match_entity", "is_new_numbering",
]


# ---------------------------------------------------------------------------
def synth_code(entity_id: str) -> str:
    """entity_id → 안정적 6자 대문자 alnum 코드."""
    return hashlib.sha1(entity_id.encode()).hexdigest()[:6].upper()


def synth_duns(entity_id: str) -> str:
    """entity_id → NN-NNN-NNNN 형식 9자리 Duns."""
    d = int(hashlib.sha1(("duns" + entity_id).encode()).hexdigest(), 16) % 10**9
    s = f"{d:09d}"
    return f"{s[:2]}-{s[2:5]}-{s[5:]}"


def assign_entities(seed_rows: list) -> list:
    """동명(comparison_key 일치) + 좌표 근접(<100m) 행을 같은 entity 로 묶는다.

    좌표가 멀면 같은 회사라도 다른 site(FP_branch 실사례)이므로 다른 entity.
    반환: seed_id 순서의 entity_id 리스트.
    """
    n = len(seed_rows)
    uf = ec.dd.UnionFind(n)
    gates = [ec.to_gate_row(r) for r in seed_rows]
    for i in range(n):
        for j in range(i + 1, n):
            ki = comparison_key(seed_rows[i].get("STD 업체명") or "")
            kj = comparison_key(seed_rows[j].get("STD 업체명") or "")
            if not ki or ki != kj:
                continue
            ci, cj = gates[i].get("coord"), gates[j].get("coord")
            if ci and cj and ec.gc.haversine(ci, cj) <= ec.dd.COORD_EQUAL_M:
                uf.union(i, j)
    # 대표 인덱스 → 안정적 entity_id
    root_to_eid = {}
    eids = []
    for i in range(n):
        r = uf.find(i)
        if r not in root_to_eid:
            root_to_eid[r] = f"E{len(root_to_eid):03d}"
        eids.append(root_to_eid[r])
    return eids


def _mk_ref_row(seed_row: dict, uid: str, entity_id: str) -> dict:
    """seed 행 → reference 행(업무 컬럼 + 합성 식별자 + row_uid)."""
    row = {c: seed_row.get(c, "") for c in BUSINESS_COLS}
    row["row_uid"] = uid
    row["기업식별 코드"] = synth_code(entity_id)
    row["Duns No."] = synth_duns(entity_id)
    return row


def _label(uid, entity_id, seed_id, role, case_class, variant_type="",
           perturbed_fields="", difficulty="", compare_uid="", expected_gate="",
           expected_verdict="", component_gates="", expected_match_entity="",
           is_new_numbering=False):
    return {
        "row_uid": uid, "entity_id": entity_id, "seed_id": seed_id, "role": role,
        "case_class": case_class, "variant_type": variant_type,
        "perturbed_fields": perturbed_fields, "difficulty": difficulty,
        "compare_uid": compare_uid, "expected_gate": expected_gate,
        "expected_verdict": expected_verdict or "", "component_gates": component_gates,
        "expected_match_entity": expected_match_entity, "is_new_numbering": is_new_numbering,
    }


# 변형 → (함수, 대상 필드 라벨, gate 이름, 난이도)
def _variant_plan():
    return [
        (lambda r: pt.name_legal_suffix(r), "name", "name", "easy"),
        (lambda r: pt.name_case_punct(r), "name", "name", "easy"),
        (lambda r: pt.name_typo1(r), "name", "name", "med"),
        (lambda r: pt.name_word_order(r), "name", "name", "hard"),
        (lambda r: pt.addr_drop_detail(r), "addr", "addr", "med"),
        (lambda r: pt.addr_abbr_iso(r), "addr", "addr", "med"),
        (lambda r: pt.addr_upper_romanization(r, 1), "addr", "addr", "hard"),
        (lambda r: pt.addr_lower_reorder(r), "addr", "addr", "med"),
        (lambda r: pt.coord_drift(r, 50), "coord", "coord", "easy"),
        (lambda r: pt.coord_drift(r, 99), "coord", "coord", "hard"),
        (lambda r: pt.coord_none(r), "coord", "coord", "med"),
        (lambda r: pt.code_hyphen_space(r), "code", "code", "easy"),
        (lambda r: pt.code_typo1(r), "code", "code", "med"),
        (lambda r: pt.code_missing(r), "code", "code", "easy"),
        (lambda r: pt.code_hyphen_space(r, "Duns No."), "duns", "duns", "easy"),
        (lambda r: pt.code_typo1(r, "Duns No."), "duns", "duns", "med"),
    ]


# 복합 프로파일 → (steps=[(fn, gate)...], difficulty)
# 여러 필드를 동시 열화해 강신호(N=1.0, g_strong=1.0)를 제거, 점수를 중간대로 낮춘다.
def _combo_plan():
    return [
        # ~85점: 이름 2자 오타(N 하락) + 식별자 결측(g_strong=0.85는 addr/coord EQUAL 유지)
        ("combo_mid_high", [
            (lambda r: pt.name_typo2(r), "name"),
            (lambda r: pt.code_missing(r), "code"),
            (lambda r: pt.code_missing(r, "Duns No."), "duns"),
        ], "med"),
        # ~60~75점: 이름 오타 + 좌표 이탈(DIFFERENT) + 주소 상위 표기 큰 변이(DIFFERENT)
        #           + 식별자 결측 → EQUAL 게이트 전무(g_strong=0) → base≈N
        ("combo_mid", [
            (lambda r: pt.name_typo2(r), "name"),
            (lambda r: pt.coord_drift(r, 150), "coord"),
            (lambda r: pt.addr_upper_romanization(r, 3), "addr"),
            (lambda r: pt.code_missing(r), "code"),
            (lambda r: pt.code_missing(r, "Duns No."), "duns"),
        ], "hard"),
        # ~20~35점: 이름 오타 + 식별자 2자 오타(DIFFERENT→veto) → v_factor=0.35 저점
        ("combo_low_veto", [
            (lambda r: pt.name_typo2(r), "name"),
            (lambda r: pt.code_typo2(r), "code"),
        ], "hard"),
    ]


def build(seed_path: str, sheet: str, variants_per_entity: int,
          combos_per_entity: int = 2):
    rng = random.Random(SEED)
    df = pd.read_excel(seed_path, sheet_name=sheet, dtype=str).fillna("")
    seed_rows = df.to_dict("records")
    eids = assign_entities(seed_rows)

    references, queries, labels = [], [], []

    # ---- 1. reference DB = seed 38 행 (entity_id, 합성 식별자 부여) -------------
    uid_by_seed = {}
    for sid, (srow, eid) in enumerate(zip(seed_rows, eids)):
        uid = f"R{sid:03d}"
        uid_by_seed[sid] = uid
        ref = _mk_ref_row(srow, uid, eid)
        references.append(ref)
        # 자연 발생 동일-entity 중복(예: BOYD)은 dedup 이 병합해야 하므로 role 로 표시
        dup_count = eids.count(eid)
        cc = "reference_dup" if dup_count > 1 else "reference"
        labels.append(_label(uid, eid, sid, "reference", cc,
                             expected_match_entity=eid))

    # entity 대표 seed 행(변형 소스): 각 entity 의 첫 등장 행
    entity_src = {}
    for sid, eid in enumerate(eids):
        entity_src.setdefault(eid, sid)

    # 변형 소스로 적합한 행(주소/좌표/이름이 충분한 검증완료·확인필요) 선별
    def _rich(sid):
        r = seed_rows[sid]
        g = ec.to_gate_row(r)
        return (r.get("표준화") != ec.gc.STATUS_FAILED and g.get("coord")
                and len(g.get("components") or []) >= 4 and r.get("STD 업체명"))

    plan = _variant_plan()
    qseq = 0

    # ---- 2. TP 변형 쿼리 ------------------------------------------------------
    for eid, sid in entity_src.items():
        if not _rich(sid):
            continue
        base = _mk_ref_row(seed_rows[sid], uid_by_seed[sid], eid)
        chosen = rng.sample(plan, min(variants_per_entity, len(plan)))
        for fn, field, gate, diff in chosen:
            variant, expected, vt = fn(base)
            qseq += 1
            uid = f"Q{qseq:04d}"
            variant["row_uid"] = uid
            queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
            labels.append(_label(
                uid, eid, sid, "query", "TP_variant", vt, field, diff,
                compare_uid=uid_by_seed[sid], expected_gate=gate,
                expected_verdict=expected, expected_match_entity=eid))

    # ---- 2b. TP 복합(multi-field) 변형 쿼리 -----------------------------------
    combo_plan = _combo_plan()
    for eid, sid in entity_src.items():
        if not _rich(sid):
            continue
        base = _mk_ref_row(seed_rows[sid], uid_by_seed[sid], eid)
        chosen = rng.sample(combo_plan, min(combos_per_entity, len(combo_plan)))
        for name, steps, diff in chosen:
            variant, per_gate, tags = pt.compose(base, steps)
            qseq += 1
            uid = f"Q{qseq:04d}"
            variant["row_uid"] = uid
            queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
            # 결정적 성분(per_gate)을 "gate:verdict;..." 로 직렬화해 per-gate 진단에 사용
            comp = ";".join(f"{g}:{v}" for g, v in per_gate.items())
            fields = ";".join(dict.fromkeys(
                {"name": "name", "code": "code", "duns": "duns",
                 "addr": "addr", "coord": "coord"}[g] for g in
                [s[1] for s in steps]))
            labels.append(_label(
                uid, eid, sid, "query", "TP_composite", f"combo:{name}", fields,
                diff, compare_uid=uid_by_seed[sid], component_gates=comp,
                expected_match_entity=eid))

    # ---- 3. Hard Negatives ----------------------------------------------------
    rich_sids = [s for s in entity_src.values() if _rich(s)]

    # 3a. FP_adjacent: 좌표/주소 복제, 이름만 무관 업체로 교체 → 매칭되면 안 됨
    for k, sid in enumerate(rich_sids[:6]):
        eid = eids[sid]
        other_sid = rich_sids[(k + 3) % len(rich_sids)]
        variant = _mk_ref_row(seed_rows[sid], "", f"FPADJ{k}")  # 신규 식별자
        variant["STD 업체명"] = seed_rows[other_sid].get("STD 업체명") or "UNRELATED CO"
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant["row_uid"] = uid
        queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
        labels.append(_label(uid, f"FPADJ{k}", sid, "query", "FP_adjacent",
                             "same_addr_diff_company", "name", "hard",
                             expected_match_entity="", is_new_numbering=True))

    # 3b. FP_branch: 같은 이름, 먼 좌표(다른 도시), 식별자 결측 → 다른 site
    for k, sid in enumerate(rich_sids[:6]):
        eid = eids[sid]
        g = ec.to_gate_row(seed_rows[sid])
        variant = _mk_ref_row(seed_rows[sid], "", f"FPBR{k}")
        variant["기업식별 코드"] = ""       # 지점은 site code 를 공유 안 할 수 있음
        variant["Duns No."] = ""
        lat, lon = pt.offset_coord(g["coord"][0], g["coord"][1], 300000, 90)  # 300km 동쪽
        pt._set_coord(variant, lat, lon)
        # 상위 행정구역도 달라지도록 주소 상위 레벨을 크게 변형
        variant, _, _ = pt.addr_upper_romanization(variant, edits=4)
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant["row_uid"] = uid
        queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
        labels.append(_label(uid, f"FPBR{k}", sid, "query", "FP_branch",
                             "same_name_diff_location", "name;addr;coord", "hard",
                             expected_match_entity="", is_new_numbering=True))

    # 3c. FP_similar_name: industry stopword 만 다른 무관 업체 (같은 도시)
    for k, sid in enumerate(rich_sids[:4]):
        variant = _mk_ref_row(seed_rows[sid], "", f"FPSN{k}")
        variant["STD 업체명"] = f"Golden{k} Electronics"     # reference 에 없는 신규
        # 위치는 seed 그대로 두되 신규 entity → 매칭되면 안 됨
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant["row_uid"] = uid
        # 짝이 되는 유사명 무관 업체를 reference 에 주입
        ref_uid = f"RS{k:02d}"
        ref = _mk_ref_row(seed_rows[sid], ref_uid, f"FPSNREF{k}")
        ref["STD 업체명"] = f"Golden{k} Electronic Components"
        references.append({c: ref.get(c, "") for c in BUSINESS_COLS})
        labels.append(_label(ref_uid, f"FPSNREF{k}", sid, "reference",
                             "FP_similar_name", expected_match_entity=f"FPSNREF{k}"))
        queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
        labels.append(_label(uid, f"FPSN{k}", sid, "query", "FP_similar_name",
                             "industry_stopword_only", "name", "hard",
                             compare_uid=ref_uid, expected_gate="name",
                             expected_match_entity="", is_new_numbering=True))

    # 3d. identifier_collision: 다른 entity 인데 기존 reference 의 code 를 오입력
    for k, sid in enumerate(rich_sids[:3]):
        victim_eid = eids[rich_sids[(k + 1) % len(rich_sids)]]
        variant = _mk_ref_row(seed_rows[sid], "", f"IDCOL{k}")
        variant["기업식별 코드"] = synth_code(victim_eid)   # 남의 코드
        variant["STD 업체명"] = f"Collision Corp {k}"
        g = ec.to_gate_row(seed_rows[sid])
        lat, lon = pt.offset_coord(g["coord"][0], g["coord"][1], 500000, 180)
        pt._set_coord(variant, lat, lon)
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant["row_uid"] = uid
        queries.append({c: variant.get(c, "") for c in BUSINESS_COLS})
        labels.append(_label(uid, f"IDCOL{k}", sid, "query", "identifier_collision",
                             "shared_code_diff_entity", "code", "hard",
                             expected_match_entity="", is_new_numbering=True))

    # ---- 4. 신규 채번 쿼리 (기준 DB 에 없음) ----------------------------------
    novel = [
        ("Nebula Quantum Devices", "US:미합중국"),
        ("Aurora Photonics KK", "JP:일본"),
        ("Meridian Vacuum Systems", "DE:독일"),
        ("Zephyr Thin Film", "TW:대만"),
    ]
    for k, (nm, region) in enumerate(novel):
        eid = f"NEW{k}"
        variant = {c: "" for c in BUSINESS_COLS}
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant.update({
            "row_uid": uid, "STD 업체명": nm, "업체명 (Eng)": nm, "국가/지역": region,
            "표준화": ec.gc.STATUS_VERIFIED, "기업식별 코드": synth_code(eid),
            "Duns No.": synth_duns(eid),
            # reference 와 겹치지 않는 좌표(태평양)
            "표준 위도": f"{10.0 + k:.6f}", "표준 경도": f"{-150.0 - k:.6f}",
        })
        queries.append(variant)
        labels.append(_label(uid, eid, "", "query", "new_numbering", "novel_entity",
                             "", "easy", expected_match_entity="", is_new_numbering=True))

    # ---- 5. TN_random 쿼리 (완전 무관) ----------------------------------------
    for k in range(3):
        eid = f"TN{k}"
        variant = {c: "" for c in BUSINESS_COLS}
        qseq += 1
        uid = f"Q{qseq:04d}"
        variant.update({
            "row_uid": uid, "STD 업체명": f"Random Unrelated {k}",
            "업체명 (Eng)": f"Random Unrelated {k}", "국가/지역": "BR:브라질",
            "표준화": ec.gc.STATUS_VERIFIED, "기업식별 코드": synth_code(eid),
            "Duns No.": synth_duns(eid),
            "표준 위도": f"{-20.0 - k:.6f}", "표준 경도": f"{-45.0 - k:.6f}",
        })
        queries.append(variant)
        labels.append(_label(uid, eid, "", "query", "TN_random", "unrelated",
                             "", "easy", expected_match_entity="", is_new_numbering=True))

    return references, queries, labels


def _self_check(references, queries, labels):
    """데이터셋 정합성 assert (설계 문서 §7)."""
    import json
    label_by_uid = {l["row_uid"]: l for l in labels}
    # 모든 행에 라벨 존재
    for row in references + queries:
        assert row["row_uid"] in label_by_uid, f"라벨 누락: {row['row_uid']}"
    # 식별자 정규화
    for row in references:
        c = ec.dd.normalize_code(row["기업식별 코드"])
        d = ec.dd.normalize_duns(row["Duns No."])
        assert c, f"code 정규화 실패: {row['row_uid']}"
        assert d and len(d) == 9, f"duns 9자리 아님: {row['row_uid']} -> {d}"
    # addressComponents JSON round-trip
    for row in references + queries:
        ac = row.get("addressComponents") or ""
        if ac:
            assert isinstance(json.loads(ac), list), f"addressComponents 손상: {row['row_uid']}"
    # Oracle spot-check: 결정적 TP 변형은 실제 gate 판정이 기대와 일치해야 함
    ref_by_uid = {r["row_uid"]: r for r in references}
    q_by_uid = {q["row_uid"]: q for q in queries}
    mismatches = []
    for l in labels:
        if l["role"] != "query" or not l["expected_verdict"] or not l["compare_uid"]:
            continue
        if l["variant_type"] == "name_word_order":   # 관측 전용(단정 안 함)
            continue
        base = ref_by_uid.get(l["compare_uid"])
        q = q_by_uid.get(l["row_uid"])
        if not base or not q:
            continue
        actual = ec.gate_verdicts(base, q)[l["expected_gate"]]
        if actual != l["expected_verdict"]:
            mismatches.append((l["row_uid"], l["variant_type"], l["expected_gate"],
                               l["expected_verdict"], actual))
    # Oracle spot-check(복합): component_gates 의 결정적 성분별 gate 판정 검증
    for l in labels:
        if l["role"] != "query" or not l["component_gates"] or not l["compare_uid"]:
            continue
        base = ref_by_uid.get(l["compare_uid"])
        q = q_by_uid.get(l["row_uid"])
        if not base or not q:
            continue
        actual_v = ec.gate_verdicts(base, q)
        for pair in l["component_gates"].split(";"):
            gate, expv = pair.split(":")
            if actual_v[gate] != expv:
                mismatches.append((l["row_uid"], l["variant_type"], gate,
                                   expv, actual_v[gate]))
    assert not mismatches, "Oracle 불일치:\n" + "\n".join(str(m) for m in mismatches)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Golden Dataset 생성")
    ap.add_argument("--seed", default=os.path.join(ec.DATA_DIR,
                    "STD_VLD_260926_site_master_TF_2_std.xlsx"))
    ap.add_argument("--sheet", default="TF_std_2")
    ap.add_argument("--variants-per-entity", type=int, default=4)
    ap.add_argument("--combos-per-entity", type=int, default=2)
    args = ap.parse_args(argv)

    references, queries, labels = build(args.seed, args.sheet,
                                        args.variants_per_entity, args.combos_per_entity)
    _self_check(references, queries, labels)

    ref_df = pd.DataFrame(references, columns=BUSINESS_COLS)
    q_df = pd.DataFrame(queries, columns=BUSINESS_COLS)
    lab_df = pd.DataFrame(labels, columns=LABEL_COLS)

    ref_xlsx = os.path.join(ec.DATA_DIR, "SIM_260929_golden_reference.xlsx")
    ref_csv = os.path.join(ec.DATA_DIR, "SIM_260929_golden_reference.csv")
    q_xlsx = os.path.join(ec.DATA_DIR, "SIM_260929_golden_queries.xlsx")
    lab_csv = os.path.join(ec.DATA_DIR, "SIM_260929_golden_labels.csv")
    ref_df.to_excel(ref_xlsx, index=False)
    ref_df.to_csv(ref_csv, index=False, encoding="utf-8-sig")
    q_df.to_excel(q_xlsx, index=False)
    lab_df.to_csv(lab_csv, index=False, encoding="utf-8-sig")

    # manifest
    print(f"[생성 완료] reference={len(references)}행  queries={len(queries)}행")
    print("\n=== case_class 분포 (labels) ===")
    print(lab_df["case_class"].value_counts().to_string())
    print("\n=== variant_type 분포 (query only) ===")
    print(lab_df[lab_df.role == "query"]["variant_type"].value_counts().to_string())
    print("\n=== difficulty 분포 (query only) ===")
    qd = lab_df[lab_df.role == "query"]
    print(qd[qd.difficulty != ""]["difficulty"].value_counts().to_string())
    print(f"\n출력:\n  {ref_xlsx}\n  {ref_csv}\n  {q_xlsx}\n  {lab_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
