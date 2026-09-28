/**
 * Shared MessagePack worker client.
 *
 * One worker instance serves both the dev-API path (``fmt=msgpack`` mesh
 * responses, served as ``application/gzip`` so ETag revalidation can reuse
 * the cache entry) and the static-site path (``cvt_mesh.msgpack.gz`` blobs
 * fetched by the static client and handed over as object URLs) — both use
 * ``gunzip: true`` and the worker sniffs the actual magic bytes.
 */
import MsgPackWorker from './msgpack.worker.ts?worker'
import { recordExternal } from '../utils/perf'

let _msgpackWorker: Worker | null = null

function getMsgpackWorker(): Worker {
  if (!_msgpackWorker) {
    _msgpackWorker = new MsgPackWorker()
  }
  return _msgpackWorker
}

/** Fetch *url* and decode its MessagePack payload off the main thread. */
export function decodeMsgpackUrl(url: string, gunzip = false): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const worker = getMsgpackWorker()
    worker.onmessage = (e: MessageEvent<{
      data?: unknown
      error?: string
      cloneProbeMs?: number
      timing?: { fetchMs: number; gunzipMs: number; decodeMs: number }
    }>) => {
      if (e.data.cloneProbeMs != null) {
        recordExternal('msgpack-clone-out', e.data.cloneProbeMs)
        return
      }
      const t = e.data.timing
      if (t) {
        // Stack the sequential worker phases backwards from receipt time.
        recordExternal('msgpack-decode', t.decodeMs)
        recordExternal('msgpack-gunzip', t.gunzipMs, t.decodeMs)
        recordExternal('msgpack-net', t.fetchMs, t.gunzipMs + t.decodeMs)
      }
      if (e.data.error) {
        reject(new Error(e.data.error))
      } else {
        resolve(e.data.data)
      }
    }
    worker.onerror = (err: ErrorEvent) => {
      reject(new Error(err.message))
    }
    worker.postMessage({ url, gunzip })
  })
}
