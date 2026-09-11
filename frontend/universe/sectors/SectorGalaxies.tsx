"use client";

/** Sector galaxies: a soft core plus a label that appears only when relevant.
 *
 *  Spec 58-59: sectors must be identifiable without permanent labels, so text
 *  is shown near, hovered, selected or searched - never 500 labels at once.
 *
 *  Labels are DOM elements via drei's <Html>, not SDF text. troika-based text
 *  suspends until it can fetch a font index from a CDN, and a single blocked
 *  request would leave the entire scene in its Suspense fallback - a blank
 *  universe because a label font was unreachable. DOM labels use the page's own
 *  fonts, need no network, and there are never more than a couple of dozen.
 */

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useUniverseStore } from "@/stores/useUniverseStore";
import type { UniverseSector } from "@/lib/types";

const LABEL_DISTANCE = 420;

function SectorCore({ sector }: { sector: UniverseSector }) {
  const { camera } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const [near, setNear] = useState(false);
  const hovered = useUniverseStore((s) => s.hovered);
  const selected = useUniverseStore((s) => s.selected);
  const filter = useUniverseStore((s) => s.filter);
  const showLabels = useUniverseStore((s) => s.showLabels);
  const setHovered = useUniverseStore((s) => s.setHovered);
  const focusOn = useUniverseStore((s) => s.focusOn);

  const position = useMemo(
    () => new THREE.Vector3(...sector.position),
    [sector.position],
  );

  const color = useMemo(() => {
    const c = new THREE.Color();
    // Relative strength brightens the galaxy core; sector hue identifies it.
    const rs = Math.max(-1, Math.min(1, sector.relative_strength * 25));
    c.setHSL(sector.hue / 360, 0.55, 0.34 + 0.2 * rs);
    return c;
  }, [sector.hue, sector.relative_strength]);

  const isActive = hovered === sector.id || selected === sector.id;
  const emphasised = filter === "SECTORS" || filter === "MARKET";

  useFrame(() => {
    const distance = camera.position.distanceTo(position);
    const shouldShow = distance < LABEL_DISTANCE;
    if (shouldShow !== near) setNear(shouldShow);
    if (groupRef.current) {
      // A very slow drift so the scene is alive but never a screensaver.
      groupRef.current.rotation.y += 0.00035;
    }
  });

  const labelVisible = showLabels && (near || isActive);
  const coreScale = 8 + sector.member_count * 0.11;

  return (
    <group ref={groupRef} position={position}>
      <mesh
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(sector.id);
        }}
        onPointerOut={() => setHovered(null)}
        onClick={(e) => {
          e.stopPropagation();
          focusOn(sector.id);
        }}
      >
        <sphereGeometry args={[coreScale, 20, 20]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={(isActive ? 0.22 : 0.13) * (emphasised ? 1 : 0.45)}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* Inner light so a galaxy reads as a source, not a bubble. */}
      <pointLight
        color={color}
        intensity={emphasised ? 70 : 24}
        distance={coreScale * 10}
        decay={2}
      />

      {labelVisible && (
        <Html
          position={[0, coreScale + 7, 0]}
          center
          zIndexRange={[10, 0]}
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          <div className="flex flex-col items-center whitespace-nowrap">
            <span
              className="font-mono uppercase tracking-[0.22em]"
              style={{
                fontSize: isActive ? 13 : 10.5,
                color: isActive ? "#e8ecf4" : "#9aa5bb",
                textShadow: "0 0 6px #05070d, 0 0 2px #05070d",
              }}
            >
              {sector.label}
            </span>
            {isActive && (
              <span
                className="mt-0.5 font-mono text-[10px] tracking-[0.14em]"
                style={{ color: "#5ad1e6", textShadow: "0 0 6px #05070d" }}
              >
                {sector.rs_label} · {sector.signal_count} signal
                {sector.signal_count === 1 ? "" : "s"}
              </span>
            )}
          </div>
        </Html>
      )}
    </group>
  );
}

export function SectorGalaxies() {
  const sectors = useUniverseStore((s) => s.sectors);
  return (
    <group>
      {sectors.map((sector) => (
        <SectorCore key={sector.id} sector={sector} />
      ))}
    </group>
  );
}

/** Ticker labels for the few entities that have earned one: the selected name,
 *  the hovered one, and the highest-confidence candidate (spec 59). */
export function EntityLabels() {
  const { camera } = useThree();
  const entities = useUniverseStore((s) => s.entities);
  const hovered = useUniverseStore((s) => s.hovered);
  const selected = useUniverseStore((s) => s.selected);
  const showLabels = useUniverseStore((s) => s.showLabels);
  const [nearby, setNearby] = useState<string[]>([]);

  const top = useMemo(() => {
    const withSignals = entities
      .filter((e) => e.signal?.active)
      .sort((a, b) => (b.signal?.score ?? 0) - (a.signal?.score ?? 0));
    return withSignals.slice(0, 3).map((e) => e.id);
  }, [entities]);

  useFrame(() => {
    if (!showLabels) return;
    // Proximity labels, recomputed cheaply and capped so a dense cluster never
    // turns into a wall of text.
    const close: string[] = [];
    for (const entity of entities) {
      const dx = camera.position.x - entity.position[0];
      const dy = camera.position.y - entity.position[1];
      const dz = camera.position.z - entity.position[2];
      if (dx * dx + dy * dy + dz * dz < 900) {
        close.push(entity.id);
        if (close.length >= 12) break;
      }
    }
    if (close.join() !== nearby.join()) setNearby(close);
  });

  if (!showLabels) return null;

  const ids = new Set<string>([...nearby, ...top]);
  if (hovered) ids.add(hovered);
  if (selected) ids.add(selected);

  return (
    <group>
      {[...ids].map((id) => {
        const entity = entities.find((e) => e.id === id);
        if (!entity) return null;
        const emphasis = hovered === id || selected === id;
        return (
          <Html
            key={id}
            position={[
              entity.position[0],
              entity.position[1] + entity.size * 2.6 + 1.6,
              entity.position[2],
            ]}
            center
            zIndexRange={[10, 0]}
            style={{ pointerEvents: "none", userSelect: "none" }}
          >
            <span
              className="font-mono whitespace-nowrap"
              style={{
                fontSize: emphasis ? 12 : 10,
                color: emphasis ? "#e8ecf4" : "#8794ad",
                textShadow: "0 0 6px #05070d, 0 0 2px #05070d",
              }}
            >
              {entity.id}
            </span>
          </Html>
        );
      })}
    </group>
  );
}
