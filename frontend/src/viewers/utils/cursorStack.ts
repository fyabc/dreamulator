/**
 * Shared cursor-state tracker — prevents races between multiple Three.js meshes
 * that all try to control document.body.style.cursor.
 *
 * Usage:
 *   onPointerOver: CursorStack.enter('pointer')
 *   onPointerOut:  CursorStack.leave()
 */

let _stack = 0
const _default = typeof document !== 'undefined' ? document.body.style.cursor : ''

export const CursorStack = {
  enter(cursor: string) {
    _stack++
    document.body.style.cursor = cursor
  },
  leave() {
    _stack = Math.max(0, _stack - 1)
    if (_stack === 0) {
      document.body.style.cursor = _default
    }
  },
}
