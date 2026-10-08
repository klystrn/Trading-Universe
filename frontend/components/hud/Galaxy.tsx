"use client";

/** The market as one spiral galaxy, drawn behind the HUD.
 *
 *  The galaxy itself is a single pre-rendered photograph-style image
 *  (scripts/render_galaxy.py) that the canvas rotates in its own plane and
 *  squashes for inclination: one drawImage per frame, no WebGL. Each stock is
 *  a star placed on the same logarithmic spiral the image shows, one arm
 *  segment per sector. A star's brightness follows the stock's activity,
 *  its tint follows the day's move, and live setups twinkle.
 *
 *  The canvas also stands in for the old reactive core: rotation speed
 *  follows the market regime, the nucleus brightens while listening or
 *  speaking, and the whole disc dims when the kill switch is engaged.
 */

import { useEffect, useRef, useState } from "react";
import { useHudStore } from "@/stores/useHudStore";
import { useTradingStore } from "@/stores/useTradingStore";
import type { UniverseEntity, UniversePayload } from "@/lib/types";

/** Mirrors frontend/public/galaxy.json, written by the renderer. */
interface GalaxyMeta {
  arms: number;
  pitch_deg: number;
  arm_r0: number;
  arm_phase: number;
  arm_r_min: number;
  arm_r_max: number;
}

const FALLBACK_META: GalaxyMeta = {
  arms: 2, pitch_deg: 17, arm_r0: 0.07, arm_phase: 0, arm_r_min: 0.1, arm_r_max: 0.66,
};

/** Seconds per revolution by regime: a strong tape turns the disc faster. */
const PERIOD: Record<string, number> = {
  STRONG_BULL: 260, BULL: 320, RECOVERY: 360, NEUTRAL: 420,
  HIGH_VOLATILITY: 300, CORRECTION: 520, RISK_OFF: 640,
};

const INCLINATION = 0.52;     // cos(i): how flattened the disc looks
const POSITION_ANGLE = -0.38; // tilt of the major axis on screen, radians
const MAX_DPR = 1.5;          // a background does not need retina sharpness

interface StarPoint {
  id: string;
  x: number;          // disc plane, fraction of the galaxy radius
  y: number;
  size: number;
  alpha: number;
  tint: 0 | 1 | 2;    // neutral, cool (up), warm (down)
  twinkle: number;    // 0 = steady, 1 = live executable setup
  held: boolean;
  phase: number;
}

