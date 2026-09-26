"use client";
import type { TableMeta } from "@/lib/types";

// 저장된 테이블 목록(체크박스 멀티셀렉트). 선택 상태는 부모가 관리.
export default function TableList({
  tables, selected, onToggle, onDelete,
}: {
  tables: TableMeta[];
  selected: Set<string>;
  onToggle: (name: string) => void;
  onDelete?: (name: string) => void;
}) {
  if (!tables.length) {
    return <div className="empty" style={{ padding: "24px 8px" }}>저장된 테이블이 없습니다</div>;
  }
  return (
    <div className="tbl-list">
      {tables.map((t) => (
        <label key={t.name} className={`tbl-item${selected.has(t.name) ? " sel" : ""}`}>
          <input type="checkbox" checked={selected.has(t.name)} onChange={() => onToggle(t.name)} />
          <span className="ti-main">{t.name}</span>
          <span className="ti-sub">{t.row_count}행</span>
          {onDelete && (
            <span className="ti-del" title="삭제"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); onDelete(t.name); }}>✕</span>
          )}
        </label>
      ))}
    </div>
  );
}
