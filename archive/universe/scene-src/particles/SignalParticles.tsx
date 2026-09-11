"use client";

/** Particle attraction around qualifying setups (spec 50).
 *
 *  A pulse alone reads as "this moved"; particles converging on a star read as
 *  "this is a trade". Stronger setups attract more particles and hold them
 *  tighter. Kept restrained rather than flashy, and capped so a broad signal
 *  day cannot tank the frame rate.
 */

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useUniverseStore } from "@/stores/useUniverseStore";

const MAX_SIGNALS = 24;
const PARTICLES_PER_SIGNAL = 26;

export function SignalParticles() {
  const pointsRef = useRef<THREE.Points>(null);
  const entities = useUniverseStore((s) => s.entities);
  const filter = useUniverseStore((s) => s.filter);

  const signals = useMemo(
    () =>
      entities
        .filter((e) => e.signal?.active)
        .sort((a, b) => (b.signal?.score ?? 0) - (a.signal?.score ?? 0))
        .slice(0, MAX_SIGNALS),
    [entities],
  );

  const { positions, seeds, count } = useMemo(() => {
    const total = signals.length * PARTICLES_PER_SIGNAL;
    const positions = new Float32Array(total * 3);
    const seeds = new Float32Array(total * 4); // signalIndex, phase, radius, speed
    for (let s = 0; s < signals.length; s += 1) {
      const score = signals[s].signal?.score ?? 70;
      // 70-79 subtle, 80-89 moderate, 90+ strong (spec 50).
      const density = score >= 90 ? 1 : score >= 80 ? 0.7 : 0.42;
      for (let p = 0; p < PARTICLES_PER_SIGNAL; p += 1) {
        const i = s * PARTICLES_PER_SIGNAL + p;
        seeds[i * 4] = s;
        seeds[i * 4 + 1] = Math.random() * Math.PI * 2;
        // Stronger signals hold their particles closer to the star.
        seeds[i * 4 + 2] = (2.2 + Math.random() * 7.0) * (1.35 - 0.45 * density);
        seeds[i * 4 + 3] = 0.3 + Math.random() * 0.55;
      }
    }
    return { positions, seeds, count: total };
  }, [signals]);

  useFrame((state) => {
    const points = pointsRef.current;
    if (!points || count === 0) return;
    const array = points.geometry.attributes.position.array as Float32Array;
    const t = state.clock.elapsedTime;

    for (let i = 0; i < count; i += 1) {
      const signalIndex = seeds[i * 4];
      const entity = signals[signalIndex];
      if (!entity) continue;
      const phase = seeds[i * 4 + 1];
      const radius = seeds[i * 4 + 2];
      const speed = seeds[i * 4 + 3];

      // Each particle spirals inward, then resets - a continuous drift toward
      // the setup rather than a static halo.
      const progress = (t * speed * 0.22 + phase) % 1;
      const r = radius * (1 - progress * 0.72);
      const angle = phase * 6.283 + progress * 8.5;
      const lift = Math.sin(phase * 3.1 + progress * 4.0) * r * 0.35;

      array[i * 3] = entity.position[0] + Math.cos(angle) * r;
      array[i * 3 + 1] = entity.position[1] + lift;
      array[i * 3 + 2] = entity.position[2] + Math.sin(angle) * r;
    }
    points.geometry.attributes.position.needsUpdate = true;
  });

  if (count === 0) return null;

  // In POLITICAL/PORTFOLIO/WATCHLIST views, signal particles would compete with
  // the layer the user actually asked for.
  const opacity = filter === "SIGNALS" ? 0.85 : filter === "MARKET" ? 0.5 : 0.18;

  return (
    <points ref={pointsRef} key={count} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={count}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.62}
        color="#9df0ff"
        transparent
        opacity={opacity}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

/** Thin orbital rings marking disclosed political activity (spec 52).
 *
 *  Deliberately a different visual grammar from a trade signal: a ring, not a
 *  pulse, so the two are never confused. */
export function PoliticalRings() {
  const entities = useUniverseStore((s) => s.entities);
  const filter = useUniverseStore((s) => s.filter);
  const groupRef = useRef<THREE.Group>(null);

  const marked = useMemo(
    () => entities.filter((e) => e.political?.active).slice(0, 60),
    [entities],
  );

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.children.forEach((child, i) => {
        child.rotation.z = state.clock.elapsedTime * 0.12 + i * 0.4;
      });
    }
  });

  if (marked.length === 0) return null;
  const opacity = filter === "POLITICAL" ? 0.9 : filter === "MARKET" ? 0.42 : 0.14;

  return (
    <group ref={groupRef}>
      {marked.map((entity) => {
        const count = entity.political?.count ?? 1;
        // One disclosure: one subtle ring. Multiple politicians: a second,
        // wider ring - more prominent without becoming a signal.
        const rings = Math.min(2, count > 1 ? 2 : 1);
        return (
          <group key={entity.id} position={entity.position} rotation={[Math.PI / 2.6, 0, 0]}>
            {Array.from({ length: rings }, (_, r) => (
              <mesh key={r}>
                <torusGeometry
                  args={[entity.size * (2.6 + r * 1.5), 0.055 + r * 0.02, 6, 48]}
                />
                <meshBasicMaterial
                  color={(entity.political?.consensus ?? 0) > 0.6 ? "#e8c26b" : "#b79bd6"}
                  transparent
                  opacity={opacity * (r === 0 ? 1 : 0.6)}
                  depthWrite={false}
                  toneMapped={false}
                />
              </mesh>
            ))}
          </group>
        );
      })}
    </group>
  );
}

/** A persistent inner halo on held positions, so the portfolio stays locatable
 *  while exploring unrelated sectors (spec 53). */
export function PortfolioMarkers() {
  const entities = useUniverseStore((s) => s.entities);
  const filter = useUniverseStore((s) => s.filter);

  const held = useMemo(() => entities.filter((e) => e.portfolio?.held), [entities]);
  if (held.length === 0) return null;

  const opacity = filter === "PORTFOLIO" ? 0.8 : 0.34;

  return (
    <group>
      {held.map((entity) => {
        const warmth = entity.portfolio?.warmth ?? 0.5;
        const color = new THREE.Color().setHSL(
          // Warm for a winner, cool for a loser - a shift in temperature, not a
          // red/green alarm (spec 54).
          0.08 + 0.42 * (1 - warmth),
          0.5,
          0.55,
        );
        return (
          <mesh key={entity.id} position={entity.position}>
            <sphereGeometry args={[entity.size * 2.2, 16, 16]} />
            <meshBasicMaterial
              color={color}
              transparent
              opacity={opacity * 0.3}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
              toneMapped={false}
            />
          </mesh>
        );
      })}
    </group>
  );
}
