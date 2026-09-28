import { describe, it, expect } from 'vitest'
import { KDTree3D, buildCellKDTree } from './kdtree'

/** Deterministic LCG so failures reproduce. */
function lcg(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 0x100000000
  }
}

function bruteNearest(
  points: Array<[number, number, number, number]>,
  qx: number,
  qy: number,
  qz: number,
): number {
  let bestId = -1
  let bestDist = Infinity
  for (const [x, y, z, id] of points) {
    const d = (qx - x) ** 2 + (qy - y) ** 2 + (qz - z) ** 2
    if (d < bestDist) {
      bestDist = d
      bestId = id
    }
  }
  return bestId
}

describe('KDTree3D (flat-array rewrite)', () => {
  it('matches brute-force nearest on random clouds', () => {
    const rand = lcg(42)
    for (const n of [1, 2, 17, 100, 1000]) {
      const points: Array<[number, number, number, number]> = []
      for (let i = 0; i < n; i++) {
        points.push([rand() * 2 - 1, rand() * 2 - 1, rand() * 2 - 1, i])
      }
      const tree = new KDTree3D(points)
      for (let q = 0; q < 200; q++) {
        const qx = rand() * 2.4 - 1.2
        const qy = rand() * 2.4 - 1.2
        const qz = rand() * 2.4 - 1.2
        expect(tree.nearest(qx, qy, qz)).toBe(bruteNearest(points, qx, qy, qz))
      }
    }
  })

  it('handles duplicate points (first-by-search-order id wins on ties)', () => {
    const points: Array<[number, number, number, number]> = [
      [0, 0, 0, 7],
      [0, 0, 0, 9],
      [1, 0, 0, 3],
    ]
    const tree = new KDTree3D(points)
    const id = tree.nearest(0, 0, 0)
    expect(id === 7 || id === 9).toBe(true)
    expect(tree.nearest(0.9, 0, 0)).toBe(3)
  })

  it('returns -1 for an empty tree', () => {
    expect(new KDTree3D([]).nearest(0, 0, 0)).toBe(-1)
  })

  it('buildCellKDTree memoizes on cells array identity', () => {
    const cells = [
      { id: 0, lon: 10, lat: 20 },
      { id: 1, lon: -30, lat: 45 },
      { id: 2, lon: 170, lat: -60 },
    ]
    const a = buildCellKDTree(cells)
    const b = buildCellKDTree(cells)
    expect(b).toBe(a)
    const other = [...cells]
    const c = buildCellKDTree(other)
    expect(c).not.toBe(a)
    // Same geometry, same answers
    expect(c.nearest(0.5, 0.5, 0.5)).toBe(a.nearest(0.5, 0.5, 0.5))
  })

  it('lon/lat cells: nearest matches direct 3D construction', () => {
    const cells = [
      { id: 11, lon: 0, lat: 0 },
      { id: 22, lon: 90, lat: 0 },
      { id: 33, lon: 0, lat: 90 },
    ]
    const tree = buildCellKDTree(cells)
    // Query on the equator at lon 45 → equidistant to 11 and 22; near lon 80 → 22
    const rad = Math.PI / 180
    const q = (lon: number, lat: number): [number, number, number] => [
      Math.cos(lat * rad) * Math.cos(lon * rad),
      Math.sin(lat * rad),
      Math.cos(lat * rad) * Math.sin(lon * rad),
    ]
    const [x, y, z] = q(80, 0)
    expect(tree.nearest(x, y, z)).toBe(22)
    const [x2, y2, z2] = q(0, 80)
    expect(tree.nearest(x2, y2, z2)).toBe(33)
  })
})
