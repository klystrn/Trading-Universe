/** HUD state: the conversation, voice status, and connection. */

import { create } from "zustand";

export interface Exchange {
  id: string;
  role: "you" | "tu";
  text: string;
  at: number;
}

interface HudState {
  transcript: Exchange[];
  listening: boolean;
  interim: string;
  speaking: boolean;
  muted: boolean;
  connected: boolean;
  busy: boolean;

  say: (role: Exchange["role"], text: string) => void;
  setListening: (v: boolean) => void;
  setInterim: (v: string) => void;
  setSpeaking: (v: boolean) => void;
  toggleMuted: () => void;
  setConnected: (v: boolean) => void;
  setBusy: (v: boolean) => void;
  clear: () => void;
}

export const useHudStore = create<HudState>((set) => ({
  transcript: [],
  listening: false,
  interim: "",
  speaking: false,
  muted: false,
  connected: false,
  busy: false,

  say: (role, text) =>
    set((s) => ({
      transcript: [...s.transcript.slice(-11), { id: `${Date.now()}-${role}`, role, text, at: Date.now() }],
    })),
  setListening: (listening) => set({ listening }),
  setInterim: (interim) => set({ interim }),
  setSpeaking: (speaking) => set({ speaking }),
  toggleMuted: () => set((s) => ({ muted: !s.muted })),
  setConnected: (connected) => set({ connected }),
  setBusy: (busy) => set({ busy }),
  clear: () => set({ transcript: [] }),
}));
