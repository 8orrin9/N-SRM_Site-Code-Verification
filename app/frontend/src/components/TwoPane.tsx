"use client";
import { useEffect, useRef } from "react";

// 좌/우 2분할 레이아웃. ratio(좌측 flex-grow, 0~10)로 7:3 ↔ 3:7 애니메이션.
// 가운데 스플리터를 드래그하면 사용자가 직접 비율을 조절할 수 있다.
export default function TwoPane({
  ratio, left, right,
}: {
  ratio: number;
  left: React.ReactNode;
  right: React.ReactNode;
}) {
  const tpRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  // ratio prop 변경 시 애니메이션으로 flex-grow 전환.
  useEffect(() => {
    const tp = tpRef.current;
    if (!tp || !leftRef.current || !rightRef.current) return;
    tp.classList.remove("no-anim");
    leftRef.current.style.flexGrow = String(ratio);
    rightRef.current.style.flexGrow = String(10 - ratio);
  }, [ratio]);

  useEffect(() => {
    const tp = tpRef.current, l = leftRef.current, r = rightRef.current;
    if (!tp || !l || !r) return;
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const rect = tp.getBoundingClientRect();
      let ra = (e.clientX - rect.left) / rect.width;
      ra = Math.min(0.85, Math.max(0.15, ra));
      l.style.flexGrow = (ra * 10).toFixed(2);
      r.style.flexGrow = ((1 - ra) * 10).toFixed(2);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      tp.classList.remove("no-anim");
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      tp.querySelector(".splitter")?.classList.remove("active");
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const onSplitterDown = (e: React.MouseEvent) => {
    dragging.current = true;
    tpRef.current?.classList.add("no-anim");
    (e.currentTarget as HTMLElement).classList.add("active");
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  };

  return (
    <div className="twopane" ref={tpRef}>
      <div className="pane pane-left" ref={leftRef}>{left}</div>
      <div className="splitter" title="드래그하여 좌우 비율 조절" onMouseDown={onSplitterDown} />
      <div className="pane pane-right" ref={rightRef}>{right}</div>
    </div>
  );
}
