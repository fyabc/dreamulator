import { elevationSource, type ElevationResult, type ElevationSource, type LocalProject } from '../../projects/elevationProject'
import type { PackWindow } from './packCoords'

export const currentBrowserRefinement = 'current-browser-refinement'

export function matchingBrowserRegionResults(project: LocalProject | null | undefined,
  location: NonNullable<ElevationSource['location']>, window: PackWindow) {
  if (!project?.published) return []
  const results: { layer: ElevationResult; source: ElevationSource }[] = []
  for (const layer of project.layers) {
    if (layer.kind !== 'elevation-result') continue
    const source = elevationSource(project.layers, layer)
    if (!source || source.location?.planet !== location.planet || source.location.branch !== location.branch) continue
    const frame = source.frame.window
    if (frame.centerLat !== window.centerLat || (frame.centerLon - window.centerLon) % 360 !== 0 ||
      frame.radiusKm !== window.radiusKm || frame.projection !== window.projection ||
      frame.extentKmX !== window.extentKmX || frame.extentKmY !== window.extentKmY) continue
    results.push({ layer, source })
  }
  return results
}
