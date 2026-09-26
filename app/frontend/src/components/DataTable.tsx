"use client";
import { useEffect, useRef } from "react";
import type { SiteRow } from "@/lib/types";

const STATUS_CLASS: Record<string, string> = {
  "검증 완료": "s-verified",
  "확인 필요": "s-unverified",
  "실패": "s-failed",
};

// 편집 셀. contentEditable에 React가 매 렌더마다 children을 주입하면
// 편집 중 부모 리렌더(예: flash 타이머)로 입력값이 옛 값으로 되돌아간다.
// DOM 텍스트는 ref로 직접 관리하고, 외부 value가 실제로 바뀐 경우에만 동기화한다.
function EditableCell({
  value, className, onCommit,
}: {
  value: string;
  className?: string;
  onCommit: (v: string) => void;
}) {
  const ref = useRef<HTMLTableCellElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el && el.textContent !== value) el.textContent = value;
  }, [value]);
  return (
    <td
      ref={ref}
      className={className}
      contentEditable
      suppressContentEditableWarning
      onBlur={(e) => onCommit(e.currentTarget.textContent?.trim() || "")}
    />
  );
}

// 편집 가능한 데이터 그리드. 프로토타입 renderTable/bindTable을 React로 이식.
// - editable: 셀 인라인 편집(STD 컬럼 제외) + 행 삭제
// - selectable: 행 체크박스(전체 선택 헤더 포함)
// - stdCols: STD 강조 컬럼. "표준화"는 상태 배지, "참조 URL"은 링크로 렌더.
// - flash: STD 셀에 just-filled 플래시 애니메이션
export default function DataTable({
  columns, rows,
  editable = false, selectable = false, stdCols = [],
  selected, onToggleRow, onToggleAll,
  onEditCell, onDeleteRow, onToggleStatus, flash = false,
}: {
  columns: string[];
  rows: SiteRow[];
  editable?: boolean;
  selectable?: boolean;
  stdCols?: string[];
  selected?: Set<number>;
  onToggleRow?: (i: number) => void;
  onToggleAll?: (checked: boolean) => void;
  onEditCell?: (i: number, col: string, value: string) => void;
  onDeleteRow?: (i: number) => void;
  onToggleStatus?: (i: number) => void;
  flash?: boolean;
}) {
  const stdSet = new Set(stdCols);
  const allChecked = selectable && rows.length > 0 && selected != null && selected.size === rows.length;

  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            {selectable && (
              <th style={{ width: 34 }}>
                <input type="checkbox" className="row-chk" checked={allChecked}
                  onChange={(e) => onToggleAll?.(e.target.checked)} />
              </th>
            )}
            <th style={{ width: 44 }}>No.</th>
            {columns.map((c) => (
              <th key={c} className={stdSet.has(c) ? "std-col" : undefined}>{c}</th>
            ))}
            {editable && <th style={{ width: 36 }} />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const isSel = selected?.has(i) ?? false;
            return (
              <tr key={i} className={isSel ? "sel" : undefined}>
                {selectable && (
                  <td>
                    <input type="checkbox" className="row-chk" checked={isSel}
                      onChange={() => onToggleRow?.(i)} />
                  </td>
                )}
                <td>{i + 1}</td>
                {columns.map((c) => {
                  const isStd = stdSet.has(c);
                  const isAddr = c.indexOf("주소") >= 0;
                  if (c === "표준화") {
                    const st = row[c] || "확인 필요";
                    const cls = STATUS_CLASS[st] || "s-unverified";
                    return (
                      <td key={c} className={`std-cell${flash ? " just-filled" : ""}`}>
                        <span className={`status ${cls}`} onClick={() => onToggleStatus?.(i)}>{st}</span>
                      </td>
                    );
                  }
                  if (c === "참조 URL") {
                    // 표준/원본 주소가 다르면 " | "로 두 URL이 병존한다(표준 → 원본 순).
                    const urls = (row[c] || "").split(" | ").map((s) => s.trim()).filter(Boolean);
                    return (
                      <td key={c} className={`std-cell${flash ? " just-filled" : ""}`}>
                        {urls.length
                          ? urls.map((u, k) => (
                              <a key={k} href={u} target="_blank" rel="noopener noreferrer"
                                className="ref-link" title={k === 0 ? "표준 주소로 위치 검증" : "원본 주소로 위치 검증"}
                                style={{ marginRight: k < urls.length - 1 ? 8 : 0 }}>🔗</a>
                            ))
                          : "—"}
                      </td>
                    );
                  }
                  // 표준화·참조 URL은 위에서 특수 처리됨. 나머지는 STD 컬럼이라도 편집 허용.
                  const editableCell = editable;
                  const cls = [
                    isStd ? "std-cell" : "",
                    isStd && flash ? "just-filled" : "",
                    isAddr ? "addr" : "",
                    editableCell ? "editable" : "",
                  ].filter(Boolean).join(" ") || undefined;
                  if (editableCell) {
                    return (
                      <EditableCell key={c} value={row[c] ?? ""} className={cls}
                        onCommit={(v) => onEditCell?.(i, c, v)} />
                    );
                  }
                  return <td key={c} className={cls}>{row[c] ?? ""}</td>;
                })}
                {editable && (
                  <td>
                    <span className="row-del" title="행 삭제" onClick={() => onDeleteRow?.(i)}>✕</span>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
