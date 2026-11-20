import { useEffect, useState } from 'react'
import { generateAdaptiveTerrainScale } from '../map/utils/colorScales'
import type { ElevationRaster } from './elevationRaster'

export function useElevationPreview(raster: ElevationRaster | null, min: number, max: number, sea: number) {
  const [base, setBase] = useState<{ url: string } | null>(null)
  useEffect(() => {
    setBase(null)
    if (!raster) return
    const canvas = document.createElement('canvas')
    canvas.width = raster.width
    canvas.height = raster.height
    const context = canvas.getContext('2d')
    if (!context) return
    const image = context.createImageData(raster.width, raster.height)
    const lut = generateAdaptiveTerrainScale(min, max, sea)
    const bins = lut.length / 4 - 1
    raster.values.forEach((height, index) => {
      const offset = 4 * Math.round(bins * Math.max(0, Math.min(1, (height - min) / (max - min || 1))))
      image.data[index * 4] = lut[offset]
      image.data[index * 4 + 1] = lut[offset + 1]
      image.data[index * 4 + 2] = lut[offset + 2]
      image.data[index * 4 + 3] = 255
    })
    context.putImageData(image, 0, 0)
    let active = true
    let url: string | undefined
    canvas.toBlob((blob) => {
      if (!active || !blob) return
      url = URL.createObjectURL(blob)
      setBase({ url })
    })
    return () => { active = false; if (url) URL.revokeObjectURL(url) }
  }, [raster, min, max, sea])
  return base
}
