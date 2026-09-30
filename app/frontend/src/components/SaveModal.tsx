"use client";
import { useEffect, useState } from "react";
import { toast } from "@/lib/toast";

// 공용 저장 모달. 이름 입력 → Save(1차) → "확정" → Save(2차)로 최종 저장.
// onSave가 FileExistsError(409)를 던지면 덮어쓰기 옵션을 노출한다.
export default function SaveModal({
  open, rowCount, onClose, onSave,
}: {
  open: boolean;
  rowCount: number;
  onClose: () => void;
  onSave: (name: string, overwrite: boolean) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) { setName(""); setConfirmed(false); setOverwrite(false); setConflict(false); setBusy(false); }
  }, [open]);

  if (!open) return null;

  const doSave = async () => {
    const n = name.trim();
    if (!n) return;
    if (!confirmed && !conflict) { setConfirmed(true); return; }
    setBusy(true);
    try {
      await onSave(n, overwrite || conflict);
      onClose();
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 409) { setConflict(true); setConfirmed(false); }
      else { toast(err.message || "저장 실패 — 다시 시도해주세요"); }
      setBusy(false);
    }
  };

  const hint = conflict
    ? `"${name.trim()}" 은(는) 이미 존재합니다. 덮어쓰려면 Save를 누르세요.`
    : confirmed
      ? `"${name.trim()}" 으로 저장하려면 Save를 한 번 더 누르세요.`
      : `${rowCount}행 · 이름을 입력하고 Save를 누르세요.`;

  return (
    <div className="modal-overlay show" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <span className="modal-title">테이블 저장</span>
          <button className="modal-x" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>테이블 이름</label>
            <input type="text" value={name} autoFocus placeholder="예: 260926_1차_업로드"
              onChange={(e) => { setName(e.target.value); setConfirmed(false); setConflict(false); }}
              onKeyDown={(e) => { if (e.key === "Enter") doSave(); }} />
          </div>
          <div className="save-hint"><span className="info-ic">i</span><span>{hint}</span></div>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={busy} onClick={doSave}>
            {conflict ? "덮어쓰기" : confirmed ? "Save (확정)" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
