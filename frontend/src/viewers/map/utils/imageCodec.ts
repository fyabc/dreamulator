/**
 * Image codec utilities — decode PNG blobs to typed arrays for GPU upload.
 *
 * In the browser, we use an offscreen Canvas to decode the PNG, then
 * extract the pixel data.  For 16-bit elevation data we use the
 * single-channel red channel from the decoded RGBA image.
 */

import * as THREE from 'three'
import { generateAdaptiveTerrainScale } from './colorScales'

/**
 * Decode a PNG Blob to a Float32Array with normalised [0, 1] values.
 *
 * Uses an Image element + Canvas to decode the PNG, then extracts
 * the red channel as a single-channel float array.
 *
 * @param blob PNG file blob.
 * @returns Promise of { data, width, height }.
 */
export async function decodePngToFloat32(
  blob: Blob,
): Promise<{ data: Float32Array; width: number; height: number }> {
  const bitmap = await createImageBitmap(blob)
  const { width, height } = bitmap

  // Decode via offscreen canvas
  const canvas = new OffscreenCanvas(width, height)
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(bitmap, 0, 0)
  const imageData = ctx.getImageData(0, 0, width, height)

  // Extract red channel (first byte of each RGBA pixel) as normalised float
  const rgba = imageData.data
  const floats = new Float32Array(width * height)
  for (let i = 0; i < width * height; i++) {
    // For 16-bit PNGs loaded via Canvas, the value may be in the high byte
    // or split across R and G channels.  Use R as primary.
    floats[i] = rgba[i * 4] / 255
  }

  bitmap.close()
  return { data: floats, width, height }
}

/**
 * Encode a Float32Array (normalised [0, 1]) to a PNG Blob.
 *
 * Creates a canvas, writes the data as grayscale RGBA, and exports as PNG.
 * Note: Canvas only supports 8-bit per channel, so this is lossy for 16-bit
 * elevation data.  For full 16-bit precision, the backend should handle encoding.
 *
 * @param data Normalised elevation values.
 * @param width Image width.
 * @param height Image height.
 * @returns PNG Blob.
 */
export async function encodeFloat32ToPng(
  data: Float32Array,
  width: number,
  height: number,
): Promise<Blob> {
  const canvas = new OffscreenCanvas(width, height)
  const ctx = canvas.getContext('2d')!
  const imageData = ctx.createImageData(width, height)

  for (let i = 0; i < data.length; i++) {
    const v = Math.max(0, Math.min(255, Math.round(data[i] * 255)))
    imageData.data[i * 4 + 0] = v // R
    imageData.data[i * 4 + 1] = v // G
    imageData.data[i * 4 + 2] = v // B
    imageData.data[i * 4 + 3] = 255 // A
  }

  ctx.putImageData(imageData, 0, 0)
  return canvas.convertToBlob({ type: 'image/png' })
}

/**
 * Create a simple thumbnail from elevation data.
 *
 * @param data Normalised elevation values.
 * @param width Source width.
 * @param height Source height.
 * @param thumbWidth Desired thumbnail width.
 * @param seaLevel Normalised sea level for land/sea coloring.
 * @returns Data URL of the thumbnail.
 */
export function createThumbnail(
  data: Float32Array,
  width: number,
  height: number,
  thumbWidth: number = 256,
  seaLevel: number = 0.4,
): string {
  const scale = thumbWidth / width
  const thumbHeight = Math.round(height * scale)
  const canvas = document.createElement('canvas')
  canvas.width = thumbWidth
  canvas.height = thumbHeight
  const ctx = canvas.getContext('2d')!
  const imageData = ctx.createImageData(thumbWidth, thumbHeight)

  for (let ty = 0; ty < thumbHeight; ty++) {
    for (let tx = 0; tx < thumbWidth; tx++) {
      const sx = Math.min(width - 1, Math.round(tx / scale))
      const sy = Math.min(height - 1, Math.round(ty / scale))
      const val = data[sy * width + sx]

      let r: number, g: number, b: number
      if (val < seaLevel) {
        // Water: dark to medium blue
        const depth = val / seaLevel
        r = Math.round(10 + depth * 30)
        g = Math.round(30 + depth * 70)
        b = Math.round(80 + depth * 90)
      } else {
        // Land: green to brown to white
        const landT = (val - seaLevel) / (1 - seaLevel)
        if (landT < 0.4) {
          r = Math.round(60 + landT * 150)
          g = Math.round(130 + landT * 50)
          b = Math.round(40 + landT * 50)
        } else if (landT < 0.8) {
          r = Math.round(120 + (landT - 0.4) * 200)
          g = Math.round(100 + (landT - 0.4) * 100)
          b = Math.round(60 + (landT - 0.4) * 150)
        } else {
          r = Math.round(200 + (landT - 0.8) * 275)
          g = Math.round(200 + (landT - 0.8) * 275)
          b = Math.round(210 + (landT - 0.8) * 225)
        }
      }

      const idx = (ty * thumbWidth + tx) * 4
      imageData.data[idx] = r
      imageData.data[idx + 1] = g
      imageData.data[idx + 2] = b
      imageData.data[idx + 3] = 255
    }
  }

  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}

/**
 * Generate a low-resolution planet texture from elevation data using the
 * adaptive hypsometric colour scale.
 *
 * Used by the stellar system viewer (Route C) to display real terrain colours
 * on planet spheres instead of procedural solid colours.
 *
 * @param elevation  Normalised [0, 1] elevation Float32Array (width × height).
 * @param srcW       Source image width (pixels).
 * @param srcH       Source image height (pixels).
 * @param elevMinM   Minimum elevation in metres.
 * @param elevMaxM   Maximum elevation in metres.
 * @param seaLevelM  Sea level in metres.
 * @param thumbW     Desired texture width (height = thumbW × srcH / srcW).
 * @returns A THREE.DataTexture suitable for `.map` on a sphere material.
 */
export function generatePlanetTexture(
  elevation: Float32Array,
  srcW: number,
  srcH: number,
  elevMinM: number,
  elevMaxM: number,
  seaLevelM: number,
  thumbW = 256,
): THREE.DataTexture {
  const thumbH = Math.max(1, Math.round(thumbW * (srcH / srcW)))
  const lut = generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevelM)
  const buf = new Uint8Array(thumbW * thumbH * 4)

  const scaleX = (srcW - 1) / thumbW
  const scaleY = (srcH - 1) / thumbH

  for (let ty = 0; ty < thumbH; ty++) {
    const sy = Math.round(ty * scaleY)
    const rowOff = sy * srcW
    const tRowOff = ty * thumbW * 4
    for (let tx = 0; tx < thumbW; tx++) {
      const sx = Math.round(tx * scaleX)
      const elev = elevation[rowOff + sx]
      const lutIdx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
      const pi = tRowOff + tx * 4
      buf[pi] = lut[lutIdx * 4]
      buf[pi + 1] = lut[lutIdx * 4 + 1]
      buf[pi + 2] = lut[lutIdx * 4 + 2]
      buf[pi + 3] = 255
    }
  }

  const tex = new THREE.DataTexture(
    buf as unknown as BufferSource, thumbW, thumbH, THREE.RGBAFormat,
  )
  tex.flipY = true
  tex.colorSpace = THREE.NoColorSpace
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping
  tex.minFilter = THREE.LinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.needsUpdate = true
  return tex
}
