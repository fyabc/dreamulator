interface AdapterInfo {
  description?: string
  vendor?: string
  architecture?: string
  isFallbackAdapter?: boolean
}

interface BrowserAdapter {
  info?: AdapterInfo
  isFallbackAdapter?: boolean
}

interface BrowserGpu {
  requestAdapter(options: { powerPreference: 'high-performance' }): Promise<BrowserAdapter | null>
}

export type WebGpuDevice = {
  adapter: BrowserAdapter
  kind: 'hardware' | 'software' | 'unknown'
  name: string | null
}

const vendors: Record<string, string> = { nvidia: 'NVIDIA', intel: 'Intel', amd: 'AMD', apple: 'Apple', google: 'Google' }
let browserDevice: Promise<WebGpuDevice | null> | undefined

export function getWebGpuDevice() {
  return browserDevice ??= detectWebGpu().then((device) => {
    if (!device) browserDevice = undefined
    return device
  })
}

export async function detectWebGpu(
  gpu = (globalThis.navigator as (Navigator & { gpu?: BrowserGpu }) | undefined)?.gpu,
): Promise<WebGpuDevice | null> {
  try {
    const adapter = await gpu?.requestAdapter({ powerPreference: 'high-performance' })
    if (!adapter) return null
    const { description, vendor, architecture, isFallbackAdapter } = adapter.info ?? {}
    const vendorName = vendor && (vendors[vendor.toLowerCase()] ?? vendor)
    const fallback = isFallbackAdapter ?? adapter.isFallbackAdapter
    return {
      adapter,
      kind: fallback === true ? 'software' : fallback === false ? 'hardware' : 'unknown',
      name: description?.trim() || [vendorName, architecture].filter(Boolean).join(' ') || null,
    }
  } catch {
    return null
  }
}
