# -*- coding: utf-8 -*-
"""유사 검색 / 중복 제거 성능 평가 오케스트레이터.

Golden Dataset(SIM_260929_build_golden.py 산출물)을 로드해 코어 매칭 로직을
결정적으로 평가하고 리포트/CSV/콘솔 요약을 산출한다.

사용:
  .venv/Scripts/python.exe scripts/SIM_260929_run_eval.py [--sweep] [--top-k N]

산출:
  docs/reports/SIM_260929_eval_report.md
  docs/reports/SIM_260929_eval_failures.csv
  docs/reports/SIM_260929_threshold_sweep.csv
  docs/reports/SIM_260929_gate_confusion.csv
"""

import argparse
import os

import pandas as pd

import SIM_260929_eval_common as ec
import SIM_260929_eval_metrics as mt

DEFAULT_T = 60


# ---------------------------------------------------------------------------
def _load():
    ref = pd.read_excel(os.path.join(ec.DATA_DIR, "SIM_260929_golden_reference.xlsx"),
                        dtype=str).fillna("").to_dict("records")
    q = pd.read_excel(os.path.join(ec.DATA_DIR, "SIM_260929_golden_queries.xlsx"),
                      dtype=str).fillna("").to_dict("records")
    lab = pd.read_csv(os.path.join(ec.DATA_DIR, "SIM_260929_golden_labels.csv"),
                      dtype=str).fillna("").to_dict("records")
    labels = {l["row_uid"]: l for l in lab}
    return ref, q, labels


def _run_similarity(ref, queries, labels, top_k):
    """각 쿼리에 대해 find_similar 실행 → ranking/decision 입력 형태로 변환."""
    ref_eid = [labels[r["row_uid"]]["entity_id"] for r in ref]
    results, failures = [], []
    for q in queries:
        lab = labels[q["row_uid"]]
        matches = ec.find_similar(q, ref, top_k=top_k)
        ranked = [ref_eid[m["ref_index"]] for m in matches]
        top1_score = matches[0]["avg"] if matches else 0
        is_new = lab["is_new_numbering"] == "True"
        exp = lab["expected_match_entity"]
        rec = {
            "row_uid": q["row_uid"], "case_class": lab["case_class"],
            "variant_type": lab["variant_type"], "difficulty": lab["difficulty"],
            "expected_entity": exp, "is_new": is_new,
            "ranked_entities": ranked, "top1_score": top1_score,
            "top1_entity": ranked[0] if ranked else "",
        }
        results.append(rec)
        # 실패 케이스 수집 (기본 T=60 기준)
        pred_map = top1_score >= DEFAULT_T
        if is_new and pred_map:
            failures.append({**_fail_base(rec), "issue": "신규인데_매핑",
                             "detail": f"top1={rec['top1_entity']}"})
        elif (not is_new) and (not pred_map):
            failures.append({**_fail_base(rec), "issue": "매핑실패_신규채번",
                             "detail": f"score={top1_score}<{DEFAULT_T}"})
        elif (not is_new) and pred_map and rec["top1_entity"] != exp:
            failures.append({**_fail_base(rec), "issue": "오매핑",
                             "detail": f"top1={rec['top1_entity']} != {exp}"})
    return results, failures


def _fail_base(rec):
    return {"row_uid": rec["row_uid"], "case_class": rec["case_class"],
            "variant_type": rec["variant_type"], "top1_score": rec["top1_score"]}


def _run_dedup(ref, labels):
    gate_rows = ec.dd._to_rows(ref)
    result = ec.dd.dedup(gate_rows)
    gold = [labels[r["row_uid"]]["entity_id"] for r in ref]
    active = [i for i, gr in enumerate(gate_rows)
              if gr.get("status") != ec.gc.STATUS_FAILED]
    metrics = mt.dedup_metrics(result["clusters"], gold, active)
    suspects = mt.suspect_analysis(result["suspects"], gold)
    return result, metrics, suspects, gold


def _run_gate_diag(ref, queries, labels):
    ref_by_uid = {r["row_uid"]: r for r in ref}
    q_by_uid = {q["row_uid"]: q for q in queries}
    rows = []
    for uid, lab in labels.items():
        if lab["role"] != "query" or not lab["compare_uid"]:
            continue
        base = ref_by_uid.get(lab["compare_uid"])
        q = q_by_uid.get(uid)
        if not base or not q:
            continue
        verdicts = ec.gate_verdicts(base, q)
        # 단일 변형: expected_gate + expected_verdict
        if lab["expected_verdict"]:
            rows.append({"gate": lab["expected_gate"], "expected": lab["expected_verdict"],
                         "actual": verdicts[lab["expected_gate"]], "row_uid": uid,
                         "variant_type": lab["variant_type"]})
        # 복합 변형: component_gates("gate:verdict;...")의 결정적 성분 전개
        if lab.get("component_gates"):
            for pair in lab["component_gates"].split(";"):
                gate, expv = pair.split(":")
                rows.append({"gate": gate, "expected": expv, "actual": verdicts[gate],
                             "row_uid": uid, "variant_type": lab["variant_type"]})
    return rows