export interface HoveredStar {
  entity: UniverseEntity;
  sectorLabel: string;
  x: number;
  y: number;
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

/** Lay stocks along the arms: the two arms end to end form one long path,
 *  cut into one contiguous segment per sector. */
function placeStars(payload: UniversePayload, meta: GalaxyMeta): StarPoint[] {
  const k = 1 / Math.tan((meta.pitch_deg * Math.PI) / 180);
  const lnMin = Math.log(meta.arm_r_min);
  const lnMax = Math.log(meta.arm_r_max);
  const sectors = payload.sectors.map((s) => s.id);
  const bySector = new Map<string, UniverseEntity[]>();
  for (const e of payload.entities) {
    const list = bySector.get(e.sector) ?? [];
    list.push(e);
    bySector.set(e.sector, list);
  }
  const total = payload.entities.length || 1;
  const stars: StarPoint[] = [];
  let cursor = 0; // position along the combined path, 0..arms
  for (const sector of sectors) {
    const members = (bySector.get(sector) ?? []).sort((a, b) => a.id.localeCompare(b.id));
    const span = (members.length / total) * meta.arms;
    members.forEach((e, i) => {
      const along = cursor + span * ((i + 0.15 + 0.7 * hash(e.id)) / Math.max(members.length, 1));
      const arm = Math.min(meta.arms - 1, Math.floor(along));
      const u = along - arm;
      const lnR = lnMin + u * (lnMax - lnMin) + (hash(`${e.id}r`) - 0.5) * 0.22;
      const r = Math.exp(lnR);
      const theta = k * Math.log(r / meta.arm_r0) + meta.arm_phase + (arm * 2 * Math.PI) / meta.arms
        + (hash(`${e.id}t`) - 0.5) * 0.55;
      const intensity = Math.max(0, Math.min(1, e.intensity ?? 0.3));
      const change = e.price_change ?? 0;
      stars.push({
        id: e.id,
        x: r * Math.cos(theta),
        y: r * Math.sin(theta),
        size: 0.8 + 1.8 * intensity + (e.signal?.active ? 0.8 : 0),
        alpha: 0.18 + 0.5 * intensity,
        tint: Math.abs(change) < 0.004 ? 0 : change > 0 ? 1 : 2,
        twinkle: e.signal?.executable ? 1 : e.signal?.active ? 0.45 : 0,
        held: !!e.portfolio?.held,
        phase: hash(`${e.id}p`) * Math.PI * 2,
      });
    });
    cursor += span;
  }
  return stars;
}

/** Small seeded PRNG: a hash of sequential keys correlates and draws stars
 *  in straight lines, so the sky uses a real generator. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function glowSprite(rgb: [number, number, number]): HTMLCanvasElement {
  const size = 64;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const [r, gr, b] = rgb;
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.08, `rgba(${r},${gr},${b},0.95)`);
  grad.addColorStop(0.25, `rgba(${r},${gr},${b},0.28)`);
  grad.addColorStop(1, `rgba(${r},${gr},${b},0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return c;
}

/** The opaque sky: the HUD's dark radial ground plus a fixed field of faint
 *  stars. It must be opaque, because additive blending onto transparent
 *  pixels would paint the galaxy image's black square onto the page. */
function sky(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d")!;
  const ground = g.createRadialGradient(w * 0.5, h * 0.45, 0, w * 0.5, h * 0.45, Math.hypot(w, h) * 0.6);
  ground.addColorStop(0, "#0d1220");
  ground.addColorStop(1, "#04060b");
  g.fillStyle = ground;
  g.fillRect(0, 0, w, h);
  const rand = mulberry32(20261008);
  const count = Math.round((w * h) / 2600);
  for (let i = 0; i < count; i++) {
    const x = rand() * w;
    const y = rand() * h;
    const m = rand() ** 6;
    const warm = rand();
    const a = 0.12 + 0.6 * m;
    g.fillStyle = warm > 0.7 ? `rgba(255,228,200,${a})` : warm < 0.25 ? `rgba(205,220,255,${a})` : `rgba(240,240,245,${a})`;
    g.beginPath();
    g.arc(x, y, 0.35 + 1.1 * m, 0, Math.PI * 2);
    g.fill();
  }
  return c;
}

export function Galaxy({
  universe,
  onHover,
  onPick,
}: {
  universe: UniversePayload | null;
  onHover: (star: HoveredStar | null) => void;
  onPick: (ticker: string) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [meta, setMeta] = useState<GalaxyMeta>(FALLBACK_META);
  const starsRef = useRef<StarPoint[]>([]);
  const screenRef = useRef<Float32Array>(new Float32Array(0));
  const universeRef = useRef<UniversePayload | null>(null);
  const hoverRef = useRef<string | null>(null);
  const callbacks = useRef({ onHover, onPick });
  callbacks.current = { onHover, onPick };

  useEffect(() => {
    fetch("galaxy.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => m && setMeta({ ...FALLBACK_META, ...m }))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    universeRef.current = universe;
    starsRef.current = universe ? placeStars(universe, meta) : [];
    screenRef.current = new Float32Array(starsRef.current.length * 2);
  }, [universe, meta]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const image = new Image();
    image.decoding = "async";
    image.src = "galaxy.webp";

    const sprites = [
      glowSprite([235, 238, 245]),
      glowSprite([175, 205, 255]),
      glowSprite([255, 196, 150]),
    ];

    let w = 0, h = 0, dpr = 1;
    let field: HTMLCanvasElement | null = null;
    const resize = () => {
      dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      field = sky(canvas.width, canvas.height);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    let raf = 0;
    let last = performance.now();
    let angle = 0;
    let amp = 0;
    let dim = 1;

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const t = now / 1000;

      const { listening, speaking, busy } = useHudStore.getState();
      const { briefing, health, waking } = useTradingStore.getState();
      const regime = briefing?.market_regime ?? "NEUTRAL";
      const killed = health?.kill_switch_engaged ?? false;
      angle += (dt * 2 * Math.PI) / (PERIOD[regime] ?? 420);
      const target = speaking ? 1 : listening ? 0.7 : busy || waking ? 0.4 : 0;
      amp += (target - amp) * Math.min(1, dt * 4);
      dim += ((killed ? 0.45 : 1) - dim) * Math.min(1, dt * 2);

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      if (field) ctx.drawImage(field, 0, 0);

      // The disc: centre where the old core sat, sized to the viewport.
      const cx = (w * 0.5) * dpr;
      const cy = (h * 0.42) * dpr;
      const R = Math.min(w * 0.5, h * 1.1) * 0.82 * dpr;
      const cosA = Math.cos(angle), sinA = Math.sin(angle);
      const cosP = Math.cos(POSITION_ANGLE), sinP = Math.sin(POSITION_ANGLE);
      // Screen = T * Rot(PA) * Scale(1, inc) * Rot(angle) * disc
      const m00 = cosP * cosA - sinP * INCLINATION * sinA;
      const m01 = -cosP * sinA - sinP * INCLINATION * cosA;
      const m10 = sinP * cosA + cosP * INCLINATION * sinA;
      const m11 = -sinP * sinA + cosP * INCLINATION * cosA;

      ctx.globalCompositeOperation = "lighter";
      if (image.complete && image.naturalWidth) {
        ctx.globalAlpha = 0.92 * dim;
        ctx.setTransform(m00 * R, m10 * R, m01 * R, m11 * R, cx, cy);
        ctx.drawImage(image, -1, -1, 2, 2);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
      }

      // Nucleus: brightens while the assistant listens or speaks.
      const pulse = amp * (0.75 + 0.25 * Math.sin(t * (speaking ? 9 : 3)));
      if (pulse > 0.01) {
        const nr = R * 0.16;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, nr);
        g.addColorStop(0, `rgba(255,236,210,${0.55 * pulse})`);
        g.addColorStop(0.4, `rgba(255,220,180,${0.18 * pulse})`);
        g.addColorStop(1, "rgba(255,220,180,0)");
        ctx.globalAlpha = 1;
        ctx.fillStyle = g;
        ctx.fillRect(cx - nr, cy - nr, nr * 2, nr * 2);
      }

      // Stock stars.
      const stars = starsRef.current;
      const screen = screenRef.current;
      const hovered = hoverRef.current;
      for (let i = 0; i < stars.length; i++) {
        const s = stars[i];
        const sx = cx + (m00 * s.x + m01 * s.y) * R;
        const sy = cy + (m10 * s.x + m11 * s.y) * R;
        screen[i * 2] = sx / dpr;
        screen[i * 2 + 1] = sy / dpr;
        const tw = s.twinkle ? 1 + 0.35 * s.twinkle * Math.sin(t * 2.4 + s.phase) : 1;
        const size = s.size * tw * dpr * (s.id === hovered ? 2.4 : 1) * 3.4;
        ctx.globalAlpha = Math.min(1, (s.id === hovered ? 1 : s.alpha) * tw * dim);
        ctx.drawImage(sprites[s.tint], sx - size / 2, sy - size / 2, size, size);
        if (s.held) {
          // Held positions get faint diffraction spikes, like a foreground star.
          const len = size * 1.6;
          ctx.globalAlpha = 0.35 * dim;
          ctx.strokeStyle = "rgba(255,240,220,1)";
          ctx.lineWidth = 0.6 * dpr;
          ctx.beginPath();
          ctx.moveTo(sx - len, sy); ctx.lineTo(sx + len, sy);
          ctx.moveTo(sx, sy - len); ctx.lineTo(sx, sy + len);
          ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
    };
    raf = requestAnimationFrame(draw);

    const nearest = (ev: MouseEvent): number => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const screen = screenRef.current;
      let best = -1, bestD = 12 * 12;
      for (let i = 0; i < screen.length / 2; i++) {
        const dx = screen[i * 2] - mx, dy = screen[i * 2 + 1] - my;
        const d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    };
    const onMove = (ev: MouseEvent) => {
      const i = nearest(ev);
      const star = i >= 0 ? starsRef.current[i] : null;
      const id = star?.id ?? null;
      canvas.style.cursor = id ? "pointer" : "default";
      if (id === hoverRef.current) return;
      hoverRef.current = id;
      const payload = universeRef.current;
      const entity = id && payload ? payload.entities.find((e) => e.id === id) : undefined;
      if (!entity || !payload) { callbacks.current.onHover(null); return; }
      const sector = payload.sectors.find((s) => s.id === entity.sector);
      callbacks.current.onHover({
        entity,
        sectorLabel: sector?.label ?? entity.sector,
        x: screenRef.current[i * 2],
        y: screenRef.current[i * 2 + 1],
      });
    };
    const onLeave = () => { hoverRef.current = null; callbacks.current.onHover(null); };
    const onClick = (ev: MouseEvent) => {
      // Prefer the star whose card is showing: the disc keeps turning.
      if (hoverRef.current) { callbacks.current.onPick(hoverRef.current); return; }
      const i = nearest(ev);
      if (i >= 0) callbacks.current.onPick(starsRef.current[i].id);
    };
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("click", onClick);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("click", onClick);
    };
  }, []);

  return <canvas ref={ref} className="absolute inset-0 h-full w-full" aria-label="Market galaxy" />;
}
