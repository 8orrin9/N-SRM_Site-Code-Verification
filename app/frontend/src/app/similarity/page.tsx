"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import TwoPane from "@/components/TwoPane";
import PaneBox from "@/components/PaneBox";
import DataTable from "@/components/DataTable";
import TableList from "@/components/TableList";
import ResultDock from "@/components/ResultDock";
import Drawer from "@/components/Drawer";
import ColumnMapModal from "@/components/ColumnMapModal";
import { api } from "@/lib/api";
import { toast } from "@/lib/toast";
import { avgClass, scoreBadge, rowLabel } from "@/lib/ui";
import { INPUT_COLUMNS, STD_COLUMNS, MAP_TARGETS, applyMapping } from "@/lib/columns";
import type { QueryResult, SimMatch, SiteRow, TableMeta } from "@/lib/types";

const blankRow = (): SiteRow => Object.fromEntries(INPUT_COLUMNS.map((c) => [c, ""]));
const REF_COLS = ["업체", "STD 업체명", "기업식별 코드", "Duns No.", "국가/지역", "주소(Eng)", "STD 주소"];
const STD_DISPLAY_COLS = [...INPUT_COLUMNS, ...STD_COLUMNS];

export default function SimilarityPage() {
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [refRows, setRefRows] = useState<SiteRow[]>([]);
  const [queryRows, setQueryRows] = useState<SiteRow[]>([blankRow()]);
  // 확인할 데이터 로드용 상태 (좌측 기준 테이블 로드와 분리)
  const [qTables, setQTables] = useState<TableMeta[]>([]);
  const [qPicked, setQPicked] = useState<Set<string>>(new Set());
  const [qFile, setQFile] = useState<File | null>(null);
  const [qPending, setQPending] = useState<{ columns: string[]; rows: SiteRow[] } | null>(null);
  const qFileInput = useRef<HTMLInputElement>(null);
  const [stdRows, setStdRows] = useState<SiteRow[]>([]);
  const [results, setResults] = useState<QueryResult[]>([]);
  const [dockOpen, setDockOpen] = useState(false);
  const [drawerQi, setDrawerQi] = useState<number | null>(null);
  const [stdLoading, setStdLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [flash, setFlash] = useState(false);
  const [matchTh, setMatchTh] = useState(60);

  const refresh = useCallback(async () => {
    try { setTables((await api.listTables("deduped")).tables); } catch { /* noop */ }
    try { setQTables((await api.listTables("upload")).tables); } catch { /* noop */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const load = async () => {
    if (!picked.size) { toast("기준 테이블을 선택하세요"); return; }
    const loaded: SiteRow[] = [];
    for (const name of picked) {
      try {
        const t = await api.loadTable("deduped", name);
        t.rows.forEach((r) => loaded.push({ ...r }));
      } catch { toast(`"${name}" 로드 실패`); }
    }
    setRefRows((prev) => [...prev, ...loaded]);
    setPicked(new Set());
    toast(`기준 테이블 로드 — ${refRows.length + loaded.length}행`);
  };

  const editCell = (i: number, col: string, value: string) =>
    setQueryRows((prev) => prev.map((r, k) => (k === i ? { ...r, [col]: value } : r)));
  const deleteRow = (i: number) => setQueryRows((prev) => prev.filter((_, k) => k !== i));

  // 확인할 데이터 편집 시, 이전 표준화·검색 결과는 무효화(재표준화 유도).
  const invalidate = () => { setStdRows([]); setResults([]); setDockOpen(false); };
  const onEditQuery = (i: number, col: string, value: string) => { editCell(i, col, value); invalidate(); };
  const onDeleteQuery = (i: number) => { deleteRow(i); invalidate(); };

  // 로드된 행을 확인할 데이터에 추가. 초기 빈 행 하나만 있으면 대체, 아니면 이어붙임.
  const appendQueryRows = (loaded: SiteRow[]) => {
    if (!loaded.length) return;
    setQueryRows((prev) => {
      const isInitialBlank = prev.length === 1 && INPUT_COLUMNS.every((c) => !(prev[0][c] || "").trim());
      return isInitialBlank ? loaded : [...prev, ...loaded];
    });
    invalidate();
  };

  // 저장된 upload 테이블에서 확인할 데이터 로드(파일 전송 없이 — 내부망 대응).
  const loadQuery = async () => {
    if (!qPicked.size) { toast("불러올 테이블을 선택하세요"); return; }
    const loaded: SiteRow[] = [];
    for (const name of qPicked) {
      try {
        const t = await api.loadTable("upload", name);
        t.rows.forEach((r) => loaded.push({ ...r }));
      } catch { toast(`"${name}" 로드 실패`); }
    }
    appendQueryRows(loaded);
    setQPicked(new Set());
    toast(`${loaded.length}행 로드`);
  };

  // 파일 업로드 → 파싱 → 표준 컬럼이면 바로 추가, 아니면 컬럼 매핑 모달.
  const confirmQueryFile = async () => {
    if (!qFile) { toast("업로드할 파일을 먼저 선택하세요"); return; }
    try {
      const res = await api.parseUpload(qFile);
      const srcCols = res.columns.filter((c) => c !== "No.");
      const needsMapping = srcCols.some((c) => !MAP_TARGETS.includes(c));
      if (needsMapping) {
        setQPending({ columns: srcCols, rows: res.rows });
        toast(`파싱 완료 — 컬럼 매핑이 필요합니다 (${res.rows.length}행)`);
      } else {
        appendQueryRows(res.rows);
        toast(`파일 파싱 완료 — ${res.rows.length}행 추가`);
      }
      setQFile(null);
      if (qFileInput.current) qFileInput.current.value = "";
    } catch (e) {
      toast((e as Error).message || "파싱 실패");
    }
  };

  const editStdCell = (i: number, col: string, value: string) =>
    setStdRows((prev) => prev.map((r, k) => (k === i ? { ...r, [col]: value } : r)));
  const deleteStdRow = (i: number) => setStdRows((prev) => prev.filter((_, k) => k !== i));
  const toggleStdStatus = (i: number) => setStdRows((prev) => prev.map((r, k) => {
    if (k !== i || r["표준화"] === "실패") return r;
    return { ...r, "표준화": r["표준화"] === "검증 완료" ? "확인 필요" : "검증 완료" };
  }));

  // 1단계: 확인할 데이터 표준화 → 표준화 결과 섹션 노출
  const standardizeQuery = async () => {
    const validQuery = queryRows.filter((r) => INPUT_COLUMNS.some((c) => (r[c] || "").trim()));
    if (!validQuery.length) { toast("확인할 데이터를 입력하세요"); return; }
    setStdLoading(true);
    try {
      const res = await api.standardize(validQuery);
      setStdRows(res.rows);
      setResults([]); setDockOpen(false);
      setFlash(true); setTimeout(() => setFlash(false), 1000);
      toast(`표준화 완료 — ${res.rows.length}행`);
    } catch (e) {
      toast((e as Error).message || "표준화 실패");
    } finally {
      setStdLoading(false);
    }
  };

  // 2단계: 표준화된 쿼리를 기준 테이블과 유사 검색
  const search = async () => {
    if (!refRows.length) { toast("기준 테이블을 먼저 로드하세요"); return; }
    if (!stdRows.length) { toast("먼저 확인할 데이터를 표준화하세요"); return; }
    setLoading(true);
    try {
      // 전체 후보를 받아 상세 랭킹에서 '더보기'로 점진 노출한다.
      const res = await api.similarity(stdRows, refRows, refRows.length);
      setResults(res.results);
      setDockOpen(true);
      toast(`유사 검색 완료 — 쿼리 ${res.results.length}건`);
    } catch (e) {
      toast((e as Error).message || "유사 검색 실패");
    } finally {
      setLoading(false);
    }
  };

  const left = (
    <PaneBox title="기준 테이블 (Reference)">
      <div className="thresh-bar">
        <span className="th-title">신규 채번 / 코드 매핑 기준 점수</span>
        <div className="thresh"><label>기준 점수</label>
          <input type="range" min={0} max={100} value={matchTh} onChange={(e) => setMatchTh(+e.target.value)} />
          <span className="th-val">{matchTh}</span></div>
      </div>
      <p className="pane-note">중복 제거하여 저장한 테이블 (복수 선택 후 Load, 이어붙이기)</p>
      <TableList tables={tables} selected={picked}
        onToggle={(n) => setPicked((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; })}
        onDelete={async (n) => { await api.deleteTable("deduped", n); toast(`"${n}" 삭제`); refresh(); }} />
      <div className="list-actions"><button className="btn sm" onClick={load}>Load</button></div>
      {refRows.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="tbl-toolbar"><span className="count">기준 {refRows.length}행</span></div>
          <DataTable columns={REF_COLS} rows={refRows} stdCols={["STD 업체명", "STD 주소"]} />
        </div>
      )}
    </PaneBox>
  );

  const right = (
    <PaneBox title="확인할 데이터 (Query)" loading={stdLoading || loading}
      loadingMsg={stdLoading ? "표준화 진행 중…" : "유사 검색 중…"} actions={<>
      <button className="btn ghost sm" onClick={() => { setQueryRows((p) => [...p, blankRow()]); }}>+ 행 추가</button>
      <button className="btn primary" onClick={standardizeQuery}>Standardization</button>
    </>}>
      <div className="drop" onClick={() => qFileInput.current?.click()}>
        <div className="big">⬆</div>
        <div><b>xlsx 파일 업로드</b> (클릭하여 선택)</div>
        <div style={{ marginTop: 4, fontSize: "11.5px" }}>확인할 데이터를 파일에서 불러옵니다</div>
        {qFile && <div style={{ marginTop: 8, color: "var(--blue)", fontWeight: 700 }}>{qFile.name}</div>}
        <input ref={qFileInput} type="file" accept=".xlsx,.xls" hidden
          onChange={(e) => { setQFile(e.target.files?.[0] || null); toast("파일 선택됨 — 파일 불러오기를 누르세요"); }} />
      </div>
      <div className="list-actions"><button className="btn sm" onClick={confirmQueryFile}>파일 불러오기</button></div>
      <div className="divider">또는 저장된 업로드 테이블 불러오기</div>
      <p className="pane-note">저장된 업로드 테이블 (복수 선택 후 Load, 이어붙이기)</p>
      <TableList tables={qTables} selected={qPicked}
        onToggle={(n) => setQPicked((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; })}
        onDelete={async (n) => { await api.deleteTable("upload", n); toast(`"${n}" 삭제`); refresh(); }} />
      <div className="list-actions"><button className="btn sm" onClick={loadQuery}>Load</button></div>
      <div className="divider">또는 수기 입력</div>
      {queryRows.length ? (
        <>
          <div className="tbl-toolbar"><span className="count">{queryRows.length}행 · 셀 클릭 편집</span></div>
          <DataTable columns={INPUT_COLUMNS} rows={queryRows} editable
            onEditCell={onEditQuery} onDeleteRow={onDeleteQuery} />
        </>
      ) : (
        <div className="empty"><div className="big">🔍</div>확인할 데이터를 입력하세요 (+ 행 추가) 후 Standardization</div>
      )}

      {stdRows.length > 0 && (
        <div style={{ marginTop: 18, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
          <div className="tbl-toolbar">
            <span className="ph-title" style={{ color: "var(--blue)", fontWeight: 700 }}>표준화 결과</span>
            <button className="btn primary sm" onClick={search} style={{ marginLeft: "auto" }}>Similarity Search</button>
          </div>
          <p className="pane-note">표준화된 값(STD 업체명·좌표·주소)으로 기준 테이블과 비교합니다. 셀을 클릭해 값을 수정한 뒤 Similarity Search를 누르세요.</p>
          <DataTable columns={STD_DISPLAY_COLS} rows={stdRows} stdCols={STD_COLUMNS} editable
            flash={flash} onToggleStatus={toggleStdStatus}
            onEditCell={editStdCell} onDeleteRow={deleteStdRow} />
        </div>
      )}
    </PaneBox>
  );

  const drawerRes = drawerQi != null ? results[drawerQi] : null;

  return (
    <>
      <h1 className="page-title">Similarity Search</h1>
      <p className="page-sub">기준 테이블 로드(좌) → 확인할 데이터 입력(우) → Standardization → 표준화 결과 확인 → Similarity Search → 하단 결과 · 상세보기</p>
      <TwoPane ratio={7} left={left} right={right} />

      <ResultDock show={dockOpen} title="유사 Site 검색 결과" onClose={() => setDockOpen(false)}>
        <p className="pane-note">각 쿼리 행에 최고 유사 Site를 매칭했습니다. 종합 점수가 기준 점수({matchTh}) 이상이면
          <b> 기존 코드 매핑</b>, 미만이면 <b>신규 채번 후보</b>로 표시합니다. 상세보기로 전체 후보 랭킹을 확인하세요.</p>
        {results.map((res, qi) => {
          const q = stdRows[qi];
          const top = res.matches[0];
          const matched = top && top.avg >= matchTh;
          const L = rowLabel(q || {});
          return (
            <div className="clu" key={qi} style={{ marginBottom: 12 }}>
              <div className="clu-head">
                <span className="clu-title">쿼리 {qi + 1} <span>· {L.name}</span></span>
                <button className="btn ghost sm" onClick={() => setDrawerQi(qi)}>상세보기</button>
              </div>
              <div className="clu-body">
                <div className="table-wrap"><table className="grid">
                  <thead><tr>
                    <th className="g-sub">구분</th><th className="g-sub">업체</th><th className="g-sub">기업식별 코드</th><th className="g-sub">주소</th>
                    <th className="g-rec">매칭 업체</th><th className="g-rec">업체명</th><th className="g-rec">코드</th><th className="g-rec">주소</th><th className="g-rec">종합</th><th className="g-rec">판정</th>
                  </tr></thead>
                  <tbody><tr>
                    <td className="c-sub">쿼리</td>
                    <td className="c-sub">{q?.["STD 업체명"] || q?.["업체"]}</td>
                    <td className="c-sub">{q?.["기업식별 코드"]}</td>
                    <td className="c-sub addr">{q?.["STD 주소"] || q?.["주소(Eng)"]}</td>
                    {matched ? (<>
                      <td className="c-rec">
                        {top.ref_row["STD 업체명"] || top.ref_row["업체"]}
                        {top.vetoed && <span className="veto-flag" title="코드/Duns 충돌로 감점됨">식별자 충돌</span>}
                      </td>
                      {([top.nameSim, top.corpSim, top.addrSim] as (number | null)[]).map((s, si) => {
                        const b = scoreBadge(s);
                        return <td key={si}><span className={`avg-badge ${b.cls}`}>{b.text}</span></td>;
                      })}
                      <td><span className={`avg-badge ${avgClass(top.avg)}`}>{top.avg}</span></td>
                      <td><span className="verdict-badge v-map" title={`기존 Site Code 매핑 대상 (${top.avg} ≥ ${matchTh})`}>코드 매핑</span></td>
                    </>) : (<>
                      <td className="c-rec" colSpan={4} style={{ color: "var(--warn)", fontWeight: 700 }}>매칭 없음</td>
                      <td><span className="avg-badge avg-lo">{top ? top.avg : 0}</span></td>
                      <td><span className="verdict-badge v-new" title={`기준 점수 미달 (${top ? top.avg : 0} < ${matchTh})`}>신규 채번</span></td>
                    </>)}
                  </tr></tbody>
                </table></div>
              </div>
            </div>
          );
        })}
      </ResultDock>

      <Drawer open={drawerQi != null}
        title={drawerRes ? <>쿼리 {(drawerQi ?? 0) + 1} 전체 후보 랭킹</> : ""}
        onClose={() => setDrawerQi(null)}>
        {drawerRes && <DetailRanking key={drawerQi} matches={drawerRes.matches} />}
      </Drawer>

      <ColumnMapModal open={qPending !== null} columns={qPending?.columns ?? []}
        sampleRow={qPending?.rows[0]}
        onClose={() => setQPending(null)}
        onApply={(mapping) => {
          if (!qPending) return;
          appendQueryRows(applyMapping(qPending.rows, mapping));
          setQPending(null);
          toast(`컬럼 매핑 적용 — ${qPending.rows.length}행 추가`);
        }} />
    </>
  );
}

const PAGE = 8;   // 더보기 단위

function DetailRanking({ matches }: { matches: SimMatch[] }) {
  const [shown, setShown] = useState(PAGE);
  const visible = matches.slice(0, shown);
  return (
    <>
      <p className="pane-note" style={{ marginTop: 10 }}>전체 후보 유사도 랭킹 (총 {matches.length}건 중 {visible.length}건 표시).
        점수는 게이트 판정을 반영합니다 — <b>—</b>는 정보 없음(SKIP), 0은 모순(DIFFERENT).
        코드/Duns 충돌 시 <b>식별자 충돌</b>로 감점됩니다.</p>
      <div className="table-wrap"><table className="grid">
        <thead><tr>
          <th>순위</th><th>업체명</th><th>코드</th><th>주소</th>
          <th className="std-col">업체명</th><th className="std-col">코드</th><th className="std-col">Duns</th>
          <th className="std-col">주소</th><th className="std-col">좌표</th><th className="std-col">종합</th>
        </tr></thead>
        <tbody>
          {visible.map((m, k) => {
            const subs: [string, number | null][] = [
              ["name", m.nameSim], ["code", m.corpSim], ["duns", m.dunsSim],
              ["addr", m.addrSim], ["coord", m.coordSim],
            ];
            return (
              <tr key={k}>
                <td>{k + 1}</td>
                <td>
                  {m.ref_row["STD 업체명"] || m.ref_row["업체"]}
                  {m.vetoed && <span className="veto-flag" title="코드/Duns 충돌로 감점됨">식별자 충돌</span>}
                </td>
                <td>{m.ref_row["기업식별 코드"]}</td>
                <td className="addr">{m.ref_row["주소(Eng)"]}</td>
                {subs.map(([key, s]) => {
                  const b = scoreBadge(s);
                  const v = m.gates?.[key];
                  return (
                    <td key={key}>
                      <span className={`avg-badge ${b.cls}`}>{b.text}</span>
                      {v && <span className={`gate-badge gate-${v}`} title={`게이트 판정: ${v}`}>{v}</span>}
                    </td>
                  );
                })}
                <td><span className={`avg-badge ${avgClass(m.avg)}`}>{m.avg}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table></div>
      {shown < matches.length && (
        <div className="list-actions" style={{ justifyContent: "center", marginTop: 12 }}>
          <button className="btn sm" onClick={() => setShown((n) => n + PAGE)}>
            더보기 (남은 {matches.length - shown}건)
          </button>
        </div>
      )}
    </>
  );
}
