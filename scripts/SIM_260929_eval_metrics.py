# -*- coding: utf-8 -*-
"""유사 검색 / 중복 제거 평가 지표.

- Menu 4 (유사 검색): Top-1 / Recall@k / MRR, 코드매핑 vs 신규채번 결정 P/R/F1 + 임계값 스윕
- Menu 3 (중복 제거): pairwise P/R/F1, ARI/V-measure, 오병합 목록, suspect 분석
- per-gate 혼동행렬

설계 문서: documents/Site Code 채번 고도화_260929_Similarity_Golden Dataset 설계.md
"""

from sklearn.metrics import (adjusted_rand_score,
                             homogeneity_completeness_v_measure)

VERDICTS = ("EQUAL", "SIMILAR", "DIFFERENT", "SKIP")


# ---------------------------------------------------------------------------
# Menu 4 — 검색 품질
# ---------------------------------------------------------------------------
def ranking_metrics(query_results: list):
    """query_results: [{expected_entity, is_new, ranked_entities:[eid...]}]

    TP 쿼리(expected_entity 존재)에 대한 Top-1/Recall@k/MRR.

    Args:
        query_results (list): 쿼리 결과 dict 리스트.

    Returns:
        dict: {n_tp_queries, top1_accuracy, recall_at_k, mrr}. TP 없으면 {}.
    """
    tp = [q for q in query_results if q["expected_entity"] and not q["is_new"]]
    if not tp:
        return {}
    ks = (1, 3, 5, 8)
    top1 = 0
    recall = {k: 0 for k in ks}
    mrr = 0.0
    for q in tp:
        exp = q["expected_entity"]
        ranked = q["ranked_entities"]
        if ranked and ranked[0] == exp:
            top1 += 1
        rank = next((i + 1 for i, e in enumerate(ranked) if e == exp), None)
        if rank:
            mrr += 1.0 / rank
        for k in ks:
            if exp in ranked[:k]:
                recall[k] += 1
    n = len(tp)
    return {
        "n_tp_queries": n,
        "top1_accuracy": top1 / n,
        "recall_at_k": {k: recall[k] / n for k in ks},
        "mrr": mrr / n,
    }


def decision_at_threshold(query_results: list, t: int):
    """기준점수 t 에서 코드매핑 vs 신규채번 판정 성능.

    positive = "매핑되어야 함"(expected_entity 존재). negative = 신규채번(is_new).
    예측: top1_score >= t 이고 top1_entity == expected 이면 정매핑(TP).
          top1_score >= t 인데 신규거나 엉뚱한 entity 면 오매핑(FP).
          top1_score < t 이면 신규채번 예측.

    Args:
        query_results (list): 쿼리 결과 dict 리스트.
        t (int): 매핑/신규 결정 기준 점수.

    Returns:
        dict: {t, tp, fp, fn, tn, precision, recall, f1, tpr, fpr}.
    """
    tp = fp = fn = tn = 0
    for q in query_results:
        score = q["top1_score"]
        pred_map = score >= t
        if q["is_new"]:                       # 신규채번이 정답 (negative)
            if pred_map:
                fp += 1                       # 신규인데 매핑함
            else:
                tn += 1
        else:                                 # 매핑이 정답 (positive)
            correct_entity = (q["ranked_entities"][:1] == [q["expected_entity"]])
            if pred_map and correct_entity:
                tp += 1
            elif pred_map and not correct_entity:
                fp += 1                       # 엉뚱한 entity 로 매핑
                fn += 1                       # 정답 매핑은 놓침
            else:
                fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    tpr = rec
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"t": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec, "f1": f1, "tpr": tpr, "fpr": fpr}


