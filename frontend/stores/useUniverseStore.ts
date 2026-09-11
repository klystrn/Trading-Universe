/** Render state.
 *
 *  Kept separate from trading state on purpose (spec 78): this store updates at
 *  the websocket cadence and is read inside the render loop, so anything that
 *  would cause a React re-render per frame belongs here and nowhere else.
 */

import { create } from "zustand";
import type {
  FlowArc, UniverseEntity, UniverseFilter, UniversePayload,
  UniverseSector, UniverseSubsector,
} from "@/lib/types";

interface UniverseState {
  entities: UniverseEntity[];
  entityById: Map<string, UniverseEntity>;
  sectors: UniverseSector[];
  sectorById: Map<string, UniverseSector>;
  subsectors: UniverseSubsector[];
  flows: FlowArc[];
  loaded: boolean;
  connected: boolean;

  // Interaction
  hovered: string | null;
  selected: string | null;
  focusTarget: { position: [number, number, number]; id: string } | null;
  filter: UniverseFilter;
  showLabels: boolean;
  showFlows: boolean;
  flying: boolean;

  setPayload: (payload: UniversePayload) => void;
  setConnected: (connected: boolean) => void;
  setHovered: (id: string | null) => void;
  select: (id: string | null) => void;
  focusOn: (id: string) => void;
  clearFocus: () => void;
  setFilter: (filter: UniverseFilter) => void;
  toggleLabels: () => void;
  toggleFlows: () => void;
  setFlying: (flying: boolean) => void;
}

export const useUniverseStore = create<UniverseState>((set, get) => ({
  entities: [],
  entityById: new Map(),
  sectors: [],
  sectorById: new Map(),
  subsectors: [],
  flows: [],
  loaded: false,
  connected: false,

  hovered: null,
  selected: null,
  focusTarget: null,
  filter: "MARKET",
  showLabels: true,
  showFlows: true,
  flying: false,

  setPayload: (payload) =>
    set({
      entities: payload.entities,
      entityById: new Map(payload.entities.map((e) => [e.id, e])),
      sectors: payload.sectors,
      sectorById: new Map(payload.sectors.map((s) => [s.id, s])),
      subsectors: payload.subsectors,
      flows: payload.flows,
      loaded: true,
    }),

  setConnected: (connected) => set({ connected }),
  setHovered: (hovered) => set({ hovered }),
  select: (selected) => set({ selected }),

  focusOn: (id) => {
    const { entityById, sectorById, subsectors } = get();
    const entity = entityById.get(id);
    if (entity) {
      set({ focusTarget: { position: entity.position, id }, selected: id });
      return;
    }
    const sector = sectorById.get(id);
    if (sector) {
      set({ focusTarget: { position: sector.position, id }, selected: id });
      return;
    }
    const subsector = subsectors.find((s) => s.id === id);
    if (subsector) {
      set({ focusTarget: { position: subsector.position, id }, selected: id });
    }
  },

  clearFocus: () => set({ focusTarget: null }),
  setFilter: (filter) => set({ filter }),
  toggleLabels: () => set((s) => ({ showLabels: !s.showLabels })),
  toggleFlows: () => set((s) => ({ showFlows: !s.showFlows })),
  setFlying: (flying) => set({ flying }),
}));

/** Emphasis for one entity under the active filter, 0-1.
 *
 *  Filters are emphasis LAYERS over a single scene, never separate scenes
 *  (spec 56), so this dims rather than removes.
 */
export function entityEmphasis(
  entity: UniverseEntity,
  filter: UniverseFilter,
): number {
  switch (filter) {
    case "SIGNALS":
      return entity.signal?.active ? 1 : 0.12;
    case "POLITICAL":
      return entity.political?.active ? 1 : 0.1;
    case "PORTFOLIO":
      return entity.portfolio?.held ? 1 : 0.1;
    case "WATCHLIST":
      return entity.watchlist ? 1 : 0.1;
    case "SECTORS":
      return 0.55;
    case "MARKET":
    default:
      return 1;
  }
}
