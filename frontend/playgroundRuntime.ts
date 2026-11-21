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
export const ebmPackages = ['numpy', 'scipy', 'pydantic', 'rich', 'msgpack', 'pyyaml', 'pillow', 'astropy']

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
  throw new Error(`Could not download ${filename} for the browser climate runtime. ${failures.join('; ')}`)
}

async function prepareRuntime(publicDir: string, fullEbm: boolean): Promise<void> {
  const lock = JSON.parse(await readFile(join(distribution, 'pyodide-lock.json'), 'utf8')) as {
    packages: Record<string, { file_name: string; sha256: string; depends: string[] }>
  }
  const wheels = new Map<string, string>()
  function addWheel(name: string) {
    const wheel = lock.packages[name.toLowerCase().replaceAll('_', '-')]
    if (!wheel) throw new Error(`Pyodide does not publish a locked wheel for ${name}.`)
    if (wheels.has(wheel.file_name)) return
    wheels.set(wheel.file_name, wheel.sha256)
    wheel.depends.forEach(addWheel)
  }
  for (const name of fullEbm ? ebmPackages : ['numpy']) addWheel(name)
  const target = join(publicDir, playgroundRuntimePath)
  const files = [...runtimeFiles, ...wheels.keys()]
  const missing = files.filter(file => !existsSync(join(target, file)))
  if (!missing.length) return

  await mkdir(target, { recursive: true })
  const staging = await mkdtemp(join(dirname(publicDir), '.playground-runtime-'))
  try {
    for (const file of missing) {
      const checksum = wheels.get(file)
      const staged = join(staging, file)
      if (checksum) await writeFile(staged, await getWheel(file, checksum))
      else await copyFile(join(distribution, file), staged)
      await rename(staged, join(target, file))
    }
  } finally {
    await rm(staging, { recursive: true, force: true })
  }
}

export function playgroundRuntime(fullEbm: boolean): Plugin {
  return {
    name: 'dreamulator-playground-runtime',
    configResolved: config => prepareRuntime(config.publicDir, fullEbm),
  }
}
