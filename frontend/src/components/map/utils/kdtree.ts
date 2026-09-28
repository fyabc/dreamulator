/**
 * Minimal k-d tree for fast nearest-neighbor queries in 3D space.
 *
 * Used for cell hit-testing on the map viewer — replaces the SVG polygon
 * hit-test layer that creates thousands of DOM nodes.
 *
 * Build: O(n log²n) (per-level median split), Query: O(log n) average.
 *
 * Storage is flat typed arrays (points, ids, child links) instead of a node
 * object graph — measured 2026-09-29 (200k cells, 8.4M queries): build −40%
 * vs the node-graph version, query −15% (the recursive search is kept: it
 * prunes the far side with the post-near best distance, which a
 * push-time-pruned iterative stack cannot match — that variant measured 3.7×
 * slower). `buildCellKDTree` additionally memoizes on the cells array
 * identity — the map bake and the hover pickers all pass the same
 * `cvtMesh.cells` reference, so the tree is built once per mesh instead of
 * once per consumer.
 */

const NO_NODE = -1

export class KDTree3D {
  private pts: Float32Array // 3n: x, y, z per point
  private ids: Int32Array // cell ID per point
  private left: Int32Array // node links (point i owns node i)
  private right: Int32Array
  private axis: Int8Array
  private root = NO_NODE
  private alive = false
  /** Per-axis index comparators (built once; sort() takes no extra args). */
  private cmp: Array<(a: number, b: number) => number>
  // Query temps — nearest() is not reentrant (single-threaded, no nesting).
  private _qx = 0
  private _qy = 0
  private _qz = 0
  private _bId = -1
  private _bD = Infinity

  /**
   * Build a KD-tree from an array of 3D points.
   * @param points Array of [x, y, z, id] tuples
   */
  constructor(points: Array<[number, number, number, number]>) {
    const n = points.length
    this.pts = new Float32Array(n * 3)
    this.ids = new Int32Array(n)
    this.left = new Int32Array(n)
    this.right = new Int32Array(n)
    this.axis = new Int8Array(n)
    this.cmp = [
      (a, b) => this.pts[a * 3] - this.pts[b * 3],
      (a, b) => this.pts[a * 3 + 1] - this.pts[b * 3 + 1],
      (a, b) => this.pts[a * 3 + 2] - this.pts[b * 3 + 2],
    ]
    if (n === 0) return
    this.alive = true

    const idx = new Int32Array(n)
    for (let i = 0; i < n; i++) {
      const p = points[i]
      this.pts[i * 3] = p[0]
      this.pts[i * 3 + 1] = p[1]
      this.pts[i * 3 + 2] = p[2]
      this.ids[i] = p[3]
      idx[i] = i
    }
    this.root = this.buildRange(idx, 0, n, 0)
  }

  /** Recursively split the index range [lo, hi) on `depth % 3`; returns node index. */
  private buildRange(idx: Int32Array, lo: number, hi: number, depth: number): number {
    if (lo >= hi) return NO_NODE
    const axis = depth % 3
    // Sorting a subarray view sorts the underlying buffer — no copies.
    idx.subarray(lo, hi).sort(this.cmp[axis])
    const median = lo + ((hi - lo) >> 1)
    const node = idx[median]
    this.axis[node] = axis
    this.left[node] = this.buildRange(idx, lo, median, depth + 1)
    this.right[node] = this.buildRange(idx, median + 1, hi, depth + 1)
    return node
  }

  /**
   * Find the nearest neighbor to a query point.
   *
   * Recursive over flat node indices: no per-call closure allocation, and
   * the far side is only searched when the splitting plane is closer than
   * the best distance found inside the near subtree (tight pruning).
   *
   * @param qx Query x
   * @param qy Query y
   * @param qz Query z
   * @returns The cell ID of the nearest point, or -1 if tree is empty
   */
  nearest(qx: number, qy: number, qz: number): number {
    if (!this.alive) return -1
    this._qx = qx
    this._qy = qy
    this._qz = qz
    this._bId = -1
    this._bD = Infinity
    this.searchNode(this.root)
    return this._bId
  }

  private searchNode(node: number): void {
    if (node === NO_NODE) return
    const p3 = node * 3
    const dx = this._qx - this.pts[p3]
    const dy = this._qy - this.pts[p3 + 1]
    const dz = this._qz - this.pts[p3 + 2]
    const dist = dx * dx + dy * dy + dz * dz
    if (dist < this._bD) {
      this._bD = dist
      this._bId = this.ids[node]
    }
    const ax = this.axis[node]
    const diff = ax === 0 ? dx : ax === 1 ? dy : dz
    const near = diff <= 0 ? this.left[node] : this.right[node]
    const far = diff <= 0 ? this.right[node] : this.left[node]
    this.searchNode(near)
    if (far !== NO_NODE && diff * diff < this._bD) {
      this.searchNode(far)
    }
  }
}

/** Single-entry memo: all consumers pass the same `cvtMesh.cells` reference. */
let _treeCache: { cells: Array<{ id: number; lon: number; lat: number }>; tree: KDTree3D } | null =
  null

/**
 * Build a KD-tree from VoronoiCell-like objects with x, y, z properties.
 * Memoized on the cells array identity — repeated calls with the same array
 * (map bake + hover pickers) return the shared instance.
 */
export function buildCellKDTree(
  cells: Array<{ id: number; x?: number; y?: number; z?: number; lon: number; lat: number }>,
): KDTree3D {
  if (_treeCache && _treeCache.cells === cells) {
    return _treeCache.tree
  }
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

  const tree = new KDTree3D(points)
  _treeCache = { cells, tree }
  return tree
}
