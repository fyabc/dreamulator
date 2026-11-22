import type { ClimateTrialForcing, ClimateTrialJob, ClimateTrialProducts, SavedBrowserEbm } from '../api/climateTrials'
import type { MapMetadata } from '../viewers/map/types'
import { composeSplitMesh, isSplitFields, isSplitGeometry } from '../api/meshColumns'
import { decodeMonthlyClimate } from '../api/monthlyClimate'
import { decodeYearlyClimate } from '../api/yearlyClimate'
import type { BrowserEbmReply, BrowserEbmRequest } from './ebm.worker'

interface BrowserJob {
  job: ClimateTrialJob
  startedAt: number
  stageAt: number
  products?: ClimateTrialProducts
  archive?: Omit<SavedBrowserEbm['assets'], 'elevation'>
  inputs?: SavedBrowserEbm['metadata']['inputs']
  scope: { world: string; planet: string; branch: string | null }
}

let nextId = 0
const jobs = new Map<string, BrowserJob>()

export function startBrowserEbm(request: BrowserEbmRequest, signal: AbortSignal, scope: BrowserJob['scope']): ClimateTrialJob {
  if (signal.aborted) throw new DOMException('Cancelled', 'AbortError')
  if (Array.from(jobs.values()).some(({ job }) => job.state === 'running')) throw new Error('trial_busy')
  const worker = new Worker(new URL('./ebm.worker.ts', import.meta.url), { type: 'module' })
  const id = `browser-ebm-${++nextId}`
  const job: ClimateTrialJob = {
    id, state: 'running', stage: 'browserRuntime', cells: request.cells, months_done: null,
    months_total: null, moisture_pass: null, elapsed_seconds: 0, stage_seconds: 0, error: null,
    ...(typeof request.mesh !== 'string' && { builds_mesh: true }),
  }
  const startedAt = performance.now()
  const entry: BrowserJob = { job, startedAt, stageAt: startedAt, scope }
  jobs.set(id, entry)
  signal.addEventListener('abort', () => {
    worker.terminate()
    jobs.delete(id)
  }, { once: true })

  const finish = (error?: string, detail?: string) => {
    worker.terminate()
    const now = performance.now()
    Object.assign(job, { state: error ? 'failed' : 'succeeded', error: error ?? null,
      error_detail: detail, elapsed_seconds: (now - startedAt) / 1000,
      stage_seconds: (now - entry.stageAt) / 1000 })
  }
  worker.onerror = event => finish('browser_runtime', event.message)
  worker.onmessageerror = () => finish('browser_products')
  worker.onmessage = ({ data }: MessageEvent<BrowserEbmReply>) => {
    if ('error' in data) {
      finish(data.error, data.detail)
    } else if ('progress' in data) {
      if (job.stage !== data.progress.stage) {
        entry.stageAt = performance.now()
        Object.assign(job, { months_done: null, months_total: null, moisture_pass: null })
      }
      const { cells, ...progress } = data.progress
      Object.assign(job, progress, { cells: cells ?? job.cells })
    } else {
      try {
        const { geometry, fields, monthly, yearly, geometryBytes, fieldBytes, terrain, inputs } = data.products
        const mesh = isSplitGeometry(geometry) && isSplitFields(fields) ? composeSplitMesh(geometry, fields) : null
        const months = decodeMonthlyClimate(monthly)
        const years = decodeYearlyClimate(yearly)
        if (!mesh || [mesh.cells.length, months.numCells, years.numCells].some(cells => cells !== request.cells)) {
          throw new Error('Invalid climate trial grid')
        }
        entry.products = { mesh, monthly: months, yearly: years }
        entry.archive = { geometry: new Blob([geometryBytes]), fields: new Blob([fieldBytes]),
          monthly: new Blob([monthly]), yearly: new Blob([yearly]), ...(terrain && { terrain: new Blob([terrain]) }) }
        entry.inputs = inputs
        finish()
      } catch (cause) {
        finish('browser_products', cause instanceof Error ? cause.message : String(cause))
      }
    }
  }
  worker.postMessage(request)
  return { ...job }
}

export function getBrowserEbm(id: string): ClimateTrialJob {
  const entry = jobs.get(id)
  if (!entry) throw new Error('browser_expired')
  if (entry.job.state !== 'running') return { ...entry.job }
  const now = performance.now()
  return { ...entry.job, elapsed_seconds: (now - entry.startedAt) / 1000, stage_seconds: (now - entry.stageAt) / 1000 }
}

export function getBrowserEbmProducts(id: string): ClimateTrialProducts {
  const products = jobs.get(id)?.products
  if (!products) throw new Error('browser_expired')
  return products
}

export async function saveBrowserEbm(id: string, scope: BrowserJob['scope'], loadSurface: () => Promise<[MapMetadata, Blob]>) {
  const entry = jobs.get(id)
  if (!entry?.archive || !entry.inputs || entry.scope.world !== scope.world ||
      entry.scope.planet !== scope.planet || entry.scope.branch !== scope.branch || !entry.job.cells) throw new Error('browser_expired')
  const [surface, elevation] = await loadSurface().catch(() => { throw new Error('trial_surface_missing') })
  const { saveBrowserClimateResult } = await import('../projects/projectStore')
  const result: SavedBrowserEbm = {
    metadata: { id: crypto.randomUUID(), format: 1, solver: 'ebm', planet: scope.planet,
      branch: scope.branch, saved_at: new Date().toISOString(), cells: entry.job.cells,
      elapsed_seconds: entry.job.elapsed_seconds, inputs: entry.inputs, surface },
    assets: { ...entry.archive, elevation },
  }
  await saveBrowserClimateResult(scope.world, result)
  return result.metadata
}

export type BrowserEbmSource = Pick<BrowserEbmRequest, 'config' | 'cells' | 'mesh'> & { forcing: ClimateTrialForcing }
