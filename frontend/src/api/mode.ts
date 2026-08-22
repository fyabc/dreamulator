/**
 * Deployment mode detection.
 *
 * When VITE_STATIC_MODE is 'true', the frontend reads from pre-exported
 * static JSON files (for GitHub Pages). Otherwise it calls the FastAPI backend.
 */

export const isStaticMode = (): boolean =>
  import.meta.env.VITE_STATIC_MODE === 'true'
