"use client";

/** The stocks, as one instanced mesh (spec 78).
 *
 *  474 entities is far too many for one React component each. A single
 *  InstancedMesh carries position, scale and colour per instance; orbital
 *  motion and pulse are computed on the CPU into the instance matrices, which
 *  keeps the whole field to one draw call.
 *
 *  Encoding (spec 49):
 *    orbit speed  <- volume       brightness <- price movement
 *    size         <- market cap   position   <- sector / subsector
 */

import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { entityEmphasis, useUniverseStore } from "@/stores/useUniverseStore";
import type { UniverseEntity, UniverseSector } from "@/lib/types";

const dummy = new THREE.Object3D();
const color = new THREE.Color();

/** Sector hue plus price-movement lightness. Never red/green alone: hue carries
 *  sector identity and lightness carries direction, so the scene stays readable
 *  without relying on colour vision (spec 49). */
function entityColor(
  entity: UniverseEntity,
  sector: UniverseSector | undefined,
  emphasis: number,
  selected: boolean,
  hovered: boolean,
): THREE.Color {
  const hue = (sector?.hue ?? 205) / 360;
  const move = Math.max(-1, Math.min(1, entity.price_change * 14));

  let saturation = 0.35 + 0.3 * Math.abs(move);
  let lightness = 0.34 + 0.3 * entity.intensity;

  if (entity.signal?.active) {
    saturation = Math.min(1, saturation + 0.3);
    lightness = Math.min(0.9, lightness + 0.14);
  }
  if (entity.portfolio?.held) {
    // Subtle warmth for a winner, quieter for a loser - never a flashing alarm
    // (spec 54).
    lightness = Math.min(0.92, lightness + 0.10 * (entity.portfolio.warmth - 0.5));
    saturation = Math.min(1, saturation + 0.12);
  }
  if (hovered) lightness = Math.min(0.96, lightness + 0.22);
  if (selected) {
    saturation = Math.min(1, saturation + 0.25);
    lightness = Math.min(0.96, lightness + 0.18);
  }

  color.setHSL(hue, saturation, lightness * (0.25 + 0.75 * emphasis));
  return color;
}

export function StarField() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const { camera } = useThree();
  const entities = useUniverseStore((s) => s.entities);
  const sectorById = useUniverseStore((s) => s.sectorById);
  const filter = useUniverseStore((s) => s.filter);
  const hovered = useUniverseStore((s) => s.hovered);
  const selected = useUniverseStore((s) => s.selected);
  const setHovered = useUniverseStore((s) => s.setHovered);
  const select = useUniverseStore((s) => s.select);

  const count = entities.length;

  /** Per-entity orbit parameters, derived once so the motion is stable across
   *  payload updates rather than reshuffling every tick. */
  const orbits = useMemo(
    () =>
      entities.map((entity, index) => {
        const seed = (index * 2654435761) % 1000;
        return {
          radius: 1.4 + (seed % 17) * 0.22,
          phase: (seed % 360) * (Math.PI / 180),
          tilt: ((seed % 53) / 53 - 0.5) * 0.9,
          speed: entity.orbit_speed,
        };
      }),
    [entities],
  );

  // Colours only change when the data or emphasis does, not every frame.
  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;
    for (let i = 0; i < count; i += 1) {
      const entity = entities[i];
      const emphasis = entityEmphasis(entity, filter);
      mesh.setColorAt(
        i,
        entityColor(
          entity,
          sectorById.get(entity.sector),
          emphasis,
          selected === entity.id,
          hovered === entity.id,
        ),
      );
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [entities, sectorById, filter, hovered, selected, count]);

  useFrame((state) => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;
    const t = state.clock.elapsedTime;

    for (let i = 0; i < count; i += 1) {
      const entity = entities[i];
      const orbit = orbits[i];
      const [x, y, z] = entity.position;

      // Hovering pauses the entity so it can be read (spec 47).
      const paused = hovered === entity.id;
      const angle = paused ? orbit.phase : orbit.phase + t * orbit.speed;

      dummy.position.set(
        x + Math.cos(angle) * orbit.radius,
        y + Math.sin(angle * 0.7 + orbit.tilt) * orbit.radius * 0.35,
        z + Math.sin(angle) * orbit.radius,
      );

      let scale = entity.size;
      const emphasis = entityEmphasis(entity, filter);
      scale *= 0.45 + 0.55 * emphasis;

      // Level of detail in reverse: far stars get a floor on apparent size so
      // the constellation stays legible from the overview (spec 60), while a
      // star you have flown up to keeps its true scale.
      const distance = camera.position.distanceTo(dummy.position);
      scale = Math.max(scale, distance * 0.0042 * (0.6 + 0.4 * emphasis));

      // A qualifying setup pulses; intensity tracks signal strength (spec 50).
      if (entity.signal?.active && !paused) {
        const strength =
          entity.signal.pulse === "strong" ? 0.34
          : entity.signal.pulse === "moderate" ? 0.2
          : 0.11;
        scale *= 1 + strength * (0.5 + 0.5 * Math.sin(t * 2.1 + orbit.phase));
      }
      if (paused || selected === entity.id) scale *= 1.5;

      dummy.scale.setScalar(scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  const onPointerMove = useCallback(
    (event: any) => {
      event.stopPropagation();
      const index = event.instanceId;
      if (index == null) return;
      const entity = entities[index];
      if (entity) setHovered(entity.id);
    },
    [entities, setHovered],
  );

  const onPointerOut = useCallback(() => setHovered(null), [setHovered]);

  const onClick = useCallback(
    (event: any) => {
      event.stopPropagation();
      const index = event.instanceId;
      if (index == null) return;
      const entity = entities[index];
      if (entity) select(entity.id);
    },
    [entities, select],
  );

  if (count === 0) return null;

  return (
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, count]}
      frustumCulled={false}
      onPointerMove={onPointerMove}
      onPointerOut={onPointerOut}
      onClick={onClick}
    >
      {/* Detail 2 is smooth enough to read as a body rather than a gem, and
          at 320 triangles x 474 instances still a single cheap draw call. */}
      <icosahedronGeometry args={[1, 2]} />
      <meshStandardMaterial toneMapped={false} roughness={0.6} metalness={0.02} />
    </instancedMesh>
  );
}
