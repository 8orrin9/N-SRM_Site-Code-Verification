"use client";
import { useEffect, useRef } from "react";

// 우측 슬라이드 오버 패널 + 배경 블러. 좌측 가장자리 드래그로 폭 조절.
export default function Drawer({
  open, title, onClose, children,
}: {
  open: boolean;
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const dr = drawerRef.current;
    if (!dr) return;
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const w = Math.min(window.innerWidth * 0.96, Math.max(480, window.innerWidth - e.clientX));
      dr.style.width = w + "px";
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      dr.classList.remove("dragging");
      dr.querySelector(".drawer-resizer")?.classList.remove("active");
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const onResizerDown = (e: React.MouseEvent) => {
    dragging.current = true;
    drawerRef.current?.classList.add("dragging");
    (e.currentTarget as HTMLElement).classList.add("active");
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  };

  return (
    <>
      <div className={`drawer-backdrop${open ? " show" : ""}`} onClick={onClose} />
      <aside className={`drawer${open ? " show" : ""}`} ref={drawerRef}>
        <div className="drawer-resizer" title="드래그하여 폭 조절" onMouseDown={onResizerDown} />
        <div className="drawer-head">
          <span className="drawer-title">{title}</span>
          <button className="modal-x" onClick={onClose}>&times;</button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}
