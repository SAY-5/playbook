/* A measured number that counts up once on mount. Under prefers-reduced-motion it simply prints
   the value. The animated span is hidden from assistive technology; the section that owns the
   counters publishes the settled figures in a single polite live region instead. */
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../hooks/motion";

export interface CounterProps {
  value: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
}

export function Counter({ value, decimals = 0, suffix = "", duration = 1000 }: CounterProps) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(value);
  const frame = useRef(0);

  useEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      setShown(value * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };
    setShown(0);
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [value, duration, reduced]);

  return (
    <span aria-hidden="true">
      {shown.toFixed(decimals)}
      {suffix}
    </span>
  );
}
