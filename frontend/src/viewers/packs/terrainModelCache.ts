const directoryName = 'dreamulator-terrain-models-v1'
const writeChunkSize = 16 * 1024 * 1024

export async function openTerrainModelCache() {
  try {
    const root = await navigator.storage.getDirectory()
    return await root.getDirectoryHandle(directoryName, { create: true })
  } catch {
    return undefined
  }
}

export async function saveTerrainModel(cache: FileSystemDirectoryHandle, key: string, data: ArrayBuffer, signal: AbortSignal) {
  let writer: FileSystemWritableFileStream | undefined
  try {
    const entry = await cache.getFileHandle(key, { create: true })
    writer = await entry.createWritable()
    for (let offset = 0; offset < data.byteLength; offset += writeChunkSize) {
      signal.throwIfAborted()
      await writer.write(new Uint8Array(data, offset, Math.min(writeChunkSize, data.byteLength - offset)))
    }
    signal.throwIfAborted()
    await writer.close()
    return true
  } catch {
    await writer?.abort().catch(() => undefined)
    signal.throwIfAborted()
    return false
  }
}
