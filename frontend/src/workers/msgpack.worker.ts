/**
 * Web Worker: fetch + decode MessagePack data off the main thread.
 *
 * The ``@msgpack/msgpack`` library is statically imported — Vite bundles it
 * into the worker chunk automatically.  ``gunzip: true`` decompresses
 * gzip-framed payloads (the static site's ``cvt_mesh.msgpack.gz``) with the
 * native ``DecompressionStream`` before decoding — GitHub Pages serves
 * ``.gz`` files as opaque bodies without ``Content-Encoding``, so the
 * decompression has to happen client-side.
 */
import { decode } from '@msgpack/msgpack'

/** Worker-scope postMessage with a transfer list (DOM lib types self as Window). */
const postTransfer = self.postMessage.bind(self) as (
  message: unknown,
  transfer?: Transferable[],
) => void

self.onmessage = async (e: MessageEvent<{ url: string; gunzip?: boolean }>) => {
  const { url, gunzip } = e.data
  const timing = { fetchMs: 0, gunzipMs: 0, decodeMs: 0 }
  try {
    const t0 = self.performance.now()
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    let buffer = await response.arrayBuffer()
    timing.fetchMs = self.performance.now() - t0
    // Sniff gzip magic: the API serves canonical meshes as application/gzip
    // (a hand-declared Content-Encoding would block browser-cache reuse),
    // the static site hands over .gz blobs, but plain msgpack responses and
    // legacy on-disk files arrive uncompressed.
    const head = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength))
    if (gunzip && head[0] === 0x1f && head[1] === 0x8b) {
      const t1 = self.performance.now()
      const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))
      buffer = await new Response(stream).arrayBuffer()
      timing.gunzipMs = self.performance.now() - t1
    }
    const t2 = self.performance.now()
    let data: unknown = decode(new Uint8Array(buffer))
    timing.decodeMs = self.performance.now() - t2
    // Mesh-shaped payloads: pack the geometry arrays into transferable typed
    // arrays before crossing the thread boundary. Structured clone of 400k
    // vertex arrays + 200k region arrays cost ~0.65 s of the measured 2.7 s
    // handoff (2026-09-29); adjacency is dropped outright — no frontend
    // consumer ever reads it. Only the cell objects still get cloned.
    const transfer: ArrayBuffer[] = []
    if (isMeshLike(data)) {
      const packed = packMeshGeometry(data)
      data = packed.data
      transfer.push(...packed.buffers)
    }
    const t3 = self.performance.now()
    postTransfer({ data, timing }, transfer)
    setTimeout(() => {
      self.postMessage({ cloneProbeMs: self.performance.now() - t3 })
    }, 0)
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err)
    self.postMessage({ error: message })
  }
}

interface MeshLike {
  cells: unknown[]
  vertices: number[][]
  regions: number[][]
  [key: string]: unknown
}

function isMeshLike(d: unknown): d is MeshLike {
  return (
    !!d &&
    typeof d === 'object' &&
    Array.isArray((d as MeshLike).cells) &&
    Array.isArray((d as MeshLike).vertices) &&
    Array.isArray((d as MeshLike).regions)
  )
}

/**
 * Flatten vertices ([x,y,z] arrays → one Float64Array) and regions (index
 * arrays → flat Int32Array + offsets). The buffers are returned for the
 * postMessage transfer list — zero-copy handoff instead of a structured
 * clone of ~600k small arrays.
 */
function packMeshGeometry(mesh: MeshLike): { data: Record<string, unknown>; buffers: ArrayBuffer[] } {
  const n = mesh.vertices.length
  const verticesFlat = new Float64Array(n * 3)
  for (let i = 0; i < n; i++) {
    const v = mesh.vertices[i]
    verticesFlat[i * 3] = v[0]
    verticesFlat[i * 3 + 1] = v[1]
    verticesFlat[i * 3 + 2] = v[2]
  }
  const regionOffsets = new Uint32Array(mesh.regions.length + 1)
  let total = 0
  for (let i = 0; i < mesh.regions.length; i++) {
    total += mesh.regions[i].length
    regionOffsets[i + 1] = total
  }
  const regionsFlat = new Int32Array(total)
  let o = 0
  for (const r of mesh.regions) {
    for (const v of r) {
      regionsFlat[o++] = v
    }
  }
  // Destructure to omit the array/object forms from the packed payload.
  const { cells, vertices: _vertices, regions: _regions, adjacency: _adjacency, ...rest } = mesh
  return {
    data: { ...rest, cells, verticesFlat, regionsFlat, regionOffsets },
    buffers: [verticesFlat.buffer, regionsFlat.buffer, regionOffsets.buffer],
  }
}
