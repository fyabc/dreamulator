import { create } from 'zustand'

interface WorldState {
  currentWorld: string | null
  setCurrentWorld: (name: string | null) => void
}

export const useWorldStore = create<WorldState>((set) => ({
  currentWorld: null,
  setCurrentWorld: (name) => set({ currentWorld: name }),
}))
