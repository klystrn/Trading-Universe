/** Procedural sprite textures.
 *
 *  Generated on a canvas at runtime so the scene has no network dependency: a
 *  blocked CDN request must never be able to blank the universe (it did once).
 */

import * as THREE from "three";

const cache = new Map<string, THREE.Texture>();

function canvasTexture(key: string, size: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const cached = cache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  draw(ctx);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  cache.set(key, texture);
  return texture;
}

/** A star: hard bright centre, long soft falloff. */
export function softStarTexture(): THREE.Texture {
  return canvasTexture("star", 128, (ctx) => {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0.0, "rgba(255,255,255,1)");
    g.addColorStop(0.08, "rgba(255,255,255,0.95)");
    g.addColorStop(0.25, "rgba(255,255,255,0.35)");
    g.addColorStop(0.55, "rgba(255,255,255,0.07)");
    g.addColorStop(1.0, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  });
}

/** A galaxy nucleus: broad warm bloom with a tight core. */
export function coreTexture(): THREE.Texture {
  return canvasTexture("core", 256, (ctx) => {
    const g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    g.addColorStop(0.0, "rgba(255,248,232,1)");
    g.addColorStop(0.12, "rgba(255,236,200,0.85)");
    g.addColorStop(0.3, "rgba(255,220,180,0.32)");
    g.addColorStop(0.6, "rgba(230,200,190,0.08)");
    g.addColorStop(1.0, "rgba(200,180,200,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 256, 256);
  });
}

/** Nebulosity: a few overlapping soft blobs, irregular rather than round. */
export function nebulaTexture(seed = 1): THREE.Texture {
  return canvasTexture(`nebula-${seed}`, 256, (ctx) => {
    let s = seed * 9301 + 49297;
    const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < 7; i += 1) {
      const x = 88 + rnd() * 80;
      const y = 88 + rnd() * 80;
      const r = 36 + rnd() * 44;
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, `rgba(255,255,255,${0.18 + rnd() * 0.16})`);
      g.addColorStop(0.5, "rgba(255,255,255,0.05)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 256, 256);
    }
    // Soft circular mask: whatever the blobs did, the sprite fades to nothing
    // well inside its own edge.
    ctx.globalCompositeOperation = "destination-in";
    const mask = ctx.createRadialGradient(128, 128, 0, 128, 128, 124);
    mask.addColorStop(0.55, "rgba(0,0,0,1)");
    mask.addColorStop(1.0, "rgba(0,0,0,0)");
    ctx.fillStyle = mask;
    ctx.fillRect(0, 0, 256, 256);
  });
}
