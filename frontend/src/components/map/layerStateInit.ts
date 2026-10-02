/**
 * layerStateInit — build the initial per-layer opacity state.
 *
 * Kept out of MapLayerPanel.tsx (a pure component file) so the react-refresh
 * rule stays clean; both viewer pages use this for their `useState<LayerState>`
 * lazy initialisers.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'
import { LAYER_HELP } from './helpContent'
import type { LayerState } from './MapLayerPanel'

type LayerOpacities = Record<ColorMode, number>

/** Default opacities: terrain base + coastline overlay, everything else off. */
const DEFAULT_LAYER_OPACITIES: LayerOpacities = {
  terrain: 1, landsea: 0, plates: 0, boundaries: 0, coastlines: 1, rivers: 0,
  koppen: 0, ucc: 0, currents: 0, winds: 0, biomes: 0, npp: 0, domesticable: 0,
  soil: 0, provinces: 0, temperature: 0, precipitation: 0, temperatureError: 0,
  precipitationError: 0, pressureError: 0, windError: 0, currentError: 0,
  pressure: 0, slp: 0, habitable: 0, agriculture: 0, flow: 0,
}

/** True when the layer kind participates in a single-slot (radio) UI. */
function isRadioKind(kind: string): boolean {
  return kind === 'base' || kind === 'thematic'
}

/**
 * Initial layer state from the `?layer=<id>` URL param (shareable deep link /
 * automated reproduction): the named layer is switched on at its default
 * opacity, honouring the same slot semantics as a click in the panel
 * (selecting a base/thematic layer switches the default terrain base off).
 * Dev-only / experimental / monthly-only layers and earth-only layers on
 * non-earth worlds are ignored (fall back to defaults) — the param is a
 * one-shot nudge, never written back to the URL.
 */
export function initialLayerState(layerParam: string | null, isEarth: boolean): LayerState {
  const layers: LayerOpacities = { ...DEFAULT_LAYER_OPACITIES }
  const entry = layerParam
    ? LAYER_HELP.find(
        (l) => l.id === layerParam &&
          !l.devOnly && !l.experimentalOnly && !l.monthlyOnly &&
          (!l.earthOnly || isEarth),
      )
    : undefined
  if (entry) {
    layers[entry.id] = entry.defaultOpacity > 0 ? entry.defaultOpacity : entry.kind === 'base' ? 1 : 0.85
    if (isRadioKind(entry.kind)) {
      for (const other of LAYER_HELP) {
        if (other.kind === entry.kind && other.id !== entry.id) layers[other.id] = 0
      }
    }
  }
  return { layers }
}
