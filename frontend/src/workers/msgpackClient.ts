/**
 * Shared MessagePack worker client.
 *
 * One worker instance serves both the dev-API path (``fmt=msgpack`` mesh
 * responses, browser-decompressed via Content-Encoding) and the static-site
 * path (``cvt_mesh.msgpack.gz`` blobs fetched by the static client and handed
 * over as object URLs with ``gunzip: true``).
 */
import MsgPackWorker from './msgpack.worker.ts?worker'

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
    worker.onmessage = (e: MessageEvent<{ data?: unknown; error?: string }>) => {
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
