import { useEffect, useState } from 'react'
import type { ElevationRaster } from './elevationRaster'
import { regionFields, type RegionFieldLayer } from './regionPackLayers'

export function useRegionFieldPreview(raster: ElevationRaster | undefined, layer: RegionFieldLayer | undefined) {
  const [preview, setPreview] = useState<{ raster: ElevationRaster; layer: RegionFieldLayer; url: string; pixelated: true }>()
  useEffect(() => {
    if (!raster || !layer) return
    const { range: [min, max], colors } = regionFields[layer]
    const canvas = document.createElement('canvas')
    canvas.width = raster.width
    canvas.height = raster.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const image = ctx.createImageData(raster.width, raster.height)
    const stops = colors.map(color => [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16)))
    for (let index = 0; index < raster.values.length; index++) {
      const value = raster.values[index]
      if (!Number.isFinite(value)) continue
      const position = Math.max(0, Math.min(1, (value - min) / (max - min))) * (stops.length - 1)
      const segment = Math.min(Math.floor(position), stops.length - 2)
      const fraction = position - segment
      for (let component = 0; component < 3; component++) {
        const start = stops[segment][component]
        image.data[index * 4 + component] = start + fraction * (stops[segment + 1][component] - start)
      }
      image.data[index * 4 + 3] = 255
    }
    ctx.putImageData(image, 0, 0)
    let url: string | undefined
    let cancelled = false
    canvas.toBlob(blob => {
      if (!blob || cancelled) return
      url = URL.createObjectURL(blob)
      setPreview({ raster, layer, url, pixelated: true })
    })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [raster, layer])
  return preview && preview.raster === raster && preview.layer === layer ? preview : null
}
