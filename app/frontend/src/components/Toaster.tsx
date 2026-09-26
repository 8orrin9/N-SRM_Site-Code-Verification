"use client";
import { useEffect, useRef, useState } from "react";
import { _subscribeToast } from "@/lib/toast";

// 앱 어디서든 toast(msg) 호출 시 하단 중앙에 잠깐 표시.
export default function Toaster() {
  const [msg, setMsg] = useState("");
  const [show, setShow] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return _subscribeToast((m) => {
      setMsg(m);
      setShow(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setShow(false), 2000);
    });
  }, []);

  return <div className={`toast${show ? " show" : ""}`}>{msg}</div>;
}
