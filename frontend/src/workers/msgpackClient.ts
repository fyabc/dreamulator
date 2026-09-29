/**
 * Shared MessagePack worker client.
 *
 * One worker instance serves both the dev-API path (``fmt=msgpack`` mesh
 * responses, served as ``application/gzip`` so ETag revalidation can reuse
 * the cache entry) and the static-site path (``cvt_mesh.msgpack.gz`` /
 * ``mesh_geometry|fields.msgpack.gz`` blobs fetched by the static client and
 * handed over as object URLs) — both use ``gunzip: true`` and the worker
 * sniffs the actual magic bytes.
 *
 * Calls are routed by request id so parallel requests (the split mesh loads
 * its geometry and fields halves concurrently) each get their own reply —
 * the former single ``onmessage`` reassignment silently clobbered the
 * previous caller's handler.
 */
import MsgPackWorker from './msgpack.worker.ts?worker'
import { recordExternal } from '../utils/perf'

let _msgpackWorker: Worker | null = null

interface Pending {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
}

let _nextReqId = 1
const _pending = new Map<number, Pending>()

function getMsgpackWorker(): Worker {
  if (!_msgpackWorker) {
    _msgpackWorker = new MsgPackWorker()
    _msgpackWorker.onmessage = (e: MessageEvent<{
      reqId?: number
      data?: unknown
      error?: string
      cloneProbeMs?: number
      timing?: { fetchMs: number; gunzipMs: number; decodeMs: number }
    }>) => {
      const msg = e.data
      if (msg.cloneProbeMs != null) {
        recordExternal('msgpack-clone-out', msg.cloneProbeMs)
        return
      }
      const p = msg.reqId != null ? _pending.get(msg.reqId) : undefined
      if (!p) return
      _pending.delete(msg.reqId!)
      const t = msg.timing
      if (t) {
        // Stack the sequential worker phases backwards from receipt time.
        recordExternal('msgpack-decode', t.decodeMs)
        recordExternal('msgpack-gunzip', t.gunzipMs, t.decodeMs)
        recordExternal('msgpack-net', t.fetchMs, t.gunzipMs + t.decodeMs)
      }
      if (msg.error) {
        p.reject(new Error(msg.error))
      } else {
        p.resolve(msg.data)
      }
    }
    _msgpackWorker.onerror = (err: ErrorEvent) => {
      for (const p of _pending.values()) p.reject(new Error(err.message))
      _pending.clear()
    }
  }
  return _msgpackWorker
}

/** Fetch *url* and decode its MessagePack payload off the main thread. */
export function decodeMsgpackUrl(url: string, gunzip = false): Promise<unknown> {
  const worker = getMsgpackWorker()
  const reqId = _nextReqId++
  return new Promise((resolve, reject) => {
    _pending.set(reqId, { resolve, reject })
    worker.postMessage({ reqId, url, gunzip })
  })
}
