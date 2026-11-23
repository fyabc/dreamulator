import { decode } from '@msgpack/msgpack'
import type { ClimateTrialForcing, ClimateTrialJob, SavedClimateTrial } from '../api/climateTrials'

export type BrowserHeightmapMapping =
  | { mode: 'range'; min_m: number; max_m: number; sea_level_m: number }
  | { mode: 'threshold'; sea_level: number; max_m: number; seafloor_m: number
      curve: 'linear' | 'gamma'; gamma: number }

export interface BrowserEbmRequest {
  runtime: string
  solver: string
  mesh: string | { image: Blob; name: string; sha256: string; mapping: BrowserHeightmapMapping }
  cells: number
  forcing: Partial<ClimateTrialForcing>
  config: Record<string, unknown>
}

type Progress = Pick<ClimateTrialJob, 'stage' | 'cells' | 'months_done' | 'months_total' | 'moisture_pass'>

export type BrowserEbmReply = { progress: Partial<Progress> & Pick<Progress, 'stage'> }
  | { error: string; detail: string }
  | { products: { geometry: unknown; fields: unknown; monthly: ArrayBuffer; yearly: ArrayBuffer;
      geometryBytes: ArrayBuffer; fieldBytes: ArrayBuffer; terrain?: ArrayBuffer; inputs: SavedClimateTrial['inputs'] } }

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
    py.globals.set('trial_request', JSON.stringify({ config: request.config, forcing: request.forcing }))
    py.globals.set('report_progress', (json: string) => send({ progress: JSON.parse(json) as Progress }))
    if (typeof request.mesh === 'string') {
      send({ progress: { stage: 'reading' } })
      py.FS.writeFile('/mesh.bin', await resource(request.mesh))
    } else {
      send({ progress: { stage: 'browserMesh' } })
      py.FS.writeFile('/elevation.png', new Uint8Array(await request.mesh.image.arrayBuffer()))
      py.globals.set('elevation_request', JSON.stringify({ name: request.mesh.name, mapping: request.mesh.mapping }))
      await py.runPythonAsync(`
import json, sys
from pathlib import Path
sys.path.insert(0, '/solver')
from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.elevation_input import sample_elevation_import
from dreamulator.map.export import save_cvt_mesh
from dreamulator.map.importer import import_heightmap_metres
from dreamulator.map.models import ElevationMapping
from dreamulator.map.pipeline_types import TerrainPipelineConfig
source = json.loads(elevation_request)
mapping = ElevationMapping.model_validate(source['mapping'])
imported = import_heightmap_metres(Path('/elevation.png').read_bytes(), mapping, filename=source['name'])
mesh = generate_cvt_mesh(TerrainPipelineConfig.from_dict(json.loads(trial_request)['config']))
sample_elevation_import(mesh, imported)
save_cvt_mesh(Path('/mesh.bin'), mesh)
del mesh, imported
Path('/elevation.png').unlink()
`)
    }
    error = 'browser_run'
    await py.runPythonAsync(`
import json, sys
from pathlib import Path
if '/solver' not in sys.path:
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
    const read = (name: string) => new Uint8Array(py.FS.readFile(`/result/${name}`)).buffer
    let terrain: ArrayBuffer | undefined
    if (typeof request.mesh !== 'string') {
      py.globals.set('native_key', request.mesh.sha256)
      await py.runPythonAsync(`
from dreamulator.map.export import MESH_FILENAME
from dreamulator.map.td_world_source import terrain_packet
result = Path('/result')
(result / 'terrain.msgpack').write_bytes(terrain_packet(result, result / MESH_FILENAME, native_key))
`)
      terrain = read('terrain.msgpack')
    }
    const split = async (compressed: ArrayBuffer) => {
      const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))
      return decode(await new Response(stream).arrayBuffer())
    }
    const buffers: Transferable[] = []
    const geometryBytes = read('mesh_geometry.msgpack.gz')
    const fieldBytes = read('mesh_fields.msgpack.gz')
    const geometry = aligned(await split(geometryBytes), buffers)
    const fields = aligned(await split(fieldBytes), buffers)
    const monthly = read('climate_monthly.msgpack')
    const yearly = read('climate_yearly.msgpack')
    const inputs = JSON.parse(py.FS.readFile('/result/inputs.json', { encoding: 'utf8' })) as SavedClimateTrial['inputs']
    send({ products: { geometry, fields, monthly, yearly, geometryBytes, fieldBytes, terrain, inputs } },
      [...buffers, monthly, yearly, geometryBytes, fieldBytes, ...(terrain ? [terrain] : [])])
  } catch (cause) {
    send({ error, detail: cause instanceof Error ? cause.message : String(cause) })
  }
}