def score_distribution(query_results: list):
    """TP 쿼리 top1 점수 분포를 case_class·difficulty·variant_type 별로 요약.

    복합 변형이 실제로 점수를 중간대로 퍼뜨리는지(sweep 변별력 확보) 검증한다.
    반환: {group_key: {n, min, p25, median, p75, max, mean}}

    Args:
        query_results (list): 쿼리 결과 dict 리스트.

    Returns:
        dict: {group_key: 점수 요약 통계}. group_key는 'class:'/'variant:'/'difficulty:' 접두.
    """
    def _summary(vals):
        """점수 리스트의 분위 통계(min/p25/median/p75/max/mean)를 반환."""
        v = sorted(vals)
        n = len(v)
        mean = sum(v) / n
        return {"n": n, "min": v[0], "p25": v[n // 4], "median": v[n // 2],
                "p75": v[min(3 * n // 4, n - 1)], "max": v[-1], "mean": round(mean, 1)}

    groups = {}
    tp = [q for q in query_results if q["expected_entity"] and not q["is_new"]]
    for key_fn, prefix in (
            (lambda q: q["case_class"], "class"),
            (lambda q: q["variant_type"], "variant"),
            (lambda q: q["difficulty"], "difficulty")):
        buckets = {}
        for q in tp:
            buckets.setdefault(key_fn(q), []).append(q["top1_score"])
        for k, vals in buckets.items():
            if vals:
                groups[f"{prefix}:{k}"] = _summary(vals)
    return groups


def threshold_sweep(query_results: list, ts=range(0, 101)):
    """t=0..100 결정 성능 곡선 + F1 최대 / precision>=0.95 최소 t.

    Args:
        query_results (list): 쿼리 결과 dict 리스트.
        ts (iterable, optional): 스윕할 기준 점수 범위. 기본 range(0, 101).

    Returns:
        dict: {curve, best_f1, precision95_min_t}.
    """
    curve = [decision_at_threshold(query_results, t) for t in ts]
    best_f1 = max(curve, key=lambda r: r["f1"])
    hi_prec = [r for r in curve if r["precision"] >= 0.95]
    hi_prec_t = min(hi_prec, key=lambda r: r["t"])["t"] if hi_prec else None
    return {"curve": curve, "best_f1": best_f1, "precision95_min_t": hi_prec_t}


# ---------------------------------------------------------------------------
# Menu 3 — 중복 제거 품질
# ---------------------------------------------------------------------------
def _pairs_within(groups):
    """[[idx...]] 클러스터 → 같은 그룹 내 (i<j) 쌍 집합.

    Args:
        groups (iterable): 멤버 인덱스 리스트들의 모음.

    Returns:
        set: 같은 그룹에 속한 (i, j) 쌍 집합(i<j).
    """
    pairs = set()
    for members in groups:
        m = sorted(members)
        for x in range(len(m)):
            for y in range(x + 1, len(m)):
                pairs.add((m[x], m[y]))
    return pairs


def dedup_metrics(clusters, gold_labels, active_idx):
    """clusters: dedup 결과 [{member_indices,...}]
    gold_labels: 행 인덱스 → entity_id (정답)
    active_idx: 평가 대상 행 인덱스 리스트 (실패행 제외 등)

    반환: pairwise P/R/F1, 클러스터 지표, 오병합 쌍 목록.

    Args:
        clusters (list): dedup 결과 클러스터 리스트.
        gold_labels (dict | list): 행 인덱스 → 정답 entity_id.
        active_idx (iterable): 평가 대상 행 인덱스.

    Returns:
        dict: {pairwise, cluster, false_merges, n_clusters}.
    """
    active = list(active_idx)
    # 예측 쌍
    pred_pairs = _pairs_within([c["member_indices"] for c in clusters])
    # 정답 쌍: active 내 동일 entity
    gold_groups = {}
    for i in active:
        gold_groups.setdefault(gold_labels[i], []).append(i)
    gold_pairs = _pairs_within(gold_groups.values())

    tp = len(pred_pairs & gold_pairs)
    fp = len(pred_pairs - gold_pairs)
    fn = len(gold_pairs - pred_pairs)
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    # 오병합(false merge): 예측 같은 클러스터인데 다른 entity
    false_merges = [(i, j, gold_labels[i], gold_labels[j])
                    for (i, j) in sorted(pred_pairs - gold_pairs)]

    # 클러스터 라벨 벡터 (싱글톤은 고유 id)
    row_to_cluster = {}
    for ci, c in enumerate(clusters):
        for i in c["member_indices"]:
            row_to_cluster[i] = ci
    next_id = len(clusters)
    pred_vec, gold_vec = [], []
    for i in active:
        if i in row_to_cluster:
            pred_vec.append(row_to_cluster[i])
        else:
            pred_vec.append(next_id)
            next_id += 1
        gold_vec.append(gold_labels[i])
    ari = adjusted_rand_score(gold_vec, pred_vec)
    homo, comp, vmeas = homogeneity_completeness_v_measure(gold_vec, pred_vec)

    return {
        "pairwise": {"tp": tp, "fp": fp, "fn": fn,
                     "precision": prec, "recall": rec, "f1": f1},
        "cluster": {"ari": ari, "homogeneity": homo,
                    "completeness": comp, "v_measure": vmeas},
        "false_merges": false_merges,
        "n_clusters": len(clusters),
    }


def suspect_analysis(suspects, gold_labels):
    """의심 엣지의 TP(동일 entity)/FP(다른 entity) + 사유 분포.

    Args:
        suspects (list): dedup 의심 엣지 리스트.
        gold_labels (dict | list): 행 인덱스 → 정답 entity_id.

    Returns:
        dict: {n, tp, fp, reasons}.
    """
    tp = fp = 0
    reasons = {}
    for e in suspects:
        i, j = e["pair"]
        same = gold_labels[i] == gold_labels[j]
        if same:
            tp += 1
        else:
            fp += 1
        reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
    return {"n": len(suspects), "tp": tp, "fp": fp, "reasons": reasons}


# ---------------------------------------------------------------------------
# per-gate 진단
# ---------------------------------------------------------------------------
def gate_confusion(rows):
    """rows: [{gate, expected, actual}] → gate 별 expected×actual 혼동행렬.

    Args:
        rows (list): {gate, expected, actual} dict 리스트.

    Returns:
        dict: {gate: {expected_verdict: {actual_verdict: count}}}.
    """
    out = {}
    for r in rows:
        g = r["gate"]
        mat = out.setdefault(g, {e: {a: 0 for a in VERDICTS} for e in VERDICTS})
        if r["expected"] in mat and r["actual"] in mat[r["expected"]]:
            mat[r["expected"]][r["actual"]] += 1
    return out
