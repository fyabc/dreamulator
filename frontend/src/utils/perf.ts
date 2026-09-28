/**
 * Lightweight performance instrumentation for mesh loading.
 *
 * Usage:
 *   import { mark, initPerfObserver } from '@/utils/perf'
 *   mark('mesh-fetch-start')
 *   // ... work ...
 *   mark('mesh-fetch-end')
 *
 * On load complete the observer prints a sorted timing summary to the
 * console.  Call ``initPerfObserver()`` once at app entry.
 *
 * Why not Puppeteer / Lighthouse: zero-dependency, works in dev + static
 * preview, numbers are reproducible across builds for A/B comparison.
 */

const PREFIX = 'dream-'

const LABELS: Record<string, string> = {
  'mesh-fetch': 'mesh fetch (net + worker decode)',
  'mesh-adapt': 'adaptCvtMesh (vertex conversion)',
  'msgpack-net': '  └ worker: fetch + arrayBuffer',
  'msgpack-gunzip': '  └ worker: DecompressionStream gunzip',
  'msgpack-decode': '  └ worker: msgpack decode',
  'msgpack-clone-out': '  └ postMessage clone (serialize)',
  'monthly-fetch': 'climate_monthly net transfer',
  'monthly-decode': 'climate_monthly decode (main thread)',
  'yearly-fetch': 'climate_yearly net transfer',
  'yearly-decode': 'climate_yearly decode (main thread)',
  'elev-decode': 'elevation.png decode → Float32',
  'kd-tree': 'KD-tree build (useCellIdMap)',
  'layer-bake': 'Texture bake (all layers)',
  'layer-bake-terrain': '  └ terrain bake',
  'layer-bake-koppen': '  └ koppen bake',
  'first-paint': 'First textured globe paint',
  'first-frame': 'First rendered frame (interactive-ready)',
}

let _observer: PerformanceObserver | null = null
let _printed = false

/** Call once at app entry. */
export function initPerfObserver(): void {
  if (_observer) return
  try {
    _observer = new PerformanceObserver((list) => {
      const measures = list.getEntriesByType('measure') as PerformanceMeasure[]
      if (measures.length === 0) return
      // Only print when we have a final mark: first-frame (globe pages, first
      // rendered frame after the texture lands) or first-paint fallback.
      const hasFinal =
        measures.some((m) => m.name === PREFIX + 'first-frame') ||
        measures.some((m) => m.name === PREFIX + 'first-paint')
      if (!hasFinal || _printed) return
      _printed = true

      const all = performance.getEntriesByType('measure') as PerformanceMeasure[]
      const ours = all.filter((m) => m.name.startsWith(PREFIX))
      if (ours.length === 0) return

      const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined

      const totalMs =
        ours.find((m) => m.name === PREFIX + 'first-frame')?.duration ??
        ours.find((m) => m.name === PREFIX + 'first-paint')?.duration ??
        0

      console.groupCollapsed(
        `%c⏱ dreamulator load %c${(totalMs / 1000).toFixed(1)}s`,
        'font-weight:bold', 'color:#888',
      )
      for (const m of ours) {
        const name = m.name.slice(PREFIX.length)
        const hashIdx = name.indexOf('#')
        const label = (LABELS[hashIdx >= 0 ? name.slice(0, hashIdx) : name] ?? name)
        const ms = m.duration
        const bar = '█'.repeat(Math.min(Math.round(ms / 50), 40))
        console.log(`%c${label.padEnd(38)} %c${ms.toFixed(0).padStart(5)} ms  ${bar}`,
          '', ms > 2000 ? 'color:red;font-weight:bold' : 'color:#888')
      }
      if (navEntry) {
        const ttfb = navEntry.responseStart - navEntry.requestStart
        const dom = navEntry.domContentLoadedEventEnd - navEntry.requestStart
        console.log(`%c${'TTFB'.padEnd(38)} %c${ttfb.toFixed(0).padStart(5)} ms`, '', 'color:#888')
        console.log(`%c${'DOM ready'.padEnd(38)} %c${dom.toFixed(0).padStart(5)} ms`, '', 'color:#888')
      }
      console.groupEnd()
    })
    _observer.observe({ entryTypes: ['measure'] })
  } catch {
    // PerformanceObserver not available (SSR / test env)
  }
}

/** Record a named mark.  ``mark('mesh-fetch-end')`` auto-stops ``mesh-fetch``. */
export function mark(name: string): void {
  const full = PREFIX + name
  if (name.endsWith('-end')) {
    const base = name.slice(0, -4) // strip '-end'
    const startName = PREFIX + base + '-start'
    const start = performance.getEntriesByName(startName, 'mark')[0]
    if (start) {
      // Repeat invocations (real second bake after mesh arrival; StrictMode
      // double-mount in dev) get a ``#2``-style suffix instead of being
      // dropped, so late phases stay visible in the waterfall.
      const repeats = performance
        .getEntriesByType('measure')
        .filter((m) => m.name === PREFIX + base || m.name.startsWith(`${PREFIX + base}#`))
        .length
      const measureName = repeats > 0 ? `${PREFIX + base}#${repeats + 1}` : PREFIX + base
      performance.mark(full)  // create end mark before measure()
      performance.measure(measureName, startName, full)
      performance.clearMarks(startName)
      performance.clearMarks(full)
      return
    }
  }
  // Start mark or unmatched end mark
  performance.mark(full)
}

/**
 * Record a duration measured in another realm (e.g. the MessagePack Web
 * Worker, whose ``performance.now()`` clock is not the main-thread one).
 *
 * The synthetic measure is anchored at the main-thread receipt time; pass
 * ``offsetFromEndMs`` to stack sequential phases (later phases get offset 0,
 * earlier ones the sum of the durations that follow them).
 */
export function recordExternal(name: string, durationMs: number, offsetFromEndMs = 0): void {
  if (!Number.isFinite(durationMs) || durationMs <= 0) return
  try {
    const now = performance.now()
    performance.measure(PREFIX + name, {
      start: now - durationMs - offsetFromEndMs,
      end: now - offsetFromEndMs,
    })
  } catch {
    // numeric measure options unsupported — ignore
  }
}

/** Measure from navigation start (time origin) to now, e.g. first frame. */
export function measureFromStart(name: string): void {
  try {
    performance.measure(PREFIX + name, { start: 0, end: performance.now() })
  } catch {
    // numeric measure options unsupported — ignore
  }
}
