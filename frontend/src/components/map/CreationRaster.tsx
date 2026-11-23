import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import { heightmapDisplayScale, heightmapGrid, heightmapStats, type HeightmapInput, type HeightmapMapping,
  type SavedTemperature } from '../../projects/heightmapWorld'
import { generateLut, TEMPERATURE_LIMIT_C, TEMPERATURE_SCALE } from '../../viewers/map/utils/colorScales'

export default function CreationRaster({ input, mapping, temperature, width = 720 }: {
  input: HeightmapInput; mapping: HeightmapMapping; temperature?: SavedTemperature; width?: number
}) {
  const { t, i18n } = useTranslation('worlds')
  const canvas = useRef<HTMLCanvasElement>(null)
  const [month, setMonth] = useState(temperature ? 'annual' : 'terrain')
  const series = !temperature || month === 'terrain' ? undefined : month === 'annual'
    ? temperature.annual : temperature.monthly[Number(month)]
  const renderWidth = series ? GRID_W : Math.min(width, input.raster.width)
  const renderHeight = series ? GRID_H : renderWidth / 2
  const scale = useMemo(() => heightmapDisplayScale(input, mapping), [input, mapping])
  const stats = useMemo(() => heightmapStats(input, mapping), [input, mapping])
  const { minM: elevMinM, maxM: elevMaxM, seaLevelM } = scale
  useEffect(() => {
    const context = canvas.current?.getContext('2d')
    if (!context) return
    const image = context.createImageData(renderWidth, renderHeight)
    const terrain = series ? undefined : heightmapGrid(input, mapping, renderWidth, renderHeight)
    const lut = generateLut(TEMPERATURE_SCALE, 256)
    for (let index = 0; index < renderWidth * renderHeight; index++) {
      const pixel = index * 4
      if (series) {
        const norm = (series[index] / TEMPERATURE_LIMIT_C + 1) / 2
        const color = Math.round(Math.max(0, Math.min(1, norm)) * 255) * 3
        image.data[pixel] = lut[color]
        image.data[pixel + 1] = lut[color + 1]
        image.data[pixel + 2] = lut[color + 2]
      } else if (terrain) {
        const value = terrain.values[index]
        const shade = (value - elevMinM) / (elevMaxM - elevMinM)
        const land = terrain.land[index]
        image.data[pixel] = (land ? 76 : 11) + shade * (land ? 150 : 4)
        image.data[pixel + 1] = (land ? 111 : 28) + shade * (land ? 100 : 48)
        image.data[pixel + 2] = (land ? 72 : 55) + shade * (land ? 132 : 57)
      }
      image.data[pixel + 3] = 255
    }
    context.putImageData(image, 0, 0)
  }, [input, mapping, elevMinM, elevMaxM, renderHeight, renderWidth, series])
  const label = t(series ? 'creation.temperature' : 'creation.terrain')
  const format = new Intl.DateTimeFormat(i18n.language, { month: 'long', timeZone: 'UTC' })
  const number = (value: number) => Math.round(value).toLocaleString(i18n.language)
  return <figure className="min-w-0 space-y-2">
    {temperature && <label className="flex flex-wrap items-center gap-2 text-sm text-gray-200">{t('creation.layer')}
      <select aria-label={t('creation.layer')} value={month} onChange={event => setMonth(event.currentTarget.value)}
        className="min-h-10 rounded border border-space-border bg-space-bg px-2">
        <option value="terrain">{t('creation.terrain')}</option>
        <option value="annual">{t('creation.annual')}</option>
        {Array.from({ length: 12 }, (_, index) => <option key={index} value={index}>{format.format(new Date(Date.UTC(2000, index, 1)))}</option>)}
      </select>
    </label>}
    <canvas ref={canvas} width={renderWidth} height={renderHeight} role="img" aria-label={label}
      className="aspect-[2/1] w-full rounded border border-space-border bg-space-panel" />
    <figcaption className="flex flex-wrap justify-between gap-1 text-sm text-gray-400">
      {series ? <><span>{t('creation.experimentSource', { width: GRID_W, height: GRID_H })}</span><span>−40 °C / +40 °C</span></>
        : <><span>{t('creation.imageSize', { width: input.raster.width, height: input.raster.height, depth: input.raster.depth })}</span>
          <span>{stats
            ? t('creation.terrainStats', { min: number(stats.minM), max: number(stats.maxM),
              land: Math.round(stats.landShare * 100), sea: number(seaLevelM) })
            : t('creation.seaDatum', { value: seaLevelM })}</span></>}
    </figcaption>
  </figure>
}
