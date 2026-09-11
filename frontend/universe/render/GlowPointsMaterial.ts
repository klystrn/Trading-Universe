/** Additive point-sprite material with per-point size, colour and pulse.
 *
 *  The one custom shader in the scene, and the one that earns it: PointsMaterial
 *  allows a single size for all points, but a star field needs each star to
 *  carry its own size (market cap), brightness (price movement) and pulse
 *  (signal). Sizes attenuate with distance and are clamped so a star flown up
 *  to never becomes a screen-filling blob.
 */

import * as THREE from "three";

export function createGlowPointsMaterial(map: THREE.Texture, options?: {
  sizeScale?: number;
  minSize?: number;
  maxSize?: number;
  opacity?: number;
}): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: {
      uMap: { value: map },
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uSizeScale: { value: options?.sizeScale ?? 420 },
      uMinSize: { value: options?.minSize ?? 1.2 },
      uMaxSize: { value: options?.maxSize ?? 110 },
      uOpacity: { value: options?.opacity ?? 1 },
    },
    vertexShader: /* glsl */ `
      attribute float aSize;
      attribute vec3 aColor;
      attribute float aPulse;
      uniform float uTime;
      uniform float uPixelRatio;
      uniform float uSizeScale;
      uniform float uMinSize;
      uniform float uMaxSize;
      varying vec3 vColor;
      varying float vPulse;
      void main() {
        vColor = aColor;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float pulse = 1.0 + aPulse * 0.45 * (0.5 + 0.5 * sin(uTime * 2.2 + position.x * 0.31 + position.z * 0.17));
        vPulse = aPulse;
        float size = aSize * pulse * uPixelRatio * (uSizeScale / max(-mv.z, 1.0));
        gl_PointSize = clamp(size, uMinSize, uMaxSize);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform sampler2D uMap;
      uniform float uOpacity;
      varying vec3 vColor;
      varying float vPulse;
      void main() {
        float a = texture2D(uMap, gl_PointCoord).a;
        // A signalling star gets a slightly hotter centre.
        vec3 c = vColor * (1.0 + vPulse * 0.4);
        gl_FragColor = vec4(c * a * uOpacity, a * uOpacity);
      }
    `,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
  });
}
