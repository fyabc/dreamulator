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

self.onmessage = async (e: MessageEvent<{ url: string; gunzip?: boolean }>) => {
  const { url, gunzip } = e.data
  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    let buffer = await response.arrayBuffer()
    if (gunzip) {
      const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))
      buffer = await new Response(stream).arrayBuffer()
    }
    const data = decode(new Uint8Array(buffer))
    self.postMessage({ data })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err)
    self.postMessage({ error: message })
  }
}
