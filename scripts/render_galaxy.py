"""Render the face-on spiral galaxy the HUD rotates behind its readouts.

Run once; the output is committed to frontend/public. Deterministic for a
given seed. The browser draws this single image with a 2D affine transform
(rotate in the disc plane, squash for inclination), so the galaxy costs one
drawImage per frame instead of hundreds of thousands of particles.

    pip install numpy scipy pillow
    python scripts/render_galaxy.py

The arm geometry is written to galaxy.json so the frontend can place stock
stars on the same spiral the image shows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, zoom

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public"

# Geometry, in units of the image half-width (r = 1 is the image edge).
ARMS = 2
PITCH_DEG = 17.0        # pitch angle of the logarithmic spiral
ARM_R0 = 0.07           # radius where the arms start from the bar ends
DISK_SCALE = 0.28       # exponential disc scale length
BULGE_SCALE = 0.045
ARM_PHASE = 0.0


def noise(n: int, feature: float, rng: np.random.Generator, octaves: int = 1) -> np.ndarray:
    """Smooth fractal noise with unit standard deviation.

    ``feature`` is the size of the largest blobs as a fraction of the image.
    """
    out = np.zeros((n, n), np.float32)
    amp, total, f = 1.0, 0.0, feature
    for _ in range(octaves):
        grid = max(4, int(round(2.0 / f)))
        field = rng.standard_normal((grid + 3, grid + 3)).astype(np.float32)
        field = zoom(field, n / grid, order=3)[:n, :n]
        field = (field - field.mean()) / (field.std() + 1e-6)
        out += amp * field
        total += amp * amp
        amp *= 0.6
        f /= 2.0
    return out / np.sqrt(total)


def spiral_phase(r: np.ndarray, theta: np.ndarray) -> np.ndarray:
    k = 1.0 / np.tan(np.radians(PITCH_DEG))
    return theta - k * np.log(np.maximum(r, 1e-3) / ARM_R0) - ARM_PHASE


def arm_profile(phase: np.ndarray, width: float) -> np.ndarray:
    """1 on an arm's ridge, falling off with angular distance (ARMS-fold)."""
    d = np.angle(np.exp(1j * ARMS * phase)) / ARMS  # wrapped distance to nearest arm
    return np.exp(-0.5 * (d / width) ** 2)


