"use client";

/** FPS-style picking while the pointer is locked.
 *
 *  With the pointer captured there is no cursor, so the browser's pointer
 *  position (and therefore R3F's own pointer events) is meaningless. This
 *  casts a ray from the exact screen centre every few frames against the
 *  tagged pick targets - the stars' instanced mesh and each galaxy's pick
 *  sphere - and drives the same `hovered` state the cursor would. A click
 *  while locked acts on whatever is under the crosshair.
 */

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";

const CENTRE = new THREE.Vector2(0, 0);

export function CrosshairPicker() {
  const { camera, scene } = useThree();
  const raycaster = useRef(new THREE.Raycaster());
  const frame = useRef(0);
  const entities = useUniverseStore((s) => s.entities);
  const setHovered = useUniverseStore((s) => s.setHovered);
  const select = useUniverseStore((s) => s.select);
  const focusOn = useUniverseStore((s) => s.focusOn);
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const lastHit = useRef<string | null>(null);

  useEffect(() => {
    // Stars are small; give the ray a little forgiveness.
    raycaster.current.params.Points = { threshold: 2.5 };
  }, []);

  useFrame(() => {
    if (!document.pointerLockElement) return;
    // Every third frame is plenty for a hover and keeps the raycast cheap.
    frame.current = (frame.current + 1) % 3;
    if (frame.current !== 0) return;

    raycaster.current.setFromCamera(CENTRE, camera);
    const targets: THREE.Object3D[] = [];
    scene.traverse((o) => { if (o.userData?.pick) targets.push(o); });
    const hits = raycaster.current.intersectObjects(targets, false);

    let id: string | null = null;
    for (const hit of hits) {
      const kind = hit.object.userData.pick;
      if (kind === "stock" && hit.instanceId != null) { id = entities[hit.instanceId]?.id ?? null; break; }
      if (kind === "sector") { id = hit.object.userData.id; break; }
    }
    if (id !== lastHit.current) {
      lastHit.current = id;
      setHovered(id);
    }
  });

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!document.pointerLockElement || e.button !== 0) return;
      const id = lastHit.current;
      if (!id) return;
      const { sectorById } = useUniverseStore.getState();
      if (sectorById.has(id)) {
        focusOn(id);                 // a galaxy: travel to it
      } else {
        select(id);                  // a star: select and open its chart
        openChartFor(id);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [focusOn, select, openChartFor]);

  return null;
}
