"use client";

/** The stocks as glowing stars.
 *
 *  Two layers share one set of positions:
 *    - a point-sprite layer (custom additive shader) that is what you SEE:
 *      per-star size from market cap, brightness from price movement, a warm
 *      or cool cast for the direction of the move, a pulse for a live signal;
 *    - a tiny instanced mesh that is what you HOVER: it gives per-instance
 *      raycasting, which point sprites cannot, and is invisible.
 *
 *  Encoding (spec 49): orbit speed <- volume, brightness <- price movement,
 *  size <- log market cap, position <- sector / subsector.
 */

import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { entityEmphasis, useUniverseStore } from "@/stores/useUniverseStore";
import { createGlowPointsMaterial } from "@/universe/render/GlowPointsMaterial";
import { softStarTexture } from "@/universe/render/textures";
import type { UniverseEntity } from "@/lib/types";

const dummy = new THREE.Object3D();
const tmp = new THREE.Color();
const WARM = new THREE.Color("#ffd9a8");   // advancing
const NEUTRAL = new THREE.Color("#e6eeff"); // flat
const COOL = new THREE.Color("#8fa8e8");    // declining
const SIGNAL = new THREE.Color("#b9f4ff");
const HELD = new THREE.Color("#ffc98a");

function starColor(entity: UniverseEntity, emphasis: number, hovered: boolean, selected: boolean) {
  const move = Math.max(-1, Math.min(1, entity.price_change * 12));
  if (move >= 0) tmp.copy(NEUTRAL).lerp(WARM, move);
  else tmp.copy(NEUTRAL).lerp(COOL, -move);
  // Brightness follows intensity (price movement magnitude), floored so a
  // quiet star is dim, not invisible.
  let brightness = 0.55 + 0.9 * Math.abs(entity.intensity - 0.5) * 2;
  if (entity.signal?.active) { tmp.lerp(SIGNAL, 0.55); brightness += 0.5; }
  if (entity.portfolio?.held) { tmp.lerp(HELD, 0.5); brightness += 0.25; }
  if (hovered || selected) brightness += 0.8;
  brightness *= 0.25 + 0.75 * emphasis;
  return tmp.multiplyScalar(brightness);
}

export function StarField() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const pointsRef = useRef<THREE.Points>(null);
  const { gl } = useThree();

  const entities = useUniverseStore((s) => s.entities);
  const filter = useUniverseStore((s) => s.filter);
  const hovered = useUniverseStore((s) => s.hovered);
  const selected = useUniverseStore((s) => s.selected);
  const setHovered = useUniverseStore((s) => s.setHovered);
  const select = useUniverseStore((s) => s.select);
  const count = entities.length;

  const orbits = useMemo(
    () => entities.map((entity, index) => {
      const seed = (index * 2654435761) % 1000;
      return {
        radius: 0.9 + (seed % 17) * 0.16,
        phase: (seed % 360) * (Math.PI / 180),
        speed: entity.orbit_speed,
      };
    }),
    [entities],
  );

  const buffers = useMemo(() => ({
    positions: new Float32Array(count * 3),
    colors: new Float32Array(count * 3),
    sizes: new Float32Array(count),
    pulses: new Float32Array(count),
  }), [count]);

  const material = useMemo(
    () => createGlowPointsMaterial(softStarTexture(), { sizeScale: 520, minSize: 2.0, maxSize: 140 }),
    [],
  );

  // Colour / size / pulse change with data or emphasis, not every frame.
  useEffect(() => {
    for (let i = 0; i < count; i += 1) {
      const e = entities[i];
      const emphasis = entityEmphasis(e, filter);
      const c = starColor(e, emphasis, hovered === e.id, selected === e.id);
      buffers.colors[i * 3] = c.r; buffers.colors[i * 3 + 1] = c.g; buffers.colors[i * 3 + 2] = c.b;
      let size = 0.9 + e.size * 1.35;
      size *= 0.5 + 0.5 * emphasis;
      if (hovered === e.id || selected === e.id) size *= 1.6;
      buffers.sizes[i] = size;
      buffers.pulses[i] = e.signal?.active
        ? (e.signal.pulse === "strong" ? 1 : e.signal.pulse === "moderate" ? 0.65 : 0.35)
        : 0;
    }
    const geom = pointsRef.current?.geometry;
    if (geom) {
      (geom.attributes.aColor as THREE.BufferAttribute).needsUpdate = true;
      (geom.attributes.aSize as THREE.BufferAttribute).needsUpdate = true;
      (geom.attributes.aPulse as THREE.BufferAttribute).needsUpdate = true;
    }
  }, [entities, filter, hovered, selected, count, buffers]);

  useFrame((state) => {
    const mesh = meshRef.current;
    const points = pointsRef.current;
    if (!mesh || !points || count === 0) return;
    const t = state.clock.elapsedTime;
    material.uniforms.uTime.value = t;
    material.uniforms.uPixelRatio.value = gl.getPixelRatio();

    for (let i = 0; i < count; i += 1) {
      const e = entities[i];
      const o = orbits[i];
      const paused = hovered === e.id;                        // hover stabilises (spec 47)
      const angle = paused ? o.phase : o.phase + t * o.speed;
      const x = e.position[0] + Math.cos(angle) * o.radius;
      const y = e.position[1] + Math.sin(angle * 0.7) * o.radius * 0.2;
      const z = e.position[2] + Math.sin(angle) * o.radius;
      buffers.positions[i * 3] = x; buffers.positions[i * 3 + 1] = y; buffers.positions[i * 3 + 2] = z;

      dummy.position.set(x, y, z);
      dummy.scale.setScalar(0.6 + e.size * 0.5);            // pick radius only
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    (points.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
    mesh.instanceMatrix.needsUpdate = true;
  });

  const onPointerMove = useCallback((event: any) => {
    if (document.pointerLockElement) return;   // the crosshair picks in fly mode
    event.stopPropagation();
    const e = entities[event.instanceId ?? -1];
    if (e) setHovered(e.id);
  }, [entities, setHovered]);
  const onPointerOut = useCallback(() => { if (!document.pointerLockElement) setHovered(null); }, [setHovered]);
  const onClick = useCallback((event: any) => {
    if (document.pointerLockElement) return;
    event.stopPropagation();
    const e = entities[event.instanceId ?? -1];
    if (e) select(e.id);
  }, [entities, select]);

  if (count === 0) return null;

  return (
    <group>
      <points key={`glow-${count}`} ref={pointsRef} frustumCulled={false} material={material} renderOrder={5}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
          <bufferAttribute attach="attributes-aColor" args={[buffers.colors, 3]} />
          <bufferAttribute attach="attributes-aSize" args={[buffers.sizes, 1]} />
          <bufferAttribute attach="attributes-aPulse" args={[buffers.pulses, 1]} />
        </bufferGeometry>
      </points>

      <instancedMesh
        key={`pick-${count}`}
        ref={meshRef}
        args={[undefined, undefined, count]}
        frustumCulled={false}
        userData={{ pick: "stock" }}
        onPointerMove={onPointerMove}
        onPointerOut={onPointerOut}
        onClick={onClick}
      >
        <sphereGeometry args={[1, 6, 6]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </instancedMesh>
    </group>
  );
}
