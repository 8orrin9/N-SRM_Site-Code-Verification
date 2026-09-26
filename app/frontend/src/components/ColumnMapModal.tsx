"use client";
import { useEffect, useState } from "react";
import { MAP_TARGETS, guessTarget } from "@/lib/columns";
import type { SiteRow } from "@/lib/types";

// 업로드 파싱 후 원본 컬럼 → 표준 입력 컬럼 매핑 UI.
// 각 원본 컬럼에 대해 표준 타겟(업체/주소(Eng)/위도 …) 또는 "사용 안 함"을 지정한다.
// 자동 추정(guessTarget)을 기본값으로 채우고, 사용자가 조정할 수 있다.
export default function ColumnMapModal({
  open, columns, sampleRow, onClose, onApply,
}: {
  open: boolean;
  columns: string[];
  sampleRow: SiteRow | undefined;
  onClose: () => void;
  onApply: (mapping: Record<string, string>) => void;
}) {
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [warn, setWarn] = useState("");

  useEffect(() => {
    if (open) {
      const init: Record<string, string> = {};
      columns.forEach((c) => { init[c] = guessTarget(c); });
      setMapping(init);
      setWarn("");
    }
  }, [open, columns]);

  if (!open) return null;

  const apply = () => {
    // 같은 타겟에 두 개 이상 원본이 매핑되면 충돌 → 차단.
    const used = new Map<string, string>();
    for (const [src, tgt] of Object.entries(mapping)) {
      if (!tgt) continue;
      if (used.has(tgt)) {
        setWarn(`"${tgt}" 컬럼에 "${used.get(tgt)}"와 "${src}"가 중복 매핑되었습니다.`);
        return;
      }
      used.set(tgt, src);
    }
    if (!used.has("업체") && !used.has("주소(Eng)")) {
      setWarn("표준화를 위해 최소한 '업체' 또는 '주소(Eng)' 중 하나는 매핑되어야 합니다.");
      return;
    }
    onApply(mapping);
  };

  return (
    <div className="modal-overlay show" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal modal-wide">
        <div className="modal-head">
          <span className="modal-title">컬럼 매핑</span>
          <button className="modal-x" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          <p className="pane-note">업로드한 파일의 컬럼을 표준 컬럼명으로 연결합니다. 자동 추정된 값을 확인하고 필요 시 바꾸세요.
            (표준화 로직은 <b>업체 · 주소(Eng) · 위도 · 경도 · 국가/지역</b> 등 표준 컬럼명을 사용합니다.)</p>
          <div className="table-wrap" style={{ maxHeight: "56vh" }}>
            <table className="grid">
              <thead>
                <tr>
                  <th style={{ minWidth: 160 }}>원본 컬럼</th>
                  <th style={{ minWidth: 220 }}>미리보기(첫 행)</th>
                  <th style={{ minWidth: 180 }}>→ 표준 컬럼</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((c) => (
                  <tr key={c}>
                    <td style={{ fontWeight: 700 }}>{c}</td>
                    <td className="addr" style={{ color: "var(--text-sub)" }}>{sampleRow?.[c] ?? ""}</td>
                    <td>
                      <select
                        value={mapping[c] ?? ""}
                        onChange={(e) => setMapping((m) => ({ ...m, [c]: e.target.value }))}
                        style={{ height: 28, fontFamily: "inherit", fontSize: "12px" }}
                      >
                        <option value="">— 사용 안 함 —</option>
                        {MAP_TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {warn && <div className="save-hint" style={{ color: "var(--danger)" }}>
            <span className="info-ic" style={{ background: "var(--danger)" }}>!</span><span>{warn}</span></div>}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" onClick={apply}>적용</button>
        </div>
      </div>
    </div>
  );
}