def render(size: int, seed: int) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[-1:1:size * 1j, -1:1:size * 1j].astype(np.float32)
    r = np.hypot(x, y)
    theta = np.arctan2(y, x)
    px = size / 2048  # pixel scale relative to the reference size

    # Turbulence: bends the arms, breaks them into segments, threads the dust.
    warp = noise(size, 0.35, rng, octaves=3)
    seg = noise(size, 0.18, rng, octaves=3)
    clump = noise(size, 0.028, rng, octaves=4)
    fine = noise(size, 0.02, rng, octaves=3)

    phase = spiral_phase(r, theta + 0.16 * warp * np.clip(r * 4, 0, 1))
    t = np.clip((r - 0.06) / 0.16, 0, 1)
    arm_on = t * t * (3 - 2 * t)  # smoothstep: no visible ring where arms begin
    arm_fade = np.exp(-(r / 0.70) ** 4)

    broad = arm_profile(phase, 0.38)
    ridge = arm_profile(phase + 0.06 * fine, 0.15)
    # Secondary, fainter branches between the main arms (M101-style spurs).
    branch = arm_profile(spiral_phase(r, theta + 0.9) * 1.0 + 0.4 * warp, 0.12)
    branch *= np.clip((r - 0.22) / 0.15, 0, 1) * 0.45

    segment = np.exp(0.55 * seg)                       # arms brighten and break up
    arms = (broad * 0.7 + ridge * 0.6 + branch) * arm_on * arm_fade * segment

    disk = np.exp(-r / DISK_SCALE)
    bulge = np.exp(-((r / BULGE_SCALE) ** 0.8))
    ang = 0.6
    bx = x * np.cos(ang) + y * np.sin(ang)
    by = -x * np.sin(ang) + y * np.cos(ang)
    bar = np.exp(-(np.hypot(bx, by * 3.0) / 0.085) ** 1.6) * 0.5

    old = disk * (0.42 + 0.5 * arms) + bulge * 2.6 + bar
    young = disk ** 0.55 * (ridge + branch) * arm_on * arm_fade * segment
    young *= np.clip(np.exp(0.7 * clump) - 0.45, 0, None) * np.clip(r / 0.14, 0, 1) * 0.9

    # Dust: thin dark lanes on the concave side of each arm, shredded by noise,
    # plus feathery spurs crossing the arms.
    lane = arm_profile(phase + 0.27 + 0.05 * clump, 0.07)
    spur = arm_profile(spiral_phase(r, theta) - 0.25 + 0.25 * fine, 0.08) * 0.4
    dust = (lane + spur * np.clip(arms, 0, 1)) * np.clip(0.55 + 0.6 * fine + 0.4 * clump, 0, None)
    dust += 0.10 * np.clip(fine - 0.6, 0, None) * disk ** 0.3 * arm_on   # wisps of interarm dust
    dust *= np.clip((r - 0.07) / 0.16, 0, 1) ** 1.5 * np.exp(-(r / 0.6) ** 4)
    # Soften by a couple of pixels so no lane edge reads as a drawn line.
    tau = 2.1 * gaussian_filter(dust, 1.6 * px * 2)

    c_old = np.array([1.00, 0.87, 0.70], np.float32)
    c_bulge = np.array([1.00, 0.82, 0.60], np.float32)
    c_young = np.array([0.60, 0.72, 1.00], np.float32)
    c_hii = np.array([1.00, 0.55, 0.72], np.float32)
    img = old[..., None] * c_old + young[..., None] * c_young * 1.1
    img += (bulge * 1.2)[..., None] * c_bulge

    # Star-forming knots and young clusters, strung along the arm ridges.
    def scatter(count: int, weight: np.ndarray, sigma: float, lo: float, hi: float) -> np.ndarray:
        layer = np.zeros((size, size), np.float32)
        ys = rng.integers(0, size, count * 8)
        xs = rng.integers(0, size, count * 8)
        w = weight[ys, xs]
        keep = rng.uniform(0, w.max() + 1e-6, len(w)) < w
        ys, xs = ys[keep][:count], xs[keep][:count]
        layer[ys, xs] = rng.uniform(lo, hi, len(ys)).astype(np.float32)
        return gaussian_filter(layer, sigma * px * 2)

    knot_w = (ridge + branch) * arm_on * arm_fade * np.clip(np.exp(clump) - 0.6, 0, None) * np.clip(r / 0.1, 0, 1)
    hii = scatter(int(2200 * px * 2), knot_w, 0.8, 0.6, 4.0)
    clusters = scatter(int(9000 * px * 2), knot_w, 0.45, 0.4, 2.2)
    img += hii[..., None] * c_hii * 2.4 + clusters[..., None] * c_young * 3.0

    # Dust extinction reddens the light behind it.
    ext = np.exp(-tau[..., None] * np.array([0.72, 0.92, 1.18], np.float32))
    img *= ext

    # Resolved field stars inside the disc.
    stars = np.zeros((size, size, 3), np.float32)
    n = int(400000 * px * px * 4)
    ys, xs = rng.integers(0, size, n), rng.integers(0, size, n)
    density = (old + 2.0 * young)[ys, xs]
    keep = rng.uniform(0, np.percentile(density, 99.5), n) < density
    ys, xs = ys[keep], xs[keep]
    mags = (rng.pareto(2.4, len(ys)).astype(np.float32) * 0.12 + 0.03)
    is_young = rng.uniform(0, 1, len(ys)) < young[ys, xs] / (young[ys, xs] + old[ys, xs] + 1e-6)
    colour = np.where(is_young[:, None], c_young, c_old)
    np.add.at(stars, (ys, xs), mags[:, None] * colour)
    stars *= ext
    img += gaussian_filter(stars, (0.55 * px * 2, 0.55 * px * 2, 0))

    # Bloom around the core and brightest knots, then a faint halo.
    lum = img.mean(axis=2)
    bloom = gaussian_filter(np.clip(lum - 0.5, 0, None), 18 * px * 2)
    img += bloom[..., None] * np.array([1.0, 0.9, 0.78], np.float32) * 0.6
    img += (np.exp(-r / 0.45) * 0.035)[..., None] * np.array([0.8, 0.82, 1.0], np.float32)

    # asinh stretch, as astronomers do, with mild desaturation.
    img = np.arcsinh(img * 3.0) / np.arcsinh(3.0 * 3.4)
    grey = img.mean(axis=2, keepdims=True)
    img = grey + (img - grey) * 0.9
    rim = np.clip((1.0 - r) / 0.15, 0, 1) ** 2
    img = np.clip(img * rim[..., None], 0, 1)

    meta = {
        "arms": ARMS,
        "pitch_deg": PITCH_DEG,
        "arm_r0": ARM_R0,
        "arm_phase": ARM_PHASE,
        "disk_scale": DISK_SCALE,
        "arm_r_min": 0.10,
        "arm_r_max": 0.66,
        "note": "radii are fractions of the image half-width; theta=atan2(y, x) "
                "with +y pointing down the image",
    }
    return img, meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    img, meta = render(args.size, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    rgb = (img * 255 + 0.5).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(args.out / "galaxy.webp", quality=88, method=6)
    (args.out / "galaxy.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {args.out / 'galaxy.webp'} ({(args.out / 'galaxy.webp').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
