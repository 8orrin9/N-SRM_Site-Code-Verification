"use client";

// 좌/우 패널 공통 박스. 헤더(제목 + 액션 버튼) + 본문 + 선택적 로딩 오버레이.
export default function PaneBox({
  title, actions, loading, loadingMsg, children,
}: {
  title: string;
  actions?: React.ReactNode;
  loading?: boolean;
  loadingMsg?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="pane-box">
      {loading != null && (
        <div className={`load-overlay${loading ? " show" : ""}`}>
          <div className="spinner" />
          <div className="load-msg">{loadingMsg || "처리 중…"}</div>
        </div>
      )}
      <div className="pane-head">
        <span className="ph-title">{title}</span>
        {actions && <div className="ph-actions">{actions}</div>}
      </div>
      <div className="pane-body">{children}</div>
    </div>
  );
}
