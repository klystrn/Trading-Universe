"use client";

/** Sector-rotation arcs - the 5% capital-flow layer (spec 51).
 *
 *  This is INFERRED from relative strength, never observed institutional flow.
 *  The backend labels every arc as such and the legend says so; nothing here
 *  may imply a precision the data does not have.
 */

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { softStarTexture } from "@/universe/render/textures";

function arcCurve(from: THREE.Vector3, to: THREE.Vector3): THREE.QuadraticBezierCurve3 {
  const mid = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
  // Lift the midpoint so arcs read as currents above the plane rather than as
  // lines cutting through galaxies.
  mid.y += from.distanceTo(to) * 0.22 + 30;
  return new THREE.QuadraticBezierCurve3(from, mid, to);
}

export function FlowArcs() {
  const flows = useUniverseStore((s) => s.flows);
  const sectorById = useUniverseStore((s) => s.sectorById);
  const showFlows = useUniverseStore((s) => s.showFlows);
  const filter = useUniverseStore((s) => s.filter);
  const pointsRef = useRef<THREE.Points>(null);

  const arcs = useMemo(
    () =>
      flows
        .map((flow) => {
          const from = sectorById.get(flow.from);
          const to = sectorById.get(flow.to);
          if (!from || !to) return null;
          return {
            ...flow,
            curve: arcCurve(
              new THREE.Vector3(...from.position),
              new THREE.Vector3(...to.position),
            ),
          };
        })
        .filter(Boolean) as (typeof flows[number] & {
        curve: THREE.QuadraticBezierCurve3;
      })[],
    [flows, sectorById],
  );

  // Travelling motes along each arc give direction without animating geometry.
  const motes = useMemo(() => {
    const perArc = 14;
    const total = arcs.length * perArc;
    return {
      positions: new Float32Array(total * 3),
      offsets: Float32Array.from(
        { length: total },
        (_, i) => (i % perArc) / perArc,
      ),
      perArc,
      total,
    };
  }, [arcs]);

  useFrame((state) => {
    const points = pointsRef.current;
    if (!points || motes.total === 0) return;
    const array = points.geometry.attributes.position.array as Float32Array;
    const t = state.clock.elapsedTime;

    for (let i = 0; i < motes.total; i += 1) {
      const arcIndex = Math.floor(i / motes.perArc);
      const arc = arcs[arcIndex];
      if (!arc) continue;
      const progress = (motes.offsets[i] + t * 0.06 * (0.5 + arc.strength)) % 1;
      const point = arc.curve.getPoint(progress);
      array[i * 3] = point.x;
      array[i * 3 + 1] = point.y;
      array[i * 3 + 2] = point.z;
    }
    points.geometry.attributes.position.needsUpdate = true;
  });

  if (!showFlows || arcs.length === 0) return null;

  // Low opacity by design: flow must never overpower the constellation.
  const base = filter === "SECTORS" || filter === "MARKET" ? 1 : 0.35;

  return (
    <group>
      {arcs.map((arc) => {
        const geometry = new THREE.BufferGeometry().setFromPoints(
          arc.curve.getPoints(48),
        );
        return (
          <primitive
            key={`${arc.from}-${arc.to}`}
            object={
              new THREE.Line(
                geometry,
                new THREE.LineBasicMaterial({
                  color: new THREE.Color("#5ad1e6"),
                  transparent: true,
                  opacity: 0.025 * base * (0.5 + arc.strength * 0.5),
                  depthWrite: false,
                  toneMapped: false,
                }),
              )
            }
          />
        );
      })}

      <points ref={pointsRef} key={motes.total} frustumCulled={false}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[motes.positions, 3]}
            count={motes.total}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.9}
          color="#9df0ff"
          transparent
          opacity={0.07 * base}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
      </points>
    </group>
  );
}

/** The deep sky: three layers of distant stars at different sizes and tints,
 *  plus a faint band of dense faint stars, so the universe has depth and the
 *  galaxies sit in something rather than on black. */
export function BackgroundStars() {
  const layers = useMemo(() => {
    let seed = 12345;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const make = (count: number, rMin: number, rMax: number, band: number) => {
      const positions = new Float32Array(count * 3);
      const colors = new Float32Array(count * 3);
      const c = new THREE.Color();
      for (let i = 0; i < count; i += 1) {
        const theta = rnd() * Math.PI * 2;
        // `band` squeezes a share of stars toward the plane: a milky way.
        const inBand = rnd() < band;
        const phi = inBand
          ? Math.PI / 2 + (rnd() - 0.5) * 0.35
          : Math.acos(2 * rnd() - 1);
        const r = rMin + rnd() * (rMax - rMin);
        positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = r * Math.cos(phi) * 0.7;
        positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
        // Mostly white with a scatter of blue and amber stars.
        const kind = rnd();
        if (kind < 0.12) c.setHSL(0.6, 0.6, 0.78);
        else if (kind < 0.2) c.setHSL(0.09, 0.6, 0.75);
        else c.setHSL(0.62, 0.08, 0.72 + rnd() * 0.28);
        const b = 0.35 + rnd() * 0.65;
        colors[i * 3] = c.r * b; colors[i * 3 + 1] = c.g * b; colors[i * 3 + 2] = c.b * b;
      }
      return { positions, colors, count };
    };
    return [
      { ...make(9000, 2400, 3600, 0.55), size: 1.1, opacity: 0.55 },
      { ...make(2600, 2200, 3400, 0.35), size: 1.9, opacity: 0.75 },
      { ...make(500, 2000, 3200, 0.2), size: 3.0, opacity: 0.9 },
    ];
  }, []);

  return (
    <group>
      {layers.map((layer, i) => (
        <points key={i} frustumCulled={false}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[layer.positions, 3]} />
            <bufferAttribute attach="attributes-color" args={[layer.colors, 3]} />
          </bufferGeometry>
          <pointsMaterial
            size={layer.size}
            map={softStarTexture()}
            vertexColors
            transparent
            opacity={layer.opacity}
            sizeAttenuation={false}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </points>
      ))}
    </group>
  );
}
