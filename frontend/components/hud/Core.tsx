"use client";

/** The reactive core: concentric arcs on a 2D canvas.
 *
 *  Cheap by design - a few dozen arcs, no WebGL. It breathes with the market
 *  regime (calmer in neutral, more energetic in a strong bull, tighter and
 *  dimmer in risk-off), swells while listening, and ripples while speaking.
 */

import { useEffect, useRef } from "react";
import { useHudStore } from "@/stores/useHudStore";
import { useTradingStore } from "@/stores/useTradingStore";

const ENERGY: Record<string, number> = {
  STRONG_BULL: 1.0, BULL: 0.8, RECOVERY: 0.7, NEUTRAL: 0.55,
  HIGH_VOLATILITY: 0.9, CORRECTION: 0.4, RISK_OFF: 0.25,
};

export function Core({ size = 340 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    let raf = 0;
    let amp = 0;                       // eased activity level
    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const { listening, speaking, busy } = useHudStore.getState();
      const regime = useTradingStore.getState().briefing?.market_regime ?? "NEUTRAL";
      const killed = useTradingStore.getState().health?.kill_switch_engaged ?? false;
      const energy = killed ? 0.2 : (ENERGY[regime] ?? 0.55);
      const target = speaking ? 1 : listening ? 0.75 : busy ? 0.5 : 0;
      amp += (target - amp) * 0.08;

      const c = size / 2;
      ctx.clearRect(0, 0, size, size);

      // Soft centre glow.
      const glow = ctx.createRadialGradient(c, c, 0, c, c, size * 0.5);
      const base = killed ? "232,136,107" : "90,209,230";
      glow.addColorStop(0, `rgba(${base},${0.28 + 0.25 * amp})`);
      glow.addColorStop(0.35, `rgba(${base},${0.08 + 0.08 * amp})`);
      glow.addColorStop(1, `rgba(${base},0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);

      // Rings of broken arcs, each at its own speed and direction.
      const rings = 7;
      for (let r = 0; r < rings; r += 1) {
        const radius = size * (0.13 + r * 0.05);
        const dir = r % 2 === 0 ? 1 : -1;
        const speed = (0.12 + r * 0.05) * (0.6 + 0.8 * energy) * (1 + amp * 1.2);
        const segments = 3 + (r % 3);
        const gap = 0.35 + (r % 2) * 0.2;
        const alpha = (0.14 + 0.06 * (rings - r) / rings) * (0.7 + 0.6 * energy) + 0.3 * amp;
        ctx.lineWidth = r === 0 ? 2.2 : 1.1;
        ctx.strokeStyle = `rgba(${base},${Math.min(0.95, alpha)})`;
        ctx.lineCap = "round";
        for (let s = 0; s < segments; s += 1) {
          const a0 = dir * t * speed + (s / segments) * Math.PI * 2 + r * 0.7;
          const len = (Math.PI * 2) / segments - gap;
          // Speech ripples the radius slightly.
          const wobble = speaking ? Math.sin(t * 9 + r * 1.3 + s) * 3 * amp : 0;
          ctx.beginPath();
          ctx.arc(c, c, radius + wobble, a0, a0 + len);
          ctx.stroke();
        }
      }

      // Tick marks on the outer ring - the "instrument" feel.
      const outer = size * 0.47;
      ctx.strokeStyle = `rgba(${base},${0.22 + 0.3 * amp})`;
      ctx.lineWidth = 1;
      for (let i = 0; i < 60; i += 1) {
        const a = (i / 60) * Math.PI * 2 - t * 0.05;
        const len = i % 5 === 0 ? 7 : 3;
        ctx.beginPath();
        ctx.moveTo(c + Math.cos(a) * outer, c + Math.sin(a) * outer);
        ctx.lineTo(c + Math.cos(a) * (outer - len), c + Math.sin(a) * (outer - len));
        ctx.stroke();
      }

      // A heartbeat dot in the centre.
      const beat = 0.5 + 0.5 * Math.sin(t * (1.2 + energy * 1.6));
      ctx.fillStyle = `rgba(${base},${0.55 + 0.4 * beat})`;
      ctx.beginPath();
      ctx.arc(c, c, 3 + 2 * beat + 3 * amp, 0, Math.PI * 2);
      ctx.fill();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size }}
      className="pointer-events-none select-none"
      aria-hidden
    />
  );
}
