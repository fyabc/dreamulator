/**
 * Minimal k-d tree for fast nearest-neighbor queries in 3D space.
 *
 * Used for cell hit-testing on the map viewer — replaces the SVG polygon
 * hit-test layer that creates thousands of DOM nodes.
 *
 * Build: O(n log n), Query: O(log n) average.
 */

interface KDNode {
  point: Float32Array // [x, y, z]
  id: number // cell ID
  left: KDNode | null
  right: KDNode | null
  splitAxis: number // 0, 1, or 2
}

export class KDTree3D {
  private root: KDNode | null = null

  /**
   * Build a KD-tree from an array of 3D points.
   * @param points Array of [x, y, z, id] tuples
   */
  constructor(points: Array<[number, number, number, number]>) {
    if (points.length === 0) return
    this.root = this.build(points, 0)
  }

  private build(
    points: Array<[number, number, number, number]>,
    depth: number,
  ): KDNode | null {
    if (points.length === 0) return null

    const axis = depth % 3

    // Sort by the current axis
    points.sort((a, b) => a[axis] - b[axis])

    const median = Math.floor(points.length / 2)
    const [x, y, z, id] = points[median]

    return {
      point: new Float32Array([x, y, z]),
      id,
      splitAxis: axis,
      left: this.build(points.slice(0, median), depth + 1),
      right: this.build(points.slice(median + 1), depth + 1),
    }
  }

  /**
   * Find the nearest neighbor to a query point.
   * @param qx Query x
   * @param qy Query y
   * @param qz Query z
   * @returns The cell ID of the nearest point, or -1 if tree is empty
   */
  nearest(qx: number, qy: number, qz: number): number {
    if (!this.root) return -1

    let bestId = -1
    let bestDist = Infinity

    const search = (node: KDNode | null) => {
      if (!node) return

      const dx = qx - node.point[0]
      const dy = qy - node.point[1]
      const dz = qz - node.point[2]
      const dist = dx * dx + dy * dy + dz * dz

      if (dist < bestDist) {
        bestDist = dist
        bestId = node.id
      }

      // Distance to the splitting plane
      const axis = node.splitAxis
      const diff = axis === 0 ? dx : axis === 1 ? dy : dz

      // Search the side of the split that contains the query point first
      const first = diff <= 0 ? node.left : node.right
      const second = diff <= 0 ? node.right : node.left

      search(first)

      // Only search the other side if the splitting plane is closer than best
      if (diff * diff < bestDist) {
        search(second)
      }
    }

    search(this.root)
    return bestId
  }
}

/**
 * Build a KD-tree from VoronoiCell-like objects with x, y, z properties.
 */
export function buildCellKDTree(
  cells: Array<{ id: number; x?: number; y?: number; z?: number; lon: number; lat: number }>,
): KDTree3D {
  const points: Array<[number, number, number, number]> = cells.map((c) => {
    // Use 3D Cartesian if available, otherwise convert from lon/lat
    let x: number, y: number, z: number
    if (c.x !== undefined && c.y !== undefined && c.z !== undefined) {
      x = c.x
      y = c.y
      z = c.z
    } else {
      const lonRad = (c.lon * Math.PI) / 180
      const latRad = (c.lat * Math.PI) / 180
      const cosLat = Math.cos(latRad)
      x = cosLat * Math.cos(lonRad)
      y = Math.sin(latRad)
      z = cosLat * Math.sin(lonRad)
    }
    return [x, y, z, c.id]
  })

  return new KDTree3D(points)
}
