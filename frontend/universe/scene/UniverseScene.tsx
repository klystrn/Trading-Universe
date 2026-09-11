"use client";

/** The Trading Universe scene: 95% market constellation, 5% capital flowfield.
 *
 *  This is the dominant interface, not a decorative background (spec 80). It
 *  must communicate how the market is behaving, how each sector is behaving,
 *  where signals are forming, and how capital is rotating.
 */

import { Canvas } from "@react-three/fiber";
import { AdaptiveDpr, AdaptiveEvents, Preload } from "@react-three/drei";
import { Suspense, useEffect } from "react";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { StarField } from "@/universe/entities/StarField";
import { EntityLabels, SectorGalaxies } from "@/universe/sectors/SectorGalaxies";
import {
  PoliticalRings,
  PortfolioMarkers,
  SignalParticles,
} from "@/universe/particles/SignalParticles";
import { BackgroundStars, FlowArcs } from "@/universe/particles/FlowArcs";
import { FlyControls, usePointerLock } from "@/universe/controls/FlyControls";

function SceneContents() {
  usePointerLock();
  return (
    <>
      {/* Minimal lighting: a dim ambient plus one key light. Sector cores
          carry their own point lights, which is enough (spec 78). */}
      <ambientLight intensity={0.7} color="#8fa0c8" />
      <hemisphereLight args={["#b9c8ea", "#1a2036", 0.35]} />
      <directionalLight position={[200, 320, 180]} intensity={0.6} color="#dbe8ff" />
      <fog attach="fog" args={["#05070d", 900, 2600]} />

      <BackgroundStars />
      <StarField />
      <SignalParticles />
      <PoliticalRings />
      <PortfolioMarkers />
      <FlowArcs />
      {/* Anything that could suspend gets its own boundary: a stalled label
          must only ever hide itself, never the universe underneath it. */}
      <Suspense fallback={null}>
        <SectorGalaxies />
      </Suspense>
      <Suspense fallback={null}>
        <EntityLabels />
      </Suspense>

      <FlyControls />
      <Preload all />
    </>
  );
}

export function UniverseScene() {
  const loaded = useUniverseStore((s) => s.loaded);

  // Escape releases the pointer and stops flying, so the user is never trapped.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && document.pointerLockElement) {
        document.exitPointerLock();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="absolute inset-0">
      <Canvas
        camera={{ position: [0, 95, 440], fov: 62, near: 0.6, far: 3200 }}
        gl={{
          antialias: true,
          powerPreference: "high-performance",
          alpha: false,
        }}
        // Cap DPR: a 3x retina display would otherwise render 9x the pixels for
        // no visible gain on a scene this soft.
        dpr={[1, 1.75]}
        performance={{ min: 0.5 }}
        onCreated={({ gl }) => gl.setClearColor("#05070d")}
      >
        <Suspense fallback={null}>
          <SceneContents />
        </Suspense>
        <AdaptiveDpr pixelated={false} />
        <AdaptiveEvents />
      </Canvas>

      {!loaded && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-glass-edge border-t-accent" />
            <p className="font-mono text-xs uppercase tracking-[0.28em] text-ink-faint">
              Mapping the universe
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
