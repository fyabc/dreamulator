import { create } from 'zustand'

/** Experimental-features flag — gates features still under development
 *  (currently the UCC climate layer and the cell inspector's climate
 *  descriptor section).  Persisted so it survives a reload; default off. */
const STORAGE_KEY = 'dreamulator-experimental'

function initialExperimental(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

interface ExperimentalState {
  experimental: boolean
  setExperimental: (on: boolean) => void
}

export const useExperimentalStore = create<ExperimentalState>((set) => ({
  experimental: initialExperimental(),
  setExperimental: (on) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(on))
    } catch {
      /* localStorage unavailable (private window) — non-fatal */
    }
    set({ experimental: on })
  },
}))
