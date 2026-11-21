import { maxSourceBytes } from './elevationProject'
import { readTar, writeTar } from './worldDataArchive'

const manifestPath = 'dreamulator-snapshot.json'
const maxSnapshotBytes = maxSourceBytes + 6 * 2 ** 20

export function isCreationWorldId(id: string) {
  return /^[a-z0-9][a-z0-9_-]{0,47}$/.test(id) && !/^(earth|con|prn|aux|nul|com[1-9]|lpt[1-9])$/.test(id)
}

export const jsonBlob = (value: unknown) => new Blob([JSON.stringify(value)], { type: 'application/json' })
export const sha256 = async (blob: Blob) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
  await blob.arrayBuffer())), value => value.toString(16).padStart(2, '0')).join('')

export async function writeCreationSnapshot(id: string, contents: Map<string, Blob>): Promise<Blob> {
  const files = new Map<string, Blob>()
  const checksums: Record<string, string> = {}
  for (const [path, file] of contents) {
    files.set(`${id}/${path}`, file)
    checksums[path] = await sha256(file)
  }
  files.set(manifestPath, jsonBlob({ format: 1, world: id, dreamulatorVersion: __APP_VERSION__, sha256: checksums }))
  const stream = writeTar(files).stream().pipeThrough(new CompressionStream('gzip'))
  return new Response(stream, { headers: { 'Content-Type': 'application/gzip' } }).blob()
}

async function decompressSnapshot(blob: Blob) {
  if (!blob.size || blob.size > maxSnapshotBytes) throw new Error('Unsupported world snapshot size')
  const stream = blob.stream().pipeThrough(new DecompressionStream('gzip')).getReader()
  const chunks: Uint8Array<ArrayBuffer>[] = []
  let size = 0
  try {
    for (;;) {
      const { value, done } = await stream.read()
      if (done) break
      size += value.length
      if (size > maxSnapshotBytes) throw new Error('Unsupported world snapshot size')
      chunks.push(value)
    }
  } finally { await stream.cancel() }
  return new Blob(chunks)
}

export async function readCreationSnapshot(blob: Blob) {
  const archive = await readTar(await decompressSnapshot(blob), true)
  const header = archive.get(manifestPath)
  if (!header || header.size > 8192) throw new Error('Missing or oversized world snapshot manifest')
  const manifest = JSON.parse(await header.text())
  const { world: id, sha256: checksums } = manifest ?? {}
  if (manifest?.format !== 1 || typeof id !== 'string' || !isCreationWorldId(id) || !checksums ||
    typeof checksums !== 'object' || Array.isArray(checksums) || !Object.keys(checksums).includes('world.yaml') ||
    Object.keys(checksums).length !== archive.size - 1) throw new Error('Invalid world snapshot')
  const files = new Map<string, Blob>()
  for (const [path, hash] of Object.entries(checksums)) {
    const file = archive.get(`${id}/${path}`)
    if (!file || await sha256(file) !== hash) throw new Error('Snapshot checksum mismatch')
    files.set(path, file)
  }
  const parse = async (path: string) => {
    const file = files.get(path)
    if (!file) throw new Error('Incomplete world snapshot')
    return JSON.parse(await file.text())
  }
  return { id, files, parse }
}

export type CreationSnapshot = Awaited<ReturnType<typeof readCreationSnapshot>>
