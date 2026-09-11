# Archived: the 3D Trading Universe

The React Three Fiber scene that rendered sectors as spiral galaxies, subsectors
as constellations and stocks as glowing stars (WASD flight, crosshair picking,
bloom, dust lanes). Retired in favour of the HUD interface because it was too
heavy on modest GPUs and too colourful for daily use.

Kept for reference; not compiled. To revive it: restore `three`,
`@react-three/fiber`, `@react-three/drei`, `postprocessing`,
`@react-three/postprocessing` and `@types/three` to `frontend/package.json`,
move `scene-src/` back to `frontend/universe/`, and mount `UniverseScene` on a
route. The backend still serves the layout payload at `/api/universe`.
