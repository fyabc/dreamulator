/**
 * Split-mesh column composition (P1 几何/气候数据分离存储, 2026-09-29).
 *
 * The backend ships the mesh as two columnar halves (see
 * `map/export.py` STATIC_CELL_COLUMNS / DYNAMIC_CELL_FIELDS):
 *  - `mesh_geometry.msgpack.gz` — `mesh-geometry-v1`: metadata, flat f64
 *    vertices, flat regions + neighbors, static geological columns.
 *  - `mesh_fields.msgpack.gz` — `mesh-fields-v1`: dynamic per-cell columns.
 *
 * Column kinds: `f` f32 (null → NaN), `b` u8, `s`/`S` interned string
 * table + u32 indices (null → 0xFFFFFFFF; `S` values are `\x1f`-joined
 * lists).  The worker hands the raw blobs over as transferables; this
 * module rebuilds the VoronoiCell objects once on the main thread (one
 * pass, ~0.5 s @ 200k — vs the former 2.3 s object-graph clone + 1.3 s
 * deserialize of the combined file).
 */

import type { CVTMesh, CVTVertex, VoronoiCell } from '../viewers/map/types'

const NULL_IDX = 0xffffffff
const TAG_SEP = '\x1f'

interface ColumnPack {
  t: string
  data?: Uint8Array
  table?: string[]
  idx?: Uint8Array
}

interface FlatIndex {
  off: Uint32Array
  idx: Int32Array
}

/** msgpack-bin → typed-array views, created once per column. */
interface ColumnView {
  f?: Float32Array
  b?: Uint8Array
  table?: string[]
  idx?: Uint32Array
  isList?: boolean
}

function viewOf(col: ColumnPack): ColumnView {
  const v: ColumnView = {}
  if (col.t === 'f' && col.data) v.f = new Float32Array(col.data.buffer, col.data.byteOffset, col.data.byteLength / 4)
  else if (col.t === 'b' && col.data) v.b = col.data
  else if ((col.t === 's' || col.t === 'S') && col.idx) {
    v.table = col.table ?? []
    v.idx = new Uint32Array(col.idx.buffer, col.idx.byteOffset, col.idx.byteLength / 4)
    v.isList = col.t === 'S'
  }
  return v
}

function readAt(v: ColumnView, i: number): number | boolean | string | string[] | null {
  if (v.f) {
    const x = v.f[i]
    return Number.isNaN(x) ? null : x
  }
  if (v.b) {
    const x = v.b[i]
    return x === 2 ? null : x !== 0
  }
  if (v.idx) {
    const j = v.idx[i]
    if (j === NULL_IDX) return null
    const s = v.table![j]
    return v.isList ? s.split(TAG_SEP) : s
  }
  return null
}

/** Shape guard: a decoded split geometry/fields payload. */
export function isSplitGeometry(d: unknown): d is Record<string, unknown> {
  return !!d && typeof d === 'object' && (d as Record<string, unknown>).format === 'mesh-geometry-v1'
}

export function isSplitFields(d: unknown): d is Record<string, unknown> {
  return !!d && typeof d === 'object' && (d as Record<string, unknown>).format === 'mesh-fields-v1'
}

/**
 * Compose the frontend CVTMesh from the split pair (worker-decoded, blobs
 * transferred, no intermediate object graph).
 */
export function composeSplitMesh(
  geo: Record<string, unknown>,
  flds: Record<string, unknown> | null,
): CVTMesh | null {
  const n = (geo.num_cells as number) ?? 0
  if (!n) return null

  // Vertices: flat f64 blob → {id, lon, lat} (same math as the combined path).
  const vbytes = geo.vertices as Uint8Array
  const vflat = new Float64Array(vbytes.buffer, vbytes.byteOffset, vbytes.byteLength / 8)
  const vertices: CVTVertex[] = new Array(vflat.length / 3)
  for (let i = 0; i < vertices.length; i++) {
    const x = vflat[i * 3]
    const y = vflat[i * 3 + 1]
    const z = vflat[i * 3 + 2]
    const r = Math.sqrt(x * x + y * y + z * z)
    vertices[i] = {
      id: i,
      lat: Math.asin(Math.max(-1, Math.min(1, y / Math.max(r, 1e-12)))) * (180 / Math.PI),
      lon: Math.atan2(z, x) * (180 / Math.PI),
    }
  }

  const regionsFlat = flatIndex(geo.regions as Record<string, Uint8Array>)
  const neighborsFlat = flatIndex(geo.neighbors as Record<string, Uint8Array>)

  const staticViews = Object.entries((geo.columns as Record<string, ColumnPack>) ?? {}).map(
    ([name, col]) => [name, viewOf(col)] as const,
  )
  const dynamicViews = flds
    ? Object.entries((flds.columns as Record<string, ColumnPack>) ?? {}).map(
        ([name, col]) => [name, viewOf(col)] as const,
      )
    : []

  const cells: VoronoiCell[] = new Array(n)
  for (let i = 0; i < n; i++) {
    const c: Record<string, unknown> = {}
    for (const [name, v] of staticViews) c[name] = readAt(v, i)
    for (const [name, v] of dynamicViews) c[name] = readAt(v, i)
    const o0 = neighborsFlat.off[i]
    const o1 = neighborsFlat.off[i + 1]
    c.neighbors =
      o1 > o0
        ? Array.from(neighborsFlat.idx.subarray(o0, o1))
        : []
    cells[i] = c as unknown as VoronoiCell
  }

  const regions: CVTMesh['regions'] = new Array(regionsFlat.off.length - 1)
  for (let i = 0; i < regions.length; i++) {
    regions[i] = {
      id: i,
      vertex_ids: Array.from(
        regionsFlat.idx.subarray(regionsFlat.off[i], regionsFlat.off[i + 1]),
      ),
      plate_id: (cells[i] as VoronoiCell | undefined)?.plate_id ?? null,
      boundaries: null,
    }
  }

  return {
    seed: (geo.seed as number) ?? 0,
    num_cells: n,
    jitter_sigma: geo.jitter_sigma as number | undefined,
    lloyd_iterations: geo.lloyd_iterations as number | undefined,
    cells,
    vertices,
    regions,
  }
}

function flatIndex(pack: Record<string, Uint8Array> | undefined): FlatIndex {
  if (!pack?.off || !pack?.idx) return { off: new Uint32Array(0), idx: new Int32Array(0) }
  const off = new Uint32Array(pack.off.buffer, pack.off.byteOffset, pack.off.byteLength / 4)
  const idx = new Int32Array(pack.idx.buffer, pack.idx.byteOffset, pack.idx.byteLength / 4)
  return { off, idx }
}
