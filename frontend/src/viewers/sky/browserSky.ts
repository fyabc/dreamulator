import type { BrowserSkyReply, BrowserSkyRequest } from './browserSky.worker'

let worker: Worker | undefined
let queue: Promise<unknown> = Promise.resolve()

export function runBrowserSky(request: BrowserSkyRequest, signal?: AbortSignal) {
  const result = queue.then(() => {
    signal?.throwIfAborted()
    const active = worker ??= new Worker(new URL('./browserSky.worker.ts', import.meta.url), { type: 'module' })
    return new Promise<BrowserSkyReply>((resolve, reject) => {
      active.onmessage = ({ data }: MessageEvent<BrowserSkyReply>) => resolve(data)
      active.onerror = (error) => {
        active.terminate()
        worker = undefined
        reject(new Error(error.message || 'Sky worker failed'))
      }
      active.postMessage(request)
    })
  })
  queue = result.catch(() => undefined)
  return result.then(reply => {
    signal?.throwIfAborted()
    if ('error' in reply) throw new Error(reply.error)
    return reply.result
  })
}
