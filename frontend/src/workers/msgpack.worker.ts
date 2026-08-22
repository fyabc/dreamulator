/**
 * Web Worker: fetch + decode MessagePack CVT mesh data off the main thread.
 *
 * The ``@msgpack/msgpack`` library is statically imported — Vite bundles it
 * into the worker chunk automatically.
 */
import { decode } from '@msgpack/msgpack'

self.onmessage = async (e: MessageEvent<{ url: string }>) => {
  const { url } = e.data
  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    const buffer = await response.arrayBuffer()
    const data = decode(new Uint8Array(buffer))
    self.postMessage({ data })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err)
    self.postMessage({ error: message })
  }
}
