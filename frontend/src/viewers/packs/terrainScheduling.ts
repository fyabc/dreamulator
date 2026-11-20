export async function yieldTerrainTask(signal: AbortSignal) {
  signal.throwIfAborted()
  await new Promise<void>((resolve) => {
    const { port1, port2 } = new MessageChannel()
    port1.onmessage = () => {
      port1.close()
      port2.close()
      resolve()
    }
    port2.postMessage(null)
  })
  signal.throwIfAborted()
}