def _sweep_thresholds(ref, queries, labels, top_k):
    """임계값 one-at-a-time 스윕 → [{param,value,dedup_f1,menu4_f1}]."""
    grids = {
        "SIM_THRESHOLD": ("name_threshold", [0.80, 0.82, 0.85, 0.88, 0.90, 0.92]),
        "COORD_EQUAL_M": ("coord_m", [50, 75, 100, 150, 200]),
        "ADDR_LOWER_JACCARD": ("addr_jaccard", [0.4, 0.5, 0.6]),
    }
    out = []
    for pname, (kw, values) in grids.items():
        for v in values:
            with ec.override_thresholds(**{kw: v}):
                sim_res, _ = _run_similarity(ref, queries, labels, top_k)
                _, dd_m, _, _ = _run_dedup(ref, labels)
            menu4 = mt.decision_at_threshold(sim_res, DEFAULT_T)["f1"]
            out.append({"param": pname, "value": v,
                        "dedup_f1": round(dd_m["pairwise"]["f1"], 4),
                        "menu4_decision_f1": round(menu4, 4)})
    return out


# ---------------------------------------------------------------------------
def _write_report(path, rank, sweep, dd_m, suspects, gate_conf, gate_rows,
                  sim_res, top_k):
    L = []
    L.append("# 유사 검색 / 중복 제거 성능 평가 리포트\n")
    L.append(f"- 대상 로직: `scripts/SIM_260926_dedup.py` (dedup + find_similar)")
    L.append(f"- 쿼리 {len(sim_res)}건, top_k={top_k}, 기준점수 T={DEFAULT_T}\n")

    # 평가 방법론
    L.append("## 무엇을, 어떻게 평가했나\n")
    L.append("**평가 대상**: 3번(중복 제거)·4번(유사 검색) 메뉴가 공유하는 5-gate 매칭 "
             "파이프라인(`code/duns/addr/coord/name` gate). 표준화는 seed(`TF_std_2`)에 "
             "이미 고정돼 있어 Google API 없이 결정적으로 재현 평가한다(Layer A).\n")
    L.append("**Golden Dataset(자동 생성)**: 표준화 완료 seed 38행에 entity_id·합성 식별자"
             "(코드/Duns)를 부여해 **기준 DB**를 만들고, 각 entity에 자동 변형(perturbation)을 "
             "가해 **쿼리**를 생성한다. 모든 변형은 *표준화 이후 데이터 불변식*을 지킨다 — "
             "주소는 Google 지오코딩 출력이라 오탈자 없이 표기·granularity·순서·결측만, "
             "업체명·식별자는 오탈자까지 허용.")
    L.append("- **단일 변형(TP_variant)**: 한 필드만 열화(이름 접미사/오타, 주소 표기/결측, "
             "좌표 이탈/결측, 식별자 하이픈/오타/결측). 각 변형은 목표 gate 판정(EQUAL/"
             "SIMILAR/DIFFERENT/SKIP)을 갖는다.")
    L.append("- **복합 변형(TP_composite)**: 여러 필드를 동시 열화. 스코어링이 강신호 지배"
             "(`base=max(αG+(1-α)N, g_strong, N)`)라 단일 변형은 나머지 canonical 신호가 "
             "점수를 100으로 복원한다. 이름·식별자를 함께 떨어뜨려 점수를 중간대로 분산시켜 "
             "임계값 변별력을 만든다.")
    L.append("- **Hard Negative**: FP_adjacent(같은 좌표·다른 업체), FP_branch(같은 이름·다른 "
             "지역), FP_similar_name(stopword만 다른 유사명), identifier_collision(남의 코드 "
             "오입력) — 매칭되면 안 되는 함정. **new_numbering**(기준 DB에 없는 신규)·TN_random"
             "은 '신규 채번'이 정답인 negative.")
    L.append("**정답 라벨**은 별도 `labels.csv`(entity_id 등)에 두고 SUT엔 업무 컬럼만 입력, "
             "`row_uid`로 조인해 정보 누출을 막는다.\n")
    L.append("**측정 지표**:")
    L.append("- Menu4 검색: Top-1 정확도 / Recall@k / MRR (정답 entity가 상위에 오는가).")
    L.append("- Menu4 판정: top1 점수 ≥ T & 정답 entity면 코드매핑, 아니면 신규채번으로 보고 "
             "P/R/F1 + 임계값 스윕(T=0~100)으로 최적 T 탐색. new_numbering이 negative.")
    L.append("- Menu3 중복: pairwise P/R/F1 + 클러스터 지표(ARI/V-measure) + **오병합 건수**"
             "(다른 entity를 한 클러스터로 묶은 쌍, 심각도 최상).")
    L.append("- Gate 단위: 각 변형을 상대와 직접 비교해 gate별 기대×실제 혼동행렬 산출 → "
             "E2E 실패 시 책임 gate 격리.")
    L.append("- 임계값 스윕: `SIM_THRESHOLD`/`COORD_EQUAL_M`/`ADDR_LOWER_JACCARD`를 "
             "one-at-a-time로 바꿔가며 두 메뉴 F1 변화 관측 → 기본값 재튜닝 근거.\n")

    # Menu 4
    L.append("## Menu 4 — 유사 검색\n")
    L.append("### 검색 품질 (TP 쿼리)")
    L.append(f"- 대상 TP 쿼리: {rank['n_tp_queries']}건")
    L.append(f"- **Top-1 정확도: {rank['top1_accuracy']:.3f}**")
    L.append(f"- Recall@k: " + ", ".join(
        f"@{k}={v:.3f}" for k, v in rank["recall_at_k"].items()))
    L.append(f"- **MRR: {rank['mrr']:.3f}**\n")

    d60 = mt.decision_at_threshold(sim_res, DEFAULT_T)
    L.append(f"### 코드매핑 vs 신규채번 판정 (T={DEFAULT_T})")
    L.append(f"- TP={d60['tp']} FP={d60['fp']} FN={d60['fn']} TN={d60['tn']}")
    L.append(f"- **정밀도 {d60['precision']:.3f} / 재현율 {d60['recall']:.3f} "
             f"/ F1 {d60['f1']:.3f}**")
    bf = sweep_best(sim_res)
    L.append(f"- 임계값 스윕: F1 최대 T={bf['best_f1']['t']} "
             f"(F1={bf['best_f1']['f1']:.3f}), "
             f"precision≥0.95 최소 T={bf['precision95_min_t']}\n")

    # 점수 분포 (복합 변형 변별력 검증)
    dist = mt.score_distribution(sim_res)
    L.append("### TP 점수 분포 (top1 avg)")
    L.append("복합(TP_composite) 변형이 점수를 중간대로 분산시켜 임계값 변별력을 만든다.\n")
    L.append("| 그룹 | n | min | p25 | median | p75 | max | mean |")
    L.append("|---|---|---|---|---|---|---|---|")
    order = [k for k in dist if k.startswith("class:")] + \
            [k for k in dist if k.startswith("variant:combo")] + \
            [k for k in dist if k.startswith("difficulty:")]
    for k in order:
        s = dist[k]
        L.append(f"| {k} | {s['n']} | {s['min']} | {s['p25']} | {s['median']} "
                 f"| {s['p75']} | {s['max']} | {s['mean']} |")
    L.append("")

    # Menu 3
    pw = dd_m["pairwise"]; cl = dd_m["cluster"]
    L.append("## Menu 3 — 중복 제거\n")
    L.append(f"- 클러스터 수: {dd_m['n_clusters']}")
    L.append(f"- **Pairwise 정밀도 {pw['precision']:.3f} / 재현율 {pw['recall']:.3f} "
             f"/ F1 {pw['f1']:.3f}** (TP={pw['tp']} FP={pw['fp']} FN={pw['fn']})")
    L.append(f"- 클러스터 지표: ARI={cl['ari']:.3f}, V-measure={cl['v_measure']:.3f} "
             f"(homo={cl['homogeneity']:.3f}, comp={cl['completeness']:.3f})")
    L.append(f"- **오병합(false merge): {len(dd_m['false_merges'])}건** (심각도 최상)")
    for (i, j, ea, eb) in dd_m["false_merges"]:
        L.append(f"  - 행[{i}]({ea}) ↔ 행[{j}]({eb})")
    L.append(f"- 의심(SUSPECT) 엣지: {suspects['n']}건 "
             f"(TP={suspects['tp']} FP={suspects['fp']}), 사유={suspects['reasons']}\n")

    # per-gate
    L.append("## Gate 단위 진단\n")
    L.append("결정적 변형의 기대 판정 대비 실제 판정 (행=기대, 열=실제):\n")
    for gate, mat in gate_conf.items():
        total = sum(sum(r.values()) for r in mat.values())
        if not total:
            continue
        correct = sum(mat[v][v] for v in mt.VERDICTS)
        L.append(f"### {gate} (정합 {correct}/{total})")
        L.append("| 기대\\실제 | " + " | ".join(mt.VERDICTS) + " |")
        L.append("|" + "---|" * (len(mt.VERDICTS) + 1))
        for e in mt.VERDICTS:
            if sum(mat[e].values()) == 0:
                continue
            L.append(f"| {e} | " + " | ".join(str(mat[e][a]) for a in mt.VERDICTS) + " |")
        L.append("")

    # 튜닝 권고
    L.append("## 임계값 튜닝 스윕 (one-at-a-time)\n")
    L.append("| 파라미터 | 값 | dedup F1 | Menu4 결정 F1 |")
    L.append("|---|---|---|---|")
    for r in sweep:
        L.append(f"| {r['param']} | {r['value']} | {r['dedup_f1']} | "
                 f"{r['menu4_decision_f1']} |")
    L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def sweep_best(sim_res):
    return mt.threshold_sweep(sim_res)


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Golden Dataset 평가 실행")
    ap.add_argument("--sweep", action="store_true", help="임계값 스윕 수행")
    ap.add_argument("--top-k", type=int, default=8)
    args = ap.parse_args(argv)

    os.makedirs(ec.REPORTS_DIR, exist_ok=True)
    ref, queries, labels = _load()

    sim_res, failures = _run_similarity(ref, queries, labels, args.top_k)
    rank = mt.ranking_metrics(sim_res)
    _, dd_m, suspects, _ = _run_dedup(ref, labels)
    gate_rows = _run_gate_diag(ref, queries, labels)
    gate_conf = mt.gate_confusion(gate_rows)
    sweep = _sweep_thresholds(ref, queries, labels, args.top_k) if args.sweep else []

    # CSV 산출
    pd.DataFrame(failures).to_csv(
        os.path.join(ec.REPORTS_DIR, "SIM_260929_eval_failures.csv"),
        index=False, encoding="utf-8-sig")
    if sweep:
        pd.DataFrame(sweep).to_csv(
            os.path.join(ec.REPORTS_DIR, "SIM_260929_threshold_sweep.csv"),
            index=False, encoding="utf-8-sig")
    # gate confusion long-form
    gc_rows = [{"gate": g, "expected": e, "actual": a, "count": gate_conf[g][e][a]}
               for g in gate_conf for e in mt.VERDICTS for a in mt.VERDICTS
               if gate_conf[g][e][a]]
    pd.DataFrame(gc_rows).to_csv(
        os.path.join(ec.REPORTS_DIR, "SIM_260929_gate_confusion.csv"),
        index=False, encoding="utf-8-sig")

    report_path = os.path.join(ec.REPORTS_DIR, "SIM_260929_eval_report.md")
    _write_report(report_path, rank, sweep, dd_m, suspects, gate_conf,
                  gate_rows, sim_res, args.top_k)

    # 콘솔 요약
    d60 = mt.decision_at_threshold(sim_res, DEFAULT_T)
    print("=" * 60)
    print("유사 검색 / 중복 제거 평가 요약")
    print("=" * 60)
    print(f"[Menu4 검색] Top-1={rank['top1_accuracy']:.3f}  "
          f"Recall@8={rank['recall_at_k'][8]:.3f}  MRR={rank['mrr']:.3f}")
    print(f"[Menu4 판정 T=60] P={d60['precision']:.3f} R={d60['recall']:.3f} "
          f"F1={d60['f1']:.3f}  (TP{d60['tp']}/FP{d60['fp']}/FN{d60['fn']}/TN{d60['tn']})")
    print(f"[Menu3 중복] pairwise F1={dd_m['pairwise']['f1']:.3f}  "
          f"ARI={dd_m['cluster']['ari']:.3f}  오병합={len(dd_m['false_merges'])}건")
    print(f"[Menu3 의심] {suspects['n']}건 (TP{suspects['tp']}/FP{suspects['fp']})")
    gate_ok = sum(gate_conf[g][v][v] for g in gate_conf for v in mt.VERDICTS)
    gate_tot = sum(gate_conf[g][e][a] for g in gate_conf
                   for e in mt.VERDICTS for a in mt.VERDICTS)
    print(f"[Gate 진단] 결정적 변형 정합 {gate_ok}/{gate_tot}")
    print(f"[실패 케이스] {len(failures)}건 → SIM_260929_eval_failures.csv")
    print(f"\n리포트: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
