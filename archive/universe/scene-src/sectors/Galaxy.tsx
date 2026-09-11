"use client";

/** A sector rendered as a spiral galaxy.
 *
 *  Thousands of additive point sprites on logarithmic arms with a warm
 *  nucleus, tinted toward the sector's hue so galaxies stay distinguishable at
 *  a glance. The sector's relative strength drives the nucleus: leading sectors
 *  burn brighter and warmer, lagging ones cooler and dimmer (spec 58).
 *
 *  Subsectors are constellations inside the galaxy: their member stars are
 *  joined by faint lines and named at their centroid (spec 45).
 */

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { createGlowPointsMaterial } from "@/universe/render/GlowPointsMaterial";
import { coreTexture, nebulaTexture, softStarTexture } from "@/universe/render/textures";
import type { UniverseEntity, UniverseSector, UniverseSubsector } from "@/lib/types";

const GALAXY_RADIUS = 100;
const PARTICLES = 14000;

function seeded(seed: number) {
  let s = seed * 16807 % 2147483647 || 1;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function gauss(rnd: () => number) {
  // Box-Muller
  const u = Math.max(1e-9, rnd());
  const v = rnd();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

interface GalaxyBuffers {
  positions: Float32Array;
  colors: Float32Array;
  sizes: Float32Array;
  pulses: Float32Array;
  dust: { positions: Float32Array; colors: Float32Array; sizes: Float32Array; pulses: Float32Array };
  arms: number;
  tilt: [number, number, number];
}

const DUST = 3200;

function buildGalaxy(sector: UniverseSector, index: number): GalaxyBuffers {
  const rnd = seeded(index * 7919 + 13);
  const arms = index % 3 === 0 ? 3 : 2;
  const turns = 1.15 + rnd() * 0.55;
  const positions = new Float32Array(PARTICLES * 3);
  const colors = new Float32Array(PARTICLES * 3);
  const sizes = new Float32Array(PARTICLES);
  const pulses = new Float32Array(PARTICLES);

  const hue = new THREE.Color().setHSL(sector.hue / 360, 0.55, 0.6);
  const core = new THREE.Color("#ffe9c9");
  const arm = new THREE.Color("#a9c2ff");
  const pink = new THREE.Color("#e7a9c0");
  const c = new THREE.Color();

  for (let i = 0; i < PARTICLES; i += 1) {
    // Radial distribution: dense core, thinning arms.
    const t = Math.pow(rnd(), 0.62);
    const r = t * GALAXY_RADIUS;
    const armIndex = i % arms;
    const spread = 0.22 * (1 - t) + 0.07;                      // arms tighten outward
    const angle =
      (r / GALAXY_RADIUS) * turns * Math.PI * 2 +
      armIndex * ((Math.PI * 2) / arms) +
      gauss(rnd) * spread;
    const thickness = 4.0 * (1 - t * 0.7) + 0.5;
    const x = Math.cos(angle) * r + gauss(rnd) * (1.0 + 2.6 * (1 - t));
    const z = Math.sin(angle) * r + gauss(rnd) * (1.0 + 2.6 * (1 - t));
    const y = gauss(rnd) * thickness;
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;

    // Colour: warm nucleus, blue-white arms, a little pink dust, all leaning
    // toward the sector hue.
    const dustiness = rnd();
    if (t < 0.18) c.copy(core).lerp(hue, 0.15);
    else if (dustiness > 0.86) c.copy(pink).lerp(hue, 0.35);
    else c.copy(arm).lerp(hue, 0.4);
    const brightness = t < 0.18 ? 1.15 : 0.8 + rnd() * 0.5;
    colors[i * 3] = c.r * brightness;
    colors[i * 3 + 1] = c.g * brightness;
    colors[i * 3 + 2] = c.b * brightness;

    sizes[i] = t < 0.18 ? 1.4 + rnd() * 1.8 : 0.7 + rnd() * 1.5;
    pulses[i] = 0;
  }

  // Dust lanes: dark particles trailing the inside edge of each arm, in the
  // plane, so the arm reads as lit gas with an unlit lane behind it.
  const dust = {
    positions: new Float32Array(DUST * 3),
    colors: new Float32Array(DUST * 3),
    sizes: new Float32Array(DUST),
    pulses: new Float32Array(DUST),
  };
  const dustColor = new THREE.Color("#14090a");
  for (let i = 0; i < DUST; i += 1) {
    const t = 0.16 + Math.pow(rnd(), 0.8) * 0.8;
    const r = t * GALAXY_RADIUS;
    const armIndex = i % arms;
    const angle =
      (r / GALAXY_RADIUS) * turns * Math.PI * 2 +
      armIndex * ((Math.PI * 2) / arms) -
      0.32 + gauss(rnd) * 0.06;                                 // trails the arm
    dust.positions[i * 3] = Math.cos(angle) * r + gauss(rnd) * 1.4;
    dust.positions[i * 3 + 1] = gauss(rnd) * 0.9;
    dust.positions[i * 3 + 2] = Math.sin(angle) * r + gauss(rnd) * 1.4;
    dust.colors[i * 3] = dustColor.r;
    dust.colors[i * 3 + 1] = dustColor.g;
    dust.colors[i * 3 + 2] = dustColor.b;
    dust.sizes[i] = 2.2 + rnd() * 3.4;
  }

  return {
    positions, colors, sizes, pulses, dust, arms,
    // Inclined three-quarter views, varied per galaxy so no two look alike.
    tilt: [-0.55 - rnd() * 0.5, rnd() * Math.PI * 2, (rnd() - 0.5) * 0.5],
  };
}

const LABEL_DISTANCE = 1700;

export function Galaxy({ sector, index }: { sector: UniverseSector; index: number }) {
  const { camera, gl } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const spinRef = useRef<THREE.Group>(null);
  const materialRef = useRef<THREE.ShaderMaterial | null>(null);
  const [near, setNear] = useState(true);

  const hovered = useUniverseStore((s) => s.hovered);
  const selected = useUniverseStore((s) => s.selected);
  const filter = useUniverseStore((s) => s.filter);
  const showLabels = useUniverseStore((s) => s.showLabels);
  const setHovered = useUniverseStore((s) => s.setHovered);
  const focusOn = useUniverseStore((s) => s.focusOn);

  const buffers = useMemo(() => buildGalaxy(sector, index), [sector.hue, index]); // eslint-disable-line react-hooks/exhaustive-deps
  const position = useMemo(() => new THREE.Vector3(...sector.position), [sector.position]);

  const material = useMemo(() => {
    const m = createGlowPointsMaterial(softStarTexture(), {
      sizeScale: 1000, minSize: 1.6, maxSize: 30, opacity: 1.0,
    });
    materialRef.current = m;
    return m;
  }, []);
  const dustMaterial = useMemo(
    () => createGlowPointsMaterial(softStarTexture(), {
      sizeScale: 1000, minSize: 2.0, maxSize: 60, opacity: 0.62, blending: THREE.NormalBlending,
    }),
    [],
  );

  // Nucleus brightness follows relative strength: leaders glow, laggards fade.
  const rs = Math.max(-1, Math.min(1, sector.relative_strength * 30));
  const isActive = hovered === sector.id || selected === sector.id;
  const emphasised = filter === "SECTORS" || filter === "MARKET" || isActive;
  const coreScale = 26 + rs * 6 + (isActive ? 6 : 0);
  const coreColor = useMemo(
    () => new THREE.Color().setHSL(0.09 + 0.02 * rs, 0.55 - 0.25 * rs, 0.75 + 0.1 * rs),
    [rs],
  );
  const nebulaColor = useMemo(
    () => new THREE.Color().setHSL(sector.hue / 360, 0.6, 0.55),
    [sector.hue],
  );

  useFrame((state, delta) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value = state.clock.elapsedTime;
      materialRef.current.uniforms.uPixelRatio.value = gl.getPixelRatio();
      materialRef.current.uniforms.uOpacity.value = emphasised ? 1.0 : 0.45;
    }
    dustMaterial.uniforms.uPixelRatio.value = gl.getPixelRatio();
    if (spinRef.current) {
      // Slow rotation about the galaxy's own axis: alive, never a screensaver.
      spinRef.current.rotation.y += delta * 0.012 * (hovered === sector.id ? 0.15 : 1);
    }
    const d = camera.position.distanceTo(position);
    const shouldShow = d < LABEL_DISTANCE;
    if (shouldShow !== near) setNear(shouldShow);
  });

  const perf = sector.performance;
  const perfText = `${perf >= 0 ? "+" : ""}${(perf * 100).toFixed(2)}%`;

  return (
    <group ref={groupRef} position={position}>
      <group rotation={buffers.tilt}>
        <group ref={spinRef}>
          <points frustumCulled={false} material={material} renderOrder={1}>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
              <bufferAttribute attach="attributes-aColor" args={[buffers.colors, 3]} />
              <bufferAttribute attach="attributes-aSize" args={[buffers.sizes, 1]} />
              <bufferAttribute attach="attributes-aPulse" args={[buffers.pulses, 1]} />
            </bufferGeometry>
          </points>

          {/* Dust lanes draw after the arms (to darken them) and before the
              stocks (renderOrder 5), which must never be dimmed by dust. */}
          <points frustumCulled={false} material={dustMaterial} renderOrder={2}>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[buffers.dust.positions, 3]} />
              <bufferAttribute attach="attributes-aColor" args={[buffers.dust.colors, 3]} />
              <bufferAttribute attach="attributes-aSize" args={[buffers.dust.sizes, 1]} />
              <bufferAttribute attach="attributes-aPulse" args={[buffers.dust.pulses, 1]} />
            </bufferGeometry>
          </points>

          <mesh rotation={[-Math.PI / 2, 0, 0]} renderOrder={0}>
            <planeGeometry args={[GALAXY_RADIUS * 2.3, GALAXY_RADIUS * 2.3]} />
            <meshBasicMaterial
              map={coreTexture()}
              color={nebulaColor}
              transparent
              opacity={emphasised ? 0.34 : 0.16}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
              toneMapped={false}
              side={THREE.DoubleSide}
            />
          </mesh>

          {/* Nebulosity: three tinted clouds laid in the disc. */}
          {[0, 1, 2].map((n) => {
            const r = seeded(index * 31 + n * 7);
            const a = r() * Math.PI * 2;
            const dist = 22 + r() * 40;
            return (
              <sprite
                key={n}
                position={[Math.cos(a) * dist, 0, Math.sin(a) * dist]}
                scale={[60 + r() * 30, 48 + r() * 24, 1]}
              >
                <spriteMaterial
                  map={nebulaTexture(n + 1)}
                  color={nebulaColor}
                  transparent
                  opacity={(emphasised ? 0.18 : 0.08) * (0.8 + 0.4 * rs)}
                  depthWrite={false}
                  blending={THREE.AdditiveBlending}
                  toneMapped={false}
                />
              </sprite>
            );
          })}
        </group>
      </group>

      {/* Nucleus, camera-facing. */}
      <sprite scale={[coreScale, coreScale, 1]} renderOrder={3}>
        <spriteMaterial
          map={coreTexture()}
          color={coreColor}
          transparent
          opacity={emphasised ? 0.95 : 0.55}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
      </sprite>

      {/* Invisible pick target for hover / click. */}
      <mesh
        userData={{ pick: "sector", id: sector.id }}
        onPointerOver={(e) => { if (document.pointerLockElement) return; e.stopPropagation(); setHovered(sector.id); }}
        onPointerOut={() => { if (!document.pointerLockElement) setHovered(null); }}
        onClick={(e) => { if (document.pointerLockElement) return; e.stopPropagation(); focusOn(sector.id); }}
      >
        <sphereGeometry args={[22, 12, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {showLabels && (near || isActive) && (
        <Html position={[0, GALAXY_RADIUS * 0.62, 0]} center zIndexRange={[10, 0]}
              style={{ pointerEvents: "none", userSelect: "none" }}>
          <div className="flex flex-col items-center whitespace-nowrap">
            <span className="font-mono uppercase tracking-[0.3em]"
                  style={{ fontSize: isActive ? 14 : 12, color: isActive ? "#f2f5fb" : "#c9d2e3",
                           textShadow: "0 0 10px #000, 0 0 3px #000" }}>
              {sector.label}
            </span>
            <span className="mt-0.5 font-mono tracking-[0.1em]"
                  style={{ fontSize: 12, color: perf >= 0 ? "#67e0b3" : "#f09a7c",
                           textShadow: "0 0 8px #000" }}>
              {perfText}
            </span>
            {isActive && (
              <span className="mt-0.5 font-mono text-[10px] tracking-[0.14em]"
                    style={{ color: "#8fd8e8", textShadow: "0 0 8px #000" }}>
                {sector.rs_label} · {sector.signal_count} signal{sector.signal_count === 1 ? "" : "s"}
              </span>
            )}
          </div>
        </Html>
      )}
    </group>
  );
}

/** Subsector constellations: faint lines between a subsector's stars and a
 *  name at its centroid, shown when the camera is reasonably close. */
export function Constellations() {
  const { camera } = useThree();
  const entities = useUniverseStore((s) => s.entities);
  const subsectors = useUniverseStore((s) => s.subsectors);
  const showLabels = useUniverseStore((s) => s.showLabels);
  const filter = useUniverseStore((s) => s.filter);
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const sectors = useUniverseStore((s) => s.sectors);
  const lineRef = useRef<THREE.LineSegments>(null);

  const { geometry, centroids } = useMemo(() => {
    const bySub = new Map<string, UniverseEntity[]>();
    for (const e of entities) {
      const key = `${e.sector}:${e.subsector}`;
      (bySub.get(key) ?? bySub.set(key, []).get(key)!).push(e);
    }
    const verts: number[] = [];
    const centroids: { sub: UniverseSubsector; centre: THREE.Vector3 }[] = [];
    for (const sub of subsectors) {
      const members = bySub.get(sub.id) ?? [];
      if (members.length === 0) continue;
      const centre = new THREE.Vector3();
      members.forEach((m) => centre.add(new THREE.Vector3(...m.position)));
      centre.divideScalar(members.length);
      centroids.push({ sub, centre });
      // Greedy nearest-neighbour chain: reads as a drawn constellation rather
      // than a hairball.
      const remaining = [...members];
      let current = remaining.shift()!;
      while (remaining.length) {
        let best = 0; let bestD = Infinity;
        for (let i = 0; i < remaining.length; i += 1) {
          const d = dist2(current.position, remaining[i].position);
          if (d < bestD) { bestD = d; best = i; }
        }
        const next = remaining.splice(best, 1)[0];
        if (bestD < 26 * 26) verts.push(...current.position, ...next.position);
        current = next;
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    return { geometry, centroids };
  }, [entities, subsectors]);

  useFrame(() => {
    // Lines are a close-range detail: invisible from the overview, drawn in
    // softly as a galaxy is approached.
    let nearest = Infinity;
    for (const s of sectors) {
      const d = camera.position.distanceTo(new THREE.Vector3(...s.position));
      if (d < nearest) nearest = d;
    }
    const k = Math.max(0, Math.min(1, (700 - nearest) / 400));
    const mat = lineRef.current?.material as THREE.LineBasicMaterial | undefined;
    if (mat) mat.opacity = (filter === "SECTORS" || filter === "MARKET" ? 0.11 : 0.04) * k;
    if (!showLabels) return;
    const next = new Set<string>();
    for (const { sub, centre } of centroids) {
      if (camera.position.distanceTo(centre) < 520) next.add(sub.id);
      if (next.size >= 24) break;
    }
    if (next.size !== visible.size || [...next].some((id) => !visible.has(id))) setVisible(next);
  });

  return (
    <group>
      <lineSegments ref={lineRef} geometry={geometry} frustumCulled={false}>
        <lineBasicMaterial color="#9fb6e6" transparent opacity={0} depthWrite={false}
                           blending={THREE.AdditiveBlending} toneMapped={false} />
      </lineSegments>
      {showLabels && centroids.filter((c) => visible.has(c.sub.id)).map(({ sub, centre }) => (
        <Html key={sub.id} position={[centre.x, centre.y + 4.5, centre.z]} center zIndexRange={[9, 0]}
              style={{ pointerEvents: "none", userSelect: "none" }}>
          <span className="whitespace-nowrap font-sans text-[11px] tracking-[0.04em]"
                style={{ color: "#dfe6f3", textShadow: "0 0 8px #000, 0 0 2px #000" }}>
            {sub.label}
          </span>
        </Html>
      ))}
    </group>
  );
}

function dist2(a: [number, number, number], b: [number, number, number]) {
  const dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
  return dx * dx + dy * dy + dz * dz;
}
