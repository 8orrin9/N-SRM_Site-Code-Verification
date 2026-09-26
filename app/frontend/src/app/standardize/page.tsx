"use client";
import { useCallback, useEffect, useState } from "react";
import TwoPane from "@/components/TwoPane";
import PaneBox from "@/components/PaneBox";
import DataTable from "@/components/DataTable";
import SaveModal from "@/components/SaveModal";
import TableList from "@/components/TableList";
import { api } from "@/lib/api";
import { toast } from "@/lib/toast";
import { INPUT_COLUMNS, STD_COLUMNS } from "@/lib/columns";
import type { SiteRow, TableMeta } from "@/lib/types";

const blankRow = (): SiteRow => Object.fromEntries(INPUT_COLUMNS.map((c) => [c, ""]));
const DISPLAY_COLS = [...INPUT_COLUMNS, ...STD_COLUMNS];

export default function StandardizePage() {
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [leftRows, setLeftRows] = useState<SiteRow[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<SiteRow[]>([]);
  const [ratio, setRatio] = useState(7);
  const [loading, setLoading] = useState(false);
  const [flash, setFlash] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);

  const refresh = useCallback(async () => {
    try { setTables((await api.listTables("upload")).tables); } catch { /* noop */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const load = async () => {
    if (!picked.size) { toast("불러올 테이블을 선택하세요"); return; }
    const loaded: SiteRow[] = [];
    for (const name of picked) {
      try {
        const t = await api.loadTable("upload", name);
        t.rows.forEach((r) => loaded.push({ ...r }));
      } catch { toast(`"${name}" 로드 실패`); }
    }
    setLeftRows((prev) => [...prev, ...loaded]);
    setPicked(new Set());
    toast(`${loaded.length}행 로드 (누적 ${leftRows.length + loaded.length}행)`);
  };

  const editCell = (i: number, col: string, value: string) =>
    setLeftRows((prev) => prev.map((r, k) => (k === i ? { ...r, [col]: value } : r)));
  const deleteRow = (i: number) => setLeftRows((prev) => prev.filter((_, k) => k !== i));
  const toggleRow = (i: number) => setSelected((s) => {
    const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n;
  });
  const toggleAll = (checked: boolean) =>
    setSelected(checked ? new Set(leftRows.map((_, i) => i)) : new Set());

  const run = async () => {
    if (!leftRows.length) { toast("먼저 데이터를 로드하세요"); return; }
    const targets = selected.size ? [...selected].sort((a, b) => a - b).map((i) => leftRows[i]) : leftRows;
    setLoading(true);
    try {
      const res = await api.standardize(targets);
      setResult(res.rows);
      setRatio(3);
      setFlash(true);
      setTimeout(() => setFlash(false), 1000);
      toast(`표준화 완료 — ${res.rows.length}행 (${selected.size ? "선택" : "전체"})`);
    } catch (e) {
      toast((e as Error).message || "표준화 실패");
    } finally {
      setLoading(false);
    }
  };

  const toggleStatus = (i: number) => setResult((prev) => prev.map((r, k) => {
    if (k !== i || r["표준화"] === "실패") return r;
    return { ...r, "표준화": r["표준화"] === "검증 완료" ? "확인 필요" : "검증 완료" };
  }));

  const editResultCell = (i: number, col: string, value: string) =>
    setResult((prev) => prev.map((r, k) => (k === i ? { ...r, [col]: value } : r)));
  const deleteResultRow = (i: number) => setResult((prev) => prev.filter((_, k) => k !== i));

  const reset = () => {
    setResult([]); setRatio(7); toast("초기화 완료");
  };

  const left = (
    <PaneBox title="데이터 로드 / 편집" actions={<>
      <button className="btn" onClick={run}>Standardization</button>
      <button className="btn ghost" onClick={reset}>초기화</button>
    </>}>
      <p className="pane-note">저장된 업로드 테이블 (복수 선택 후 Load, 다시 선택 후 Load 시 이어붙임)</p>
      <TableList tables={tables} selected={picked}
        onToggle={(n) => setPicked((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; })}
        onDelete={async (n) => { await api.deleteTable("upload", n); toast(`"${n}" 삭제`); refresh(); }} />
      <div className="list-actions">
        <button className="btn sm" onClick={load}>Load</button>
        <button className="btn ghost sm" onClick={() => { setLeftRows((p) => [...p, blankRow()]); toast("빈 행 추가"); }}>+ 수기 입력</button>
      </div>
      {leftRows.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="tbl-toolbar"><span className="count">{leftRows.length}행 · 체크 없으면 전체 표준화</span></div>
          <DataTable columns={INPUT_COLUMNS} rows={leftRows} editable selectable
            selected={selected} onToggleRow={toggleRow} onToggleAll={toggleAll}
            onEditCell={editCell} onDeleteRow={deleteRow} />
        </div>
      )}
    </PaneBox>
  );

  const right = (
    <PaneBox title="표준화 결과" loading={loading} loadingMsg="표준화 진행 중…"
      actions={<button className="btn primary" onClick={() => {
        if (!result.length) { toast("저장할 표준화 결과가 없습니다"); return; }
        setSaveOpen(true);
      }}>Save</button>}>
      {result.length ? (
        <>
          <p className="pane-note">참조 URL의 🔗 아이콘으로 위치를 직접 검증한 뒤 상태 배지를 클릭해 <b>확인 필요 → 검증 완료</b>로 바꾸세요. 🔗가 2개면 표준 주소·원본 주소 각각의 지도입니다. 셀을 클릭하면 표준화 결과 값도 직접 수정할 수 있습니다.</p>
          <div className="tbl-toolbar"><span className="count">{result.length}행 · 셀 클릭 편집 · 상태 배지 클릭 시 확인 필요 ↔ 검증 완료</span></div>
          <DataTable columns={DISPLAY_COLS} rows={result} stdCols={STD_COLUMNS} editable
            flash={flash} onToggleStatus={toggleStatus}
            onEditCell={editResultCell} onDeleteRow={deleteResultRow} />
        </>
      ) : (
        <div className="empty"><div className="big">✦</div>좌측에서 데이터를 로드하고 Standardization을 누르세요<br />
          <span style={{ fontSize: "11.5px" }}>행 선택 없으면 전체, 선택 시 해당 행만 표준화</span></div>
      )}
    </PaneBox>
  );

  return (
    <>
      <h1 className="page-title">Standardization</h1>
      <p className="page-sub">저장한 테이블 로드(복수 선택·이어붙이기) → 표준화 → 행별 상태 확정 → Save</p>
      <TwoPane ratio={ratio} left={left} right={right} />
      <SaveModal open={saveOpen} rowCount={result.length} onClose={() => setSaveOpen(false)}
        onSave={async (name, overwrite) => {
          await api.saveTable("standardized", { name, columns: Object.keys(result[0]), rows: result, overwrite });
          toast(`"${name}" 저장 완료`);
        }} />
    </>
  );
}
