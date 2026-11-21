import { decode } from '@msgpack/msgpack'
import type { ClimateTrialForcing, ClimateTrialJob } from '../api/climateTrials'

export interface BrowserEbmRequest {
  runtime: string
  solver: string
  mesh: string
  cells: number
  forcing: Partial<ClimateTrialForcing>
  config: Record<string, unknown>
}

type Progress = Pick<ClimateTrialJob, 'stage' | 'cells' | 'months_done' | 'months_total' | 'moisture_pass'>

export type BrowserEbmReply = { progress: Partial<Progress> & Pick<Progress, 'stage'> }
  | { error: string; detail: string }
  | { products: { geometry: unknown; fields: unknown; monthly: ArrayBuffer; yearly: ArrayBuffer } }

const send = self.postMessage.bind(self) as (message: BrowserEbmReply, transfer?: Transferable[]) => void

async function resource(url: string) {
  const response = await fetch(url, { cache: 'no-cache' })
  if (!response.ok) throw new Error(`${response.status} ${url}`)
  return new Uint8Array(await response.arrayBuffer())
}

function aligned(value: unknown, buffers: Transferable[]): unknown {
  if (value instanceof Uint8Array) {
    const bytes = new Uint8Array(value)
    buffers.push(bytes.buffer)
    return bytes
  }
  if (Array.isArray(value)) return value.map(item => aligned(item, buffers))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, aligned(item, buffers)]))
  }
  return value
}

self.onmessage = async ({ data: request }: MessageEvent<BrowserEbmRequest>) => {
  let error = 'browser_runtime'
  try {
    send({ progress: { stage: 'browserRuntime', cells: request.cells } })
    const { loadPyodide } = await import(/* @vite-ignore */ `${request.runtime}pyodide.mjs`) as typeof import('pyodide')
    const py = await loadPyodide({ indexURL: request.runtime })
    await py.loadPackage(__EBM_PACKAGES__)
    py.FS.mkdir('/solver')
    py.FS.mkdir('/result')
    py.unpackArchive(await resource(request.solver), 'zip', { extractDir: '/solver' })

    error = 'browser_source'
    send({ progress: { stage: 'reading' } })
    py.FS.writeFile('/mesh.bin', await resource(request.mesh))
    py.globals.set('trial_request', JSON.stringify({ config: request.config, forcing: request.forcing }))
    py.globals.set('report_progress', (json: string) => send({ progress: JSON.parse(json) as Progress }))
    error = 'browser_run'
    await py.runPythonAsync(`
import json, sys
from pathlib import Path
sys.path.insert(0, '/solver')
from dreamulator.climate_trial import BROWSER_TRIAL_MAX_CELLS, TrialForcing, TrialSource, compute_trial
from dreamulator.map.pipeline_types import TerrainPipelineConfig
request = json.loads(trial_request)
compute_trial(
    TrialSource(TerrainPipelineConfig.from_dict(request['config']), Path('/mesh.bin')),
    TrialForcing.model_validate(request['forcing']), Path('/result'),
    BROWSER_TRIAL_MAX_CELLS * 32 * 1024,
    diagnostic_pngs=False, on_progress=lambda progress: report_progress(progress.model_dump_json()),
)
`)

    error = 'browser_products'
    send({ progress: { stage: 'loading' } })
    const split = async (name: string) => {
      const compressed = new Uint8Array(py.FS.readFile(`/result/${name}`))
      const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))
      return decode(await new Response(stream).arrayBuffer())
    }
    const buffers: Transferable[] = []
    const geometry = aligned(await split('mesh_geometry.msgpack.gz'), buffers)
    const fields = aligned(await split('mesh_fields.msgpack.gz'), buffers)
    const monthly = new Uint8Array(py.FS.readFile('/result/climate_monthly.msgpack')).buffer
    const yearly = new Uint8Array(py.FS.readFile('/result/climate_yearly.msgpack')).buffer
    send({ products: { geometry, fields, monthly, yearly } }, [...buffers, monthly, yearly])
  } catch (cause) {
    send({ error, detail: cause instanceof Error ? cause.message : String(cause) })
  }
}
