"use client";
import { useEffect, useRef } from "react";

// 하단에서 슬라이드로 펼쳐지는 결과 패널. show=true 시 스크롤로 이동.
export default function ResultDock({
  show, title, onClose, children,
}: {
  show: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (show) {
      const t = setTimeout(() => ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
      return () => clearTimeout(t);
    }
  }, [show]);

  return (
    <div className={`card result-dock${show ? " show" : ""}`} ref={ref}>
      <div className="rd-head">
        <span className="rd-title">{title}</span>
        <button className="btn ghost sm" onClick={onClose}>닫기</button>
      </div>
      <div className="rd-body">{children}</div>
    </div>
  );
}
