import type { SkyEphemerisResult, SkyQuery } from './types'

export interface BrowserSkyRequest {
  runtime: string
  solver: string
  catalog: string
  query: SkyQuery
}

export type BrowserSkyReply = { result: SkyEphemerisResult } | { error: string }

async function initialize(runtime: string, solver: string) {
  const { loadPyodide } = await import(/* @vite-ignore */ `${runtime}pyodide.mjs`) as typeof import('pyodide')
  const python = await loadPyodide({ indexURL: runtime })
  const source = await fetch(solver)
  if (!source.ok) throw new Error(`HTTP ${source.status}: ${solver}`)
  await python.loadPackage(['numpy', 'pydantic', 'astropy'])
  python.unpackArchive(new Uint8Array(await source.arrayBuffer()), 'zip', { extractDir: '/solver' })
  python.runPython(`
import json, sys
sys.path.insert(0, '/solver')
from dreamulator.engine.ephemeris import sky_ephemeris
from dreamulator.models.catalog import load_entities

def set_catalog(catalog_json):
    global entities, default_observer
    catalog = json.loads(catalog_json)
    entities = load_entities(catalog)
    default_observer = catalog.get('target_body_id')

def observe_sky(query_json):
    query = json.loads(query_json)
    observer = query.get('from') or default_observer
    if not observer:
        raise ValueError('No observer given and the catalog has no target_body_id')
    return sky_ephemeris(
        entities, observer, query.get('lat', 0), query.get('lon', 0),
        query.get('at', 0), targets=query.get('targets') or None,
        include_events=query.get('includeEvents', True),
    ).model_dump_json()
`)
  return python
}

let runtime: ReturnType<typeof initialize> | undefined
let currentCatalog: string | undefined

self.onmessage = async ({ data }: MessageEvent<BrowserSkyRequest>) => {
  let reply: BrowserSkyReply
  try {
    runtime ??= initialize(data.runtime, data.solver).catch(error => {
      runtime = undefined
      throw error
    })
    const python = await runtime
    if (currentCatalog !== data.catalog) {
      const response = await fetch(data.catalog)
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${data.catalog}`)
      python.globals.set('catalog_json', await response.text())
      python.runPython('set_catalog(catalog_json)')
      currentCatalog = data.catalog
    }
    python.globals.set('query_json', JSON.stringify(data.query))
    reply = { result: JSON.parse(python.runPython('observe_sky(query_json)') as string) as SkyEphemerisResult }
  } catch (error) {
    const message = error instanceof Error ? error.message.trim() : String(error)
    const detail = message.split('\n').find(line => /^[\w.]+(?:Error|Exception):/.test(line))
    reply = { error: detail ?? message }
  }
  self.postMessage(reply)
}
