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
  'mesh-fetch': 'cvt_mesh.json fetch + parse',
  'mesh-adapt': 'adaptCvtMesh (vertex conversion)',
  'kd-tree': 'KD-tree build (useCellIdMap)',
  'layer-bake': 'Texture bake (all layers)',
  'layer-bake-terrain': '  └ terrain bake',
  'layer-bake-koppen': '  └ koppen bake',
  'first-paint': 'First textured globe paint',
}

let _observer: PerformanceObserver | null = null

/** Call once at app entry. */
export function initPerfObserver(): void {
  if (_observer) return
  try {
    _observer = new PerformanceObserver((list) => {
      const measures = list.getEntriesByType('measure') as PerformanceMeasure[]
      if (measures.length === 0) return
      // Only print when we have the final mark (first-paint = real terrain texture ready).
      const hasFinal = measures.some((m) => m.name === PREFIX + 'first-paint')
      if (!hasFinal) return

      const all = performance.getEntriesByType('measure') as PerformanceMeasure[]
      const ours = all.filter((m) => m.name.startsWith(PREFIX))
      if (ours.length === 0) return

      const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined

      const totalMs = ours.find((m) => m.name === PREFIX + 'first-paint')?.duration ?? 0

      console.groupCollapsed(
        `%c⏱ dreamulator load %c${(totalMs / 1000).toFixed(1)}s`,
        'font-weight:bold', 'color:#888',
      )
      for (const m of ours) {
        const name = m.name.slice(PREFIX.length)
        const label = LABELS[name] ?? name
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
      // React StrictMode double-mount: if already measured, skip silently.
      if (performance.getEntriesByName(PREFIX + base, 'measure').length > 0) {
        performance.clearMarks(startName)
        return
      }
      performance.mark(full)  // create end mark before measure()
      performance.measure(PREFIX + base, startName, full)
      performance.clearMarks(startName)
      performance.clearMarks(full)
      return
    }
  }
  // Start mark or unmatched end mark
  performance.mark(full)
}
