"use client";
import { useCallback, useEffect, useState } from "react";
import TwoPane from "@/components/TwoPane";
import PaneBox from "@/components/PaneBox";
import DataTable from "@/components/DataTable";
import SaveModal from "@/components/SaveModal";
import TableList from "@/components/TableList";
import ResultDock from "@/components/ResultDock";
import { api } from "@/lib/api";
import { toast } from "@/lib/toast";
import { rowLabel, mapUrls } from "@/lib/ui";
import type { Cluster, SiteRow, Suspect, TableMeta, DedupThresholds } from "@/lib/types";

const DISPLAY_COLS = ["업체", "STD 업체명", "기업식별 코드", "Duns No.", "국가/지역", "주소(Eng)", "STD 주소"];

export default function DedupPage() {
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<SiteRow[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set()); // 좌측 행 선택(수동 클러스터용)
  const [clusters, setClusters] = useState<Cluster[]>([]); // representative를 각 클러스터에 내장
  const [suspects, setSuspects] = useState<Suspect[]>([]);
  const [applied, setApplied] = useState<SiteRow[]>([]);
  const [dockOpen, setDockOpen] = useState(false);
  const [ratio, setRatio] = useState(7);
  const [loading, setLoading] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [ran, setRan] = useState(false);

  // 임계치 (슬라이더 → 0~1 또는 m)
  const [thName, setThName] = useState(85);   // %
  const [thAddr, setThAddr] = useState(50);   // %
  const [thCoord, setThCoord] = useState(100); // m

  const refresh = useCallback(async () => {
    try { setTables((await api.listTables("standardized")).tables); } catch { /* noop */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const load = async () => {
    if (!picked.size) { toast("불러올 테이블을 선택하세요"); return; }
    const loaded: SiteRow[] = [];
    for (const name of picked) {
      try {
        const t = await api.loadTable("standardized", name);
        t.rows.forEach((r) => loaded.push({ ...r }));
      } catch { toast(`"${name}" 로드 실패`); }
    }
    setRows((prev) => [...prev, ...loaded]);
    setPicked(new Set());
    toast(`${loaded.length}행 로드 (누적 ${rows.length + loaded.length}행)`);
  };

  const toggleRow = (i: number) => setSelected((s) => {
    const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n;
  });
  const toggleAll = (checked: boolean) =>
    setSelected(checked ? new Set(rows.map((_, i) => i)) : new Set());

  const run = async () => {
    if (!rows.length) { toast("먼저 데이터를 로드하세요"); return; }
    const thresholds: DedupThresholds = {
      name_threshold: thName / 100,
      addr_jaccard: thAddr / 100,
      coord_m: thCoord,
    };
    setLoading(true);
    try {
      const res = await api.dedup(rows, thresholds);
      setClusters(res.clusters);
      setSuspects(res.suspects);
      setRan(true);
      setRatio(3);
      toast(`중복 분석 완료 — 클러스터 ${res.clusters.length}개, 의심 ${res.suspects.length}건`);
    } catch (e) {
      toast((e as Error).message || "중복 분석 실패");
    } finally {
      setLoading(false);
    }
  };

  // 좌측 선택 행으로 새 클러스터 수동 생성.
  const createCluster = () => {
    const members = [...selected].sort((a, b) => a - b);
    if (members.length < 2) { toast("2개 이상의 행을 선택해 클러스터를 만드세요"); return; }
    setClusters((prev) => [...prev, { member_indices: members, representative: members[0] }]);
    setSelected(new Set());
    setRan(true);
    setRatio(3);
    toast(`클러스터 생성 — ${members.length}개 행`);
  };

  // 좌측 선택 행을 기존 클러스터에 추가.
  const addSelectedToCluster = (ci: number) => {
    const add = [...selected];
    if (!add.length) { toast("좌측에서 추가할 행을 선택하세요"); return; }
    setClusters((prev) => prev.map((c, k) => k === ci
      ? { ...c, member_indices: [...new Set([...c.member_indices, ...add])].sort((a, b) => a - b) }
      : c));
    setSelected(new Set());
    toast(`${add.length}개 행을 클러스터 ${ci + 1}에 추가`);
  };

  // 클러스터에서 특정 항목 제외. 대표가 빠지면 남은 첫 행을 대표로. 멤버 2개 미만이면 해지.
  const removeMember = (ci: number, ri: number) => {
    setClusters((prev) => prev
      .map((c, k) => {
        if (k !== ci) return c;
        const member_indices = c.member_indices.filter((x) => x !== ri);
        const representative = c.representative === ri ? (member_indices[0] ?? -1) : c.representative;
        return { ...c, member_indices, representative };
      })
      .filter((c) => c.member_indices.length >= 2));
    toast("항목 제외");
  };

  const dissolveCluster = (ci: number) => {
    setClusters((prev) => prev.filter((_, k) => k !== ci));
    toast(`클러스터 ${ci + 1} 해지`);
  };

  const setRep = (ci: number, ri: number) =>
    setClusters((prev) => prev.map((c, k) => (k === ci ? { ...c, representative: ri } : c)));

  const apply = () => {
    if (!clusters.length) { toast("먼저 클러스터를 만들거나 Dedup을 실행하세요"); return; }
    const drop = new Set<number>();
    clusters.forEach((c) => c.member_indices.forEach((ri) => { if (ri !== c.representative) drop.add(ri); }));
    const kept = rows.filter((_, i) => !drop.has(i));
    setApplied(kept);
    setDockOpen(true);
    toast(`Apply 완료 — ${kept.length}행 (${drop.size}행 병합)`);
  };

  const left = (
    <PaneBox title="데이터 로드 / 편집" actions={<>
      <button className="btn" onClick={createCluster}>+ 선택으로 클러스터</button>
      <button className="btn" onClick={run}>Dedup</button>
    </>}>
      <div className="thresh-bar">
        <span className="th-title">중복 판정 임계치</span>
        <div className="thresh"><label>업체명 유사도</label>
          <input type="range" min={50} max={100} value={thName} onChange={(e) => setThName(+e.target.value)} />
          <span className="th-val">{(thName / 100).toFixed(2)}</span></div>
        <div className="thresh"><label>주소 Jaccard</label>
          <input type="range" min={10} max={100} value={thAddr} onChange={(e) => setThAddr(+e.target.value)} />
          <span className="th-val">{(thAddr / 100).toFixed(2)}</span></div>
        <div className="thresh"><label>좌표 거리(m)</label>
          <input type="range" min={10} max={1000} step={10} value={thCoord} onChange={(e) => setThCoord(+e.target.value)} />
          <span className="th-val">{thCoord}</span></div>
      </div>
      <p className="pane-note">저장된 표준화 테이블 (복수 선택 후 Load, 이어붙이기 지원)</p>
      <TableList tables={tables} selected={picked}
        onToggle={(n) => setPicked((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; })}
        onDelete={async (n) => { await api.deleteTable("standardized", n); toast(`"${n}" 삭제`); refresh(); }} />
      <div className="list-actions"><button className="btn sm" onClick={load}>Load</button></div>
      {rows.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="tbl-toolbar"><span className="count">{rows.length}행 · 행 선택 후 “+ 선택으로 클러스터” 또는 클러스터의 “+ 선택 추가”</span></div>
          <DataTable columns={DISPLAY_COLS} rows={rows} stdCols={["STD 업체명", "STD 주소"]}
            selectable selected={selected} onToggleRow={toggleRow} onToggleAll={toggleAll} />
        </div>
      )}
    </PaneBox>
  );

  const right = (
    <PaneBox title="중복 결과 (클러스터)" loading={loading} loadingMsg="중복 분석 중…" actions={<>
      <button className="btn" onClick={apply}>Apply</button>
      <button className="btn primary" onClick={() => {
        if (!applied.length) { toast("Apply 후 저장할 수 있습니다"); return; }
        setSaveOpen(true);
      }}>Save</button>
    </>}>
      {!ran ? (
        <div className="empty"><div className="big">⧉</div>좌측에서 데이터를 로드하고 Dedup을 누르거나,<br />
          <span style={{ fontSize: "11.5px" }}>행을 선택해 “+ 선택으로 클러스터”로 직접 만들 수 있습니다</span></div>
      ) : (!clusters.length && !suspects.length) ? (
        <div className="empty"><div className="big">✓</div>중복으로 판정된 그룹이 없습니다<br />
          <span style={{ fontSize: "11.5px" }}>좌측 행을 선택해 “+ 선택으로 클러스터”로 직접 만들 수 있습니다</span></div>
      ) : (
        <>
          <p className="pane-note">각 클러스터에서 <b>대표로 남길 Site</b>를 선택하세요. 🔗로 지도를 확인하고, 필요 시 항목을 제외하거나 클러스터를 해지할 수 있습니다. Apply를 누르면 대표 행만 남긴 테이블로 재구성됩니다.</p>
          {clusters.map((c, ci) => (
            <div className="clu" key={ci}>
              <div className="clu-head">
                <span className="clu-title">클러스터 {ci + 1} <span>· {c.member_indices.length}개 행 중복</span></span>
                <div className="clu-actions">
                  <button className="btn ghost sm" onClick={() => addSelectedToCluster(ci)}>+ 선택 추가</button>
                  <button className="btn ghost sm" onClick={() => dissolveCluster(ci)}>클러스터 해지</button>
                </div>
              </div>
              <div className="clu-body">
                {c.member_indices.map((ri) => {
                  const L = rowLabel(rows[ri]);
                  const urls = mapUrls(rows[ri]);
                  const isRep = c.representative === ri;
                  return (
                    <div className={`clu-row${isRep ? " is-rep" : ""}`} key={ri}>
                      <input type="radio" name={`rep-${ci}`} checked={isRep}
                        onChange={() => setRep(ci, ri)} />
                      <span className="cr-text" onClick={() => setRep(ci, ri)}>
                        <span className="cr-main">{L.name}</span><br />
                        <span className="cr-sub">{L.sub}</span>
                      </span>
                      {urls.map((u, k) => (
                        <a key={k} href={u} target="_blank" rel="noopener noreferrer"
                          className="ref-link" title={k === 0 ? "표준 주소로 위치 검증" : "원본 주소로 위치 검증"}>🔗</a>
                      ))}
                      {isRep && <span className="rep-badge">대표</span>}
                      <span className="row-del" title="클러스터에서 제외" onClick={() => removeMember(ci, ri)}>✕</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          {suspects.length > 0 && (
            <div className="suspect-box">
              <div className="sb-title">중복 의심 (자동 병합 제외 — 수동 확인 권장)</div>
              {suspects.map((s, k) => {
                const a = rowLabel(rows[s.pair[0]]), b = rowLabel(rows[s.pair[1]]);
                return <div key={k}>· {a.name} ↔ {b.name} <span style={{ color: "var(--text-sub)" }}>
                  (사유: {s.reason}{s.name_score != null ? ` · 업체명 ${s.name_score}` : ""})</span></div>;
              })}
            </div>
          )}
        </>
      )}
    </PaneBox>
  );

  return (
    <>
      <h1 className="page-title">Deduplication</h1>
      <p className="page-sub">표준화된 테이블 로드 → Dedup 또는 수동 클러스터 생성 → 대표 선택 → Apply → 저장</p>
      <TwoPane ratio={ratio} left={left} right={right} />
      <ResultDock show={dockOpen} title="중복 제거 결과" onClose={() => setDockOpen(false)}>
        <p className="pane-note">선택한 대표 행만 남기고 중복 행을 병합했습니다.</p>
        <div className="tbl-toolbar"><span className="count">{rows.length}행 → <b>{applied.length}행</b></span></div>
        <DataTable columns={DISPLAY_COLS} rows={applied} stdCols={["STD 업체명", "STD 주소"]} />
      </ResultDock>
      <SaveModal open={saveOpen} rowCount={applied.length} onClose={() => setSaveOpen(false)}
        onSave={async (name, overwrite) => {
          await api.saveTable("deduped", { name, columns: Object.keys(applied[0]), rows: applied, overwrite });
          toast(`"${name}" 저장 완료`);
        }} />
    </>
  );
}
