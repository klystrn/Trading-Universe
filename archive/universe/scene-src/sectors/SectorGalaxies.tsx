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
import { Galaxy } from "@/universe/sectors/Galaxy";
import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useState } from "react";
import { useUniverseStore } from "@/stores/useUniverseStore";

export function SectorGalaxies() {
  const sectors = useUniverseStore((s) => s.sectors);
  return (
    <group>
      {sectors.map((sector, index) => (
        <Galaxy key={sector.id} sector={sector} index={index} />
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
