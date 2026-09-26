// 전역 toast 싱글턴. <Toaster/>가 구독해 렌더한다.
type Listener = (msg: string) => void;
let listener: Listener | null = null;

export function toast(msg: string) {
  listener?.(msg);
}

export function _subscribeToast(fn: Listener) {
  listener = fn;
  return () => { if (listener === fn) listener = null; };
}
