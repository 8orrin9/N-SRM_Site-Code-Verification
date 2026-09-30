"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import TwoPane from "@/components/TwoPane";
import PaneBox from "@/components/PaneBox";
import DataTable from "@/components/DataTable";
import SaveModal from "@/components/SaveModal";
import ColumnMapModal from "@/components/ColumnMapModal";
import TableList from "@/components/TableList";
import { api } from "@/lib/api";
import { toast } from "@/lib/toast";
import { INPUT_COLUMNS, MAP_TARGETS, applyMapping } from "@/lib/columns";
import type { SiteRow, TableMeta } from "@/lib/types";

const blankRow = (): SiteRow => Object.fromEntries(INPUT_COLUMNS.map((c) => [c, ""]));

export default function UploadPage() {
  const [rows, setRows] = useState<SiteRow[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [manual, setManual] = useState<SiteRow>(blankRow());
  const [ratio, setRatio] = useState(7);
  const [saveOpen, setSaveOpen] = useState(false);
  const [pending, setPending] = useState<{ columns: string[]; rows: SiteRow[] } | null>(null);
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const fileInput = useRef<HTMLInputElement>(null);

  const columns = rows.length ? Object.keys(rows[0]).filter((c) => c !== "No.") : INPUT_COLUMNS;

  const refresh = useCallback(async () => {
    try { setTables((await api.listTables("upload")).tables); } catch { /* noop */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // 저장된 upload 테이블을 파일 전송 없이 로드(내부망 파일 업로드 차단 대응).
  const load = async () => {
    if (!picked.size) { toast("불러올 테이블을 선택하세요"); return; }
    const loaded: SiteRow[] = [];
    for (const name of picked) {
      try {
        const t = await api.loadTable("upload", name);
        t.rows.forEach((r) => loaded.push({ ...r }));
      } catch { toast(`"${name}" 로드 실패`); }
    }
    setRows((prev) => [...prev, ...loaded]);
    setPicked(new Set());
    setRatio(3);
    toast(`${loaded.length}행 로드 (누적 ${rows.length + loaded.length}행)`);
  };

  // Confirm: 선택된 파일을 파싱해 우측 테이블을 채운다(파일 전용).
  const confirm = async () => {
    if (!file) { toast("업로드할 파일을 먼저 선택하세요"); return; }
    try {
      const res = await api.parseUpload(file);
      const srcCols = res.columns.filter((c) => c !== "No.");
      // 원본 컬럼이 전부 표준 컬럼명이면 매핑 불필요, 아니면 매핑 모달을 띄운다.
      const needsMapping = srcCols.some((c) => !MAP_TARGETS.includes(c));
      if (needsMapping) {
        setPending({ columns: srcCols, rows: res.rows });
        toast(`파싱 완료 — 컬럼 매핑이 필요합니다 (${res.rows.length}행)`);
      } else {
        setRows((prev) => [...prev, ...res.rows]);
        setRatio(3);
        toast(`파일 파싱 완료 — ${res.rows.length}행 추가`);
      }
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (e) {
      toast((e as Error).message || "파싱 실패");
    }
  };

  // 수기 입력 폼의 값을 한 행으로 추가(현재 테이블 컬럼 구조에 맞춤).
  const addManualRow = () => {
    const hasManual = INPUT_COLUMNS.some((c) => (manual[c] || "").trim());
    if (!hasManual) { toast("수기 항목을 입력하세요"); return; }
    const row: SiteRow = Object.fromEntries(columns.map((c) => [c, manual[c] ?? ""]));
    setRows((prev) => [...prev, row]);
    setManual(blankRow());
    setRatio(3);
    toast("수기 행 1건 추가");
  };

  const editCell = (i: number, col: string, value: string) =>
    setRows((prev) => prev.map((r, k) => (k === i ? { ...r, [col]: value } : r)));
  const deleteRow = (i: number) => setRows((prev) => prev.filter((_, k) => k !== i));
  const addBlank = () =>
    setRows((prev) => [...prev, Object.fromEntries(columns.map((c) => [c, ""]))]);

  const left = (
    <PaneBox title="입력 (파일 / 수기)" actions={<button className="btn primary" onClick={confirm}>Confirm</button>}>
      <div className="drop" onClick={() => fileInput.current?.click()}>
        <div className="big">⬆</div>
        <div><b>xlsx 파일 업로드</b> (클릭하여 선택)</div>
        <div style={{ marginTop: 4, fontSize: "11.5px" }}>컬럼명 기준으로 파싱됩니다</div>
        {file && <div style={{ marginTop: 8, color: "var(--blue)", fontWeight: 700 }}>{file.name}</div>}
        <input ref={fileInput} type="file" accept=".xlsx,.xls" hidden
          onChange={(e) => { setFile(e.target.files?.[0] || null); toast("파일 선택됨 — Confirm을 누르세요"); }} />
      </div>
      <div className="divider">또는 저장된 테이블 불러오기</div>
      <p className="pane-note">저장된 업로드 테이블 (복수 선택 후 Load, 이어붙이기)</p>
      <TableList tables={tables} selected={picked}
        onToggle={(n) => setPicked((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; })}
        onDelete={async (n) => { await api.deleteTable("upload", n); toast(`"${n}" 삭제`); refresh(); }} />
      <div className="list-actions"><button className="btn sm" onClick={load}>Load</button></div>
      <div className="divider">또는 수기 입력</div>
      <div className="manual-grid">
        {INPUT_COLUMNS.map((c) => (
          <div className="field" key={c}>
            <label>{c}</label>
            <input type="text" value={manual[c]}
              onChange={(e) => setManual((m) => ({ ...m, [c]: e.target.value }))} />
          </div>
        ))}
      </div>
      <div className="form-actions">
        <button className="btn ghost sm" onClick={addManualRow}>+ 이 행 추가</button>
      </div>
    </PaneBox>
  );

  const right = (
    <PaneBox title="정제된 테이블" actions={<button className="btn primary" onClick={() => {
      if (!rows.length) { toast("저장할 데이터가 없습니다"); return; }
      setSaveOpen(true);
    }}>Save</button>}>
      {rows.length ? (
        <>
          <div className="tbl-toolbar">
            <button className="btn ghost sm" onClick={addBlank}>+ 빈 행</button>
            <span className="count">{rows.length}행 · 셀 클릭 편집</span>
          </div>
          <DataTable columns={columns} rows={rows} editable
            onEditCell={editCell} onDeleteRow={deleteRow} />
        </>
      ) : (
        <div className="empty"><div className="big">▦</div>Confirm을 누르면 파싱된 테이블이 여기에 표시됩니다</div>
      )}
    </PaneBox>
  );

  return (
    <>
      <h1 className="page-title">Data Upload</h1>
      <p className="page-sub">파일 업로드 또는 수기 입력 → Confirm으로 파싱 → 우측 테이블에서 편집 → Save로 이름 지정 저장</p>
      <TwoPane ratio={ratio} left={left} right={right} />
      <SaveModal open={saveOpen} rowCount={rows.length} onClose={() => setSaveOpen(false)}
        onSave={async (name, overwrite) => {
          await api.saveTable("upload", { name, columns, rows, overwrite });
          toast(`"${name}" 저장 완료`);
          refresh();
        }} />
      <ColumnMapModal open={pending !== null} columns={pending?.columns ?? []}
        sampleRow={pending?.rows[0]}
        onClose={() => setPending(null)}
        onApply={(mapping) => {
          if (!pending) return;
          const mapped = applyMapping(pending.rows, mapping);
          setRows((prev) => [...prev, ...mapped]);
          setPending(null);
          setRatio(3);
          toast(`컬럼 매핑 적용 — ${mapped.length}행 추가`);
        }} />
    </>
  );
}
