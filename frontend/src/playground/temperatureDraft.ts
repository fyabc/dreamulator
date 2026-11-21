export const GRID_W = 180
export const GRID_H = 90
export const MODEL_JANUARY_INDEX = 10
export const maxTemperatureDrafts = 24

export const EARTH_PARAMS = {
  luminosity: 1, distanceAu: 1, albedo: 0.306, greenhouseK: 33, tiltDeg: 23.44,
  yearDays: 365.25, rotationDays: 1, seaLevelM: 0, elevMinM: -11000, elevMaxM: 9000,
  variableLapse: true,
}

export type PlanetParams = typeof EARTH_PARAMS
export type TemperatureOrigin = { world: string; planet: string; branch: string | null }
export type TemperatureDraft = Omit<TemperatureOrigin, 'world'> & {
  id: string
  source: string
  defaults: boolean
  updatedAt: number
  params: PlanetParams
  grid: Blob
}

export function isTemperatureParams(value: unknown): value is PlanetParams {
  if (!value || typeof value !== 'object') return false
  const params = value as PlanetParams
  return Object.keys(EARTH_PARAMS).every(key => key === 'variableLapse'
    ? typeof params.variableLapse === 'boolean' : Number.isFinite(params[key as keyof PlanetParams]))
    && params.luminosity >= 0 && params.distanceAu >= 0.001
    && params.albedo >= 0 && params.albedo <= 1 && params.greenhouseK >= 0
    && params.tiltDeg >= 0 && params.tiltDeg <= 90 && params.yearDays >= 0.1
    && params.rotationDays >= 0.01 && params.elevMinM < params.elevMaxM
}

type TrialMapView = { kind: 'map' | 'globe'; search: URLSearchParams }

const mapSearchKeys = ['window', 'layer', 'monthly', 'play', 'terrain', 'particles', 'sun', 'season', 'night', 'spin', 'zoomPreview']

function trialMapSearch(source: URLSearchParams) {
  const result = new URLSearchParams()
  for (const key of mapSearchKeys) {
    const value = source.get(key)
    if (value !== null) result.set(key, value)
  }
  return result
}

export function temperatureTrialPath(origin: TemperatureOrigin, draft?: string, view?: TrialMapView) {
  const search = new URLSearchParams({ world: origin.world, planet: origin.planet })
  if (origin.branch) search.set('branch', origin.branch)
  if (draft) search.set('draft', draft)
  if (view) {
    search.set('from', view.kind)
    const mapSearch = trialMapSearch(view.search).toString()
    if (mapSearch) search.set('mapView', mapSearch)
  }
  return `/playground?${search}`
}

export function temperatureTrialMapPath({ world, planet, branch }: TemperatureOrigin) {
  const search = new URLSearchParams({ trial: 'climate' })
  if (branch) search.set('branch', branch)
  return `/worlds/${encodeURIComponent(world)}/map/${encodeURIComponent(planet)}?${search}`
}

export function temperatureTrialReturnPath({ world, planet, branch }: TemperatureOrigin, trial: URLSearchParams) {
  if (!world || !planet) return '/help'
  const from = trial.get('from')
  const view = from === 'map' || from === 'globe' ? from : null
  const search = view ? trialMapSearch(new URLSearchParams(trial.get('mapView') ?? '')) : new URLSearchParams({ tab: 'climate', planet })
  if (branch) search.set('branch', branch)
  const path = `/worlds/${encodeURIComponent(world)}${view ? `/${view}/${encodeURIComponent(planet)}` : ''}`
  return search.size ? `${path}?${search}` : path
}

const isIdentifier = (value: unknown): value is string => typeof value === 'string' && /^[\w.-]{1,100}$/.test(value)

export async function readTemperatureGrid(grid: Blob) {
  if (grid.size !== GRID_W * GRID_H * 4) throw new Error('Invalid temperature draft grid size')
  const values = new Float32Array(await grid.arrayBuffer())
  if (!values.every(value => Number.isFinite(value) && value >= 0 && value <= 1)) throw new Error('Invalid temperature draft grid')
  return values
}

export async function restoreTemperatureDraft(value: unknown, id: string, grid: Blob): Promise<TemperatureDraft> {
  const draft = value as Partial<TemperatureDraft> | null
  if (!draft || !isIdentifier(draft.planet) || (draft.branch !== null && !isIdentifier(draft.branch)) ||
      !isTemperatureParams(draft.params) || typeof draft.source !== 'string' || !draft.source.trim() || draft.source.length > 200 ||
      typeof draft.defaults !== 'boolean' || typeof draft.updatedAt !== 'number' || !Number.isFinite(new Date(draft.updatedAt).getTime())) {
    throw new Error('Invalid temperature draft metadata')
  }
  await readTemperatureGrid(grid)
  const { planet, branch, source, defaults, updatedAt, params } = draft
  return { id, planet, branch, source, defaults, updatedAt, params, grid }
}
