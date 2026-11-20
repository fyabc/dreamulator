const directoryName = 'dreamulator-terrain-models-v1'
const writeChunkSize = 16 * 1024 * 1024

function missingEntry(error: unknown) {
  return error instanceof DOMException && error.name === 'NotFoundError'
}

export async function openTerrainModelCache() {
  try {
    const root = await navigator.storage.getDirectory()
    return await root.getDirectoryHandle(directoryName, { create: true })
  } catch {
    return undefined
  }
}

export async function readTerrainModelCacheBytes() {
  const root = await navigator.storage.getDirectory()
  const cache = await root.getDirectoryHandle(directoryName).catch((error: unknown) => {
    if (!missingEntry(error)) throw error
  })
  if (!cache) return 0
  let bytes = 0
  for await (const entry of cache.values()) {
    if (entry.kind !== 'file') continue
    bytes += (await (entry as FileSystemFileHandle).getFile()).size
  }
  return bytes
}

export async function clearTerrainModelCache() {
  const root = await navigator.storage.getDirectory()
  await root.removeEntry(directoryName, { recursive: true }).catch((error: unknown) => {
    if (!missingEntry(error)) throw error
  })
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
