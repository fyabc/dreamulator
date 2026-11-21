import type { PyodideInterface } from 'pyodide'
import climatePhysicsSrc from '../../../src/dreamulator/engine/climate_physics.py?raw'
import climateSeasonalitySrc from '../../../src/dreamulator/engine/climate_seasonality.py?raw'
import temperatureKernelSrc from './temperature_kernel.py?raw'

export interface KernelResult {
  annual: number[]
  monthly: number[][]
  globalMeanC: number
  annualMeanC: number
  minC: number
  maxC: number
  elapsedS: number
}

export type TemperatureRequest = {
  elevation: Float32Array | Float64Array
  params: Record<string, number | boolean>
  runtimeBase: string
}

export type TemperatureResponse =
  | { type: 'runtime-ready'; seconds: number }
  | { type: 'result'; result: KernelResult; version: string }
  | { type: 'error'; stage: 'runtime' | 'compute'; detail: string }

let runtime: PyodideInterface | undefined
let modelVersion = ''

async function loadRuntime(indexURL: string): Promise<PyodideInterface> {
  const code = new TextEncoder().encode(JSON.stringify([climatePhysicsSrc, climateSeasonalitySrc, temperatureKernelSrc]))
  modelVersion = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', code)), value => value.toString(16).padStart(2, '0')).join('')
  const { loadPyodide } = await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`) as typeof import('pyodide')
  const py = await loadPyodide({ indexURL })
  await py.loadPackage('numpy')

  for (const path of ['/engine', '/engine/dreamulator', '/engine/dreamulator/engine', '/kernel']) {
    py.FS.mkdir(path)
  }
  py.FS.writeFile('/engine/dreamulator/__init__.py', '')
  py.FS.writeFile('/engine/dreamulator/engine/__init__.py', '')
  py.FS.writeFile('/engine/dreamulator/engine/climate_physics.py', climatePhysicsSrc)
  py.FS.writeFile('/engine/dreamulator/engine/climate_seasonality.py', climateSeasonalitySrc)
  py.FS.writeFile('/kernel/temperature_kernel.py', temperatureKernelSrc)
  await py.runPythonAsync(`
import sys
sys.path.insert(0, '/engine')
sys.path.insert(0, '/kernel')
from temperature_kernel import compute_temperature
`)
  return py
}

function send(message: TemperatureResponse) {
  self.postMessage(message)
}

self.onmessage = async ({ data }: MessageEvent<TemperatureRequest>) => {
  try {
    if (!runtime) {
      const started = performance.now()
      runtime = await loadRuntime(data.runtimeBase)
      send({ type: 'runtime-ready', seconds: (performance.now() - started) / 1000 })
    }
    runtime.globals.set('elev_json', JSON.stringify(Array.from(data.elevation)))
    runtime.globals.set('params_json', JSON.stringify(data.params))
    const result: KernelResult = JSON.parse(runtime.runPython('compute_temperature(elev_json, params_json)'))
    send({ type: 'result', result, version: modelVersion })
  } catch (error) {
    send({ type: 'error', stage: runtime ? 'compute' : 'runtime', detail: String(error) })
  }
}
