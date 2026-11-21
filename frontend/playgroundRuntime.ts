import { createHash } from 'node:crypto'
import { existsSync } from 'node:fs'
import { copyFile, mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import type { Plugin } from 'vite'

const require = createRequire(import.meta.url)
const packagePath = require.resolve('pyodide/package.json')
const { version } = require(packagePath) as { version: string }
const distribution = dirname(packagePath)
const runtimeFiles = [
  'pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json',
]
const mirrors = ['cdn.jsdelivr.net', 'testingcf.jsdelivr.net']

export const playgroundRuntimePath = `playground-runtime/v${version}/`

function sha256(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex')
}

async function getWheel(filename: string, checksum: string): Promise<Buffer> {
  const failures: string[] = []
  for (const host of mirrors) {
    try {
      const response = await fetch(`https://${host}/pyodide/v${version}/full/${filename}`, {
        signal: AbortSignal.timeout(30_000),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const bytes = Buffer.from(await response.arrayBuffer())
      if (sha256(bytes) !== checksum) throw new Error('SHA-256 mismatch')
      return bytes
    } catch (error) {
      failures.push(`${host}: ${String(error)}`)
    }
  }
  throw new Error(`Could not download ${filename} for the browser temperature runtime. ${failures.join('; ')}`)
}

async function prepareRuntime(publicDir: string): Promise<void> {
  const lock = JSON.parse(await readFile(join(distribution, 'pyodide-lock.json'), 'utf8'))
  const { file_name: filename, sha256: checksum } = lock.packages.numpy as {
    file_name: string; sha256: string
  }
  const target = join(publicDir, playgroundRuntimePath)
  const isReady = () => [...runtimeFiles, filename].every(file => existsSync(join(target, file)))
  if (isReady()) return
  if (existsSync(target)) await rm(target, { recursive: true, force: true })

  await mkdir(dirname(target), { recursive: true })
  const staging = await mkdtemp(join(dirname(publicDir), '.playground-runtime-'))
  try {
    await writeFile(join(staging, filename), await getWheel(filename, checksum))
    for (const file of runtimeFiles) await copyFile(join(distribution, file), join(staging, file))
    try {
      await rename(staging, target)
    } catch (error) {
      if (!isReady()) throw error
    }
  } finally {
    await rm(staging, { recursive: true, force: true })
  }
}

export function playgroundRuntime(): Plugin {
  return {
    name: 'dreamulator-playground-runtime',
    configResolved: config => prepareRuntime(config.publicDir),
  }
}
