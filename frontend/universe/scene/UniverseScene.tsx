"use client";

/** The Trading Universe scene: 95% market constellation, 5% capital flowfield.
 *
 *  This is the dominant interface, not a decorative background (spec 80). It
 *  must communicate how the market is behaving, how each sector is behaving,
 *  where signals are forming, and how capital is rotating.
 */

import { Canvas } from "@react-three/fiber";
import { AdaptiveDpr, AdaptiveEvents, Preload } from "@react-three/drei";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { Suspense, useEffect } from "react";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { StarField } from "@/universe/entities/StarField";
import { EntityLabels, SectorGalaxies } from "@/universe/sectors/SectorGalaxies";
import { Constellations } from "@/universe/sectors/Galaxy";
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
      {/* Everything visible is emissive (additive sprites), so lighting is
          only there for the few lit meshes; the mood comes from bloom. */}
      <ambientLight intensity={0.25} color="#8fa0c8" />
      <fog attach="fog" args={["#03040a", 1800, 4800]} />

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
        <Constellations />
      </Suspense>
      <Suspense fallback={null}>
        <EntityLabels />
      </Suspense>

      {/* Bloom is what turns points of light into stars. Threshold sits above
          the dim arm particles so only cores, bright stars and signals bloom. */}
      <EffectComposer multisampling={0}>
        <Bloom luminanceThreshold={0.32} luminanceSmoothing={0.35} intensity={1.15}
               mipmapBlur radius={0.72} />
        <Vignette eskil={false} offset={0.22} darkness={0.55} />
      </EffectComposer>

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
        camera={{ position: [0, 620, 820], fov: 56, near: 0.6, far: 7000 }}
        gl={{
          antialias: true,
          powerPreference: "high-performance",
          alpha: false,
        }}
        // Cap DPR: a 3x retina display would otherwise render 9x the pixels for
        // no visible gain on a scene this soft.
        dpr={[1, 1.75]}
        performance={{ min: 0.5 }}
        onCreated={({ gl }) => gl.setClearColor("#03040a")}
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
