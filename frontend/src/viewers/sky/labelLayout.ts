/** labelLayout — greedy collision-free placement for chart labels (pure).
 *
 * Each label is tried at a ring of candidate offsets around its marker; the
 * first offset whose estimated text box misses every reserved box wins.
 * Reserved boxes start as the static obstacles (cardinals, zenith caption)
 * plus all marker discs, and grow with each placed label.  When every offset
 * collides the label keeps the first (above) offset — a crowded sky still
 * names its bodies, and priority order decides who moves.
 */

export interface LabelItem {
  id: string
  /** marker centre in chart coordinates */
  x: number
  y: number
  /** marker disc radius */
  radius: number
  text: string
  fontSize: number
}

export interface Box {
  left: number
  top: number
  right: number
  bottom: number
}

export interface LabelPlacement {
  /** text x offset from the marker centre, in the anchor's sense */
  dx: number
  /** text baseline offset from the marker centre */
  dy: number
  anchor: 'start' | 'middle' | 'end'
}

/** Rough advance width: CJK glyphs are ~1 em, Latin ~0.58 em. */
export function estimateTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (const ch of text) width += ch.codePointAt(0)! > 0x2e80 ? fontSize : fontSize * 0.58
  return width
}

function textBox(item: LabelItem, placement: LabelPlacement): Box {
  const width = estimateTextWidth(item.text, item.fontSize)
  const cx = item.x + placement.dx
  const baseline = item.y + placement.dy
  const left =
    placement.anchor === 'middle' ? cx - width / 2 : placement.anchor === 'end' ? cx - width : cx
  return {
    left,
    right: left + width,
    top: baseline - item.fontSize * 0.8,
    bottom: baseline + item.fontSize * 0.25,
  }
}

function discBox(item: LabelItem): Box {
  return { left: item.x - item.radius, top: item.y - item.radius, right: item.x + item.radius, bottom: item.y + item.radius }
}

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
}

function candidates(radius: number): LabelPlacement[] {
  const side = radius + 7
  return [
    { dx: 0, dy: -(radius + 5), anchor: 'middle' },
    { dx: side, dy: -(radius + 2), anchor: 'start' },
    { dx: side, dy: 4, anchor: 'start' },
    { dx: side, dy: radius + 10, anchor: 'start' },
    { dx: 0, dy: radius + 15, anchor: 'middle' },
    { dx: -side, dy: -(radius + 2), anchor: 'end' },
    { dx: -side, dy: 4, anchor: 'end' },
    { dx: -side, dy: radius + 10, anchor: 'end' },
  ]
}

/**
 * Place labels greedily.  `items` must already be in priority order (most
 * important first — selected, hovered, then brightest); early items claim
 * their preferred offset and later items move around them.
 */
export function layoutLabels(items: LabelItem[], obstacles: Box[]): Map<string, LabelPlacement> {
  const reserved: Box[] = [...obstacles]
  for (const item of items) reserved.push(discBox(item))
  const placements = new Map<string, LabelPlacement>()
  for (const item of items) {
    const options = candidates(item.radius)
    let chosen = options[0]
    for (const option of options) {
      if (!reserved.some((box) => overlaps(textBox(item, option), box))) {
        chosen = option
        break
      }
    }
    placements.set(item.id, chosen)
    reserved.push(textBox(item, chosen))
  }
  return placements
}
