import { create } from 'zustand'

/** Developer-mode flag — gates diagnostic layers (ΔT/ΔP error heatmaps) that
 *  are useful to engine authors but noise for end users.  Persisted so it
 *  survives a reload; default off. */
const STORAGE_KEY = 'dreamulator-dev-mode'

function initialDevMode(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

interface DevModeState {
  devMode: boolean
  setDevMode: (on: boolean) => void
}

export const useDevModeStore = create<DevModeState>((set) => ({
  devMode: initialDevMode(),
  setDevMode: (on) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(on))
    } catch {
      /* localStorage unavailable (private window) — non-fatal */
    }
    set({ devMode: on })
  },
}))
