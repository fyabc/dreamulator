import { MathUtils, Vector3 } from 'three'
import type { ElevationSource, LocalProject } from '../../../projects/elevationProject'
import type { PackWindow } from '../../packs/packCoords'
import { encodeRegionWindow, type RegionWindow } from '../regionWindow'
import { lonLatToGlobePosition } from './globeCoords'
import { overviewCameraDistance, regionCameraDistance } from './globeScale'

export function savedGlobeRegion(project: LocalProject | null | undefined, scope: {
  world: string; planet: string; branch: string | null; radiusKm: number; selection: RegionWindow
}) {
  if (!project?.published || project.id !== scope.world) return null
  const sources = new Map(project.layers.flatMap((layer) => layer.kind === 'elevation-source' ? [[layer.id, layer] as const] : []))
  const matches = (source: ElevationSource) => {
    const { location, frame: { window } } = source
    return location?.planet === scope.planet && location.branch === scope.branch &&
      window.projection === 'azimuthal_equidistant' && window.radiusKm === scope.radiusKm && window.extentKmX === window.extentKmY &&
      encodeRegionWindow({ lat: window.centerLat, lon: window.centerLon, spanKm: window.extentKmX }) === encodeRegionWindow(scope.selection)
  }
  for (let index = project.layers.length - 1; index >= 0; index--) {
    const result = project.layers[index]
    if (result.kind !== 'elevation-result') continue
    const source = sources.get(result.sourceId)
    if (source && matches(source)) return { result, frame: source.frame }
  }
  return null
}

export function globeRegionBasis({ centerLon: lon, centerLat: lat }: PackWindow) {
  return {
    centre: new Vector3(...lonLatToGlobePosition({ lon, lat }, 1)),
    east: new Vector3(...lonLatToGlobePosition({ lon: lon + 90, lat: 0 }, 1)),
    north: new Vector3(...lonLatToGlobePosition({ lon, lat: lat + 90 }, 1)),
  }
}

export function globeRegionBlend(window: PackWindow, distance: number, fov: number, aspect: number) {
  const close = regionCameraDistance(window.extentKmX, window.radiusKm, fov, aspect)
  const far = Math.min(overviewCameraDistance(fov, aspect), 1 + 2 * (close - 1))
  return close < far ? 1 - MathUtils.smoothstep(distance, close, far) : 0
}
