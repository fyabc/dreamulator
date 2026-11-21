import { koppenRasterPixels, type KoppenRasterInput } from './koppenDownscale'

self.onmessage = ({ data }: MessageEvent<KoppenRasterInput>) => {
  const pixels = koppenRasterPixels(data)
  self.postMessage(pixels, { transfer: pixels ? [pixels.buffer] : [] })
}
