"use client";

/** WASD + mouse-look free navigation (spec 46).
 *
 *  The spec is specific about feel: smooth, calm, low-friction, inertia-light,
 *  easy to stop, and never inducing motion sickness. So velocity is damped
 *  heavily each frame rather than integrated freely, there is no acceleration
 *  curve that can run away, and pitch is clamped short of vertical.
 */

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useUniverseStore } from "@/stores/useUniverseStore";

const BASE_SPEED = 80;
const BOOST = 3.2;
const PRECISE = 0.3;
// High damping is what makes the camera stop the instant a key is released.
const DAMPING = 9.0;
// Was 0.0022 - far too twitchy. Input is also smoothed toward a target
// orientation each frame rather than applied raw.
const LOOK_SENSITIVITY = 0.0009;
const LOOK_SMOOTHING = 16.0;
const MAX_PITCH = Math.PI / 2 - 0.08;

export function FlyControls({ enabled = true }: { enabled?: boolean }) {
  const { camera, gl } = useThree();
  const setFlying = useUniverseStore((s) => s.setFlying);
  const focusTarget = useUniverseStore((s) => s.focusTarget);

  const keys = useRef<Record<string, boolean>>({});
  const velocity = useRef(new THREE.Vector3());
  const euler = useRef(new THREE.Euler(0, 0, 0, "YXZ"));
  const pointerLocked = useRef(false);
  const lookTarget = useRef<{ yaw: number; pitch: number } | null>(null);
  const travel = useRef<{
    from: THREE.Vector3;
    to: THREE.Vector3;
    lookAt: THREE.Vector3;
    t: number;
    duration: number;
  } | null>(null);

  const forward = useMemo(() => new THREE.Vector3(), []);
  const right = useMemo(() => new THREE.Vector3(), []);
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), []);

  // --- input ---------------------------------------------------------------
  useEffect(() => {
    if (!enabled) return;
    const canvas = gl.domElement;

    const onKeyDown = (e: KeyboardEvent) => {
      // Never swallow typing in the search bar or a panel input.
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      keys.current[e.code] = true;
      if (["Space", "ShiftLeft", "KeyW", "KeyA", "KeyS", "KeyD"].includes(e.code)) {
        e.preventDefault();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      keys.current[e.code] = false;
    };
    const onBlur = () => {
      keys.current = {};
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!pointerLocked.current) return;
      if (!lookTarget.current) {
        euler.current.setFromQuaternion(camera.quaternion);
        lookTarget.current = { yaw: euler.current.y, pitch: euler.current.x };
      }
      // Accumulate into a target; the frame loop eases toward it.
      lookTarget.current.yaw -= e.movementX * LOOK_SENSITIVITY;
      lookTarget.current.pitch = Math.max(
        -MAX_PITCH, Math.min(MAX_PITCH, lookTarget.current.pitch - e.movementY * LOOK_SENSITIVITY),
      );
      // Any manual look cancels a guided transition: travel is interruptible
      // (spec 55).
      travel.current = null;
    };

    const onPointerLockChange = () => {
      pointerLocked.current = document.pointerLockElement === canvas;
      setFlying(pointerLocked.current);
      if (!pointerLocked.current) keys.current = {};
      lookTarget.current = null;
    };

    const onWheel = (e: WheelEvent) => {
      camera.getWorldDirection(forward);
      // Scroll dollies along the view axis rather than changing FOV, which
      // keeps the sense of physical presence in the scene.
      camera.position.addScaledVector(forward, -e.deltaY * 0.25);
      travel.current = null;
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("pointerlockchange", onPointerLockChange);
    canvas.addEventListener("wheel", onWheel, { passive: true });

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("pointerlockchange", onPointerLockChange);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [camera, gl, enabled, setFlying, forward]);

  // --- guided camera travel (spec 55) ----------------------------------------
  useEffect(() => {
    if (!focusTarget) return;
    const to = new THREE.Vector3(...focusTarget.position);
    // Stop short of the target so it sits in front of the camera, not inside
    // it: a whole galaxy needs far more standoff than a single star.
    const isSector = useUniverseStore.getState().sectorById.has(focusTarget.id);
    const offset = new THREE.Vector3()
      .subVectors(camera.position, to)
      .normalize()
      .multiplyScalar(isSector ? 260 : 26);
    if (isSector) offset.y += 120;
    travel.current = {
      from: camera.position.clone(),
      to: to.clone().add(offset),
      lookAt: to.clone(),
      t: 0,
      // Cinematic but short, and scaled to distance so a nearby hop is not slow.
      duration: Math.min(
        2.2,
        0.7 + camera.position.distanceTo(to) / 900,
      ),
    };
  }, [focusTarget, camera]);

  // --- the loop ---------------------------------------------------------------
  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.1); // a tab-switch stall must not teleport us

    if (travel.current) {
      const trip = travel.current;
      trip.t = Math.min(1, trip.t + dt / trip.duration);
      // Smoothstep in and out: no jerk at either end.
      const e = trip.t * trip.t * (3 - 2 * trip.t);
      camera.position.lerpVectors(trip.from, trip.to, e);
      camera.lookAt(trip.lookAt);
      euler.current.setFromQuaternion(camera.quaternion);
      if (trip.t >= 1) {
        travel.current = null;
        lookTarget.current = null;
        // Free navigation resumes immediately on arrival (spec 55).
      }
      return;
    }

    if (!enabled) return;

    if (lookTarget.current) {
      euler.current.setFromQuaternion(camera.quaternion);
      const k = 1 - Math.exp(-LOOK_SMOOTHING * dt);
      euler.current.y += (lookTarget.current.yaw - euler.current.y) * k;
      euler.current.x += (lookTarget.current.pitch - euler.current.x) * k;
      camera.quaternion.setFromEuler(euler.current);
    }

    const k = keys.current;
    let speed = BASE_SPEED;
    if (k.ShiftLeft || k.ShiftRight) speed *= BOOST;
    if (k.AltLeft || k.AltRight) speed *= PRECISE;

    camera.getWorldDirection(forward);
    right.crossVectors(forward, up).normalize();

    const input = new THREE.Vector3();
    if (k.KeyW) input.add(forward);
    if (k.KeyS) input.sub(forward);
    if (k.KeyD) input.add(right);
    if (k.KeyA) input.sub(right);
    if (k.Space) input.add(up);                       // ascend
    if (k.ControlLeft || k.KeyC) input.sub(up);       // descend

    if (input.lengthSq() > 0) {
      input.normalize().multiplyScalar(speed);
      velocity.current.lerp(input, 1 - Math.exp(-DAMPING * dt));
    } else {
      // Exponential decay to a dead stop - "easy to stop" (spec 46).
      velocity.current.multiplyScalar(Math.exp(-DAMPING * dt));
      if (velocity.current.lengthSq() < 1e-4) velocity.current.set(0, 0, 0);
    }

    camera.position.addScaledVector(velocity.current, dt);
  });

  return null;
}

/** Click the canvas to capture the pointer and start flying. */
export function usePointerLock() {
  const { gl } = useThree();
  useEffect(() => {
    const canvas = gl.domElement;
    const onClick = () => {
      if (document.pointerLockElement !== canvas) {
        void canvas.requestPointerLock();
      }
    };
    canvas.addEventListener("click", onClick);
    return () => canvas.removeEventListener("click", onClick);
  }, [gl]);
}
