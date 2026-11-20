import { resizeElevation, type ElevationRaster } from './elevationRaster'

function radixTwo(real: Float64Array, imag: Float64Array, inverse = false) {
  const size = real.length
  for (let index = 1, reversed = 0; index < size; index++) {
    let bit = size >> 1
    for (; reversed & bit; bit >>= 1) reversed ^= bit
    reversed ^= bit
    if (index < reversed) {
      const savedReal = real[index], savedImag = imag[index]
      real[index] = real[reversed]
      imag[index] = imag[reversed]
      real[reversed] = savedReal
      imag[reversed] = savedImag
    }
  }
  for (let length = 2; length <= size; length *= 2) {
    const angle = (inverse ? 2 : -2) * Math.PI / length
    const half = length / 2
    for (let offset = 0; offset < half; offset++) {
      const cos = Math.cos(angle * offset), sin = Math.sin(angle * offset)
      for (let first = offset; first < size; first += length) {
        const second = first + half
        const re = cos * real[second] - sin * imag[second]
        const im = sin * real[second] + cos * imag[second]
        real[second] = real[first] - re
        imag[second] = imag[first] - im
        real[first] += re
        imag[first] += im
      }
    }
  }
  if (inverse) for (let index = 0; index < size; index++) {
    real[index] /= size
    imag[index] /= size
  }
}

function makeForwardFft(size: number) {
  if ((size & (size - 1)) === 0) return radixTwo
  const length = 2 ** Math.ceil(Math.log2(2 * size - 1))
  const workReal = new Float64Array(length), workImag = new Float64Array(length)
  const kernelReal = new Float64Array(length), kernelImag = new Float64Array(length)
  const cos = Float64Array.from({ length: size }, (_, index) => Math.cos(Math.PI * index * index / size))
  const sin = Float64Array.from({ length: size }, (_, index) => Math.sin(Math.PI * index * index / size))
  kernelReal[0] = 1
  for (let index = 1; index < size; index++) {
    kernelReal[index] = kernelReal[length - index] = cos[index]
    kernelImag[index] = kernelImag[length - index] = sin[index]
  }
  radixTwo(kernelReal, kernelImag)
  return (real: Float64Array, imag: Float64Array) => {
    workReal.fill(0, size)
    workImag.fill(0, size)
    for (let index = 0; index < size; index++) {
      workReal[index] = real[index] * cos[index] + imag[index] * sin[index]
      workImag[index] = imag[index] * cos[index] - real[index] * sin[index]
    }
    radixTwo(workReal, workImag)
    for (let index = 0; index < length; index++) {
      const re = workReal[index], im = workImag[index]
      workReal[index] = re * kernelReal[index] - im * kernelImag[index]
      workImag[index] = im * kernelReal[index] + re * kernelImag[index]
    }
    radixTwo(workReal, workImag, true)
    for (let index = 0; index < size; index++) {
      real[index] = workReal[index] * cos[index] + workImag[index] * sin[index]
      imag[index] = workImag[index] * cos[index] - workReal[index] * sin[index]
    }
  }
}

function makeCosineTransform(size: number) {
  const fft = makeForwardFft(size)
  const real = new Float64Array(size), imag = new Float64Array(size)
  const cos = Float64Array.from({ length: size }, (_, index) => Math.cos(Math.PI * index / (2 * size)))
  const sin = Float64Array.from({ length: size }, (_, index) => Math.sin(Math.PI * index / (2 * size)))
  const order = Int32Array.from({ length: size }, (_, index) => index % 2 ? size - (index + 1) / 2 : index / 2)
  return (values: Float32Array, start: number, stride: number, inverse: boolean) => {
    if (inverse) {
      for (let index = 0; index < size; index++) {
        const value = values[start + index * stride]
        const opposite = index === 0 ? 0 : values[start + (size - index) * stride]
        real[index] = value * cos[index] + opposite * sin[index]
        imag[index] = opposite * cos[index] - value * sin[index]
      }
    } else {
      imag.fill(0)
      for (let index = 0; index < size; index++) real[order[index]] = values[start + index * stride]
    }
    fft(real, imag)
    for (let index = 0; index < size; index++) {
      values[start + index * stride] = inverse
        ? real[order[index]] / size : real[index] * cos[index] + imag[index] * sin[index]
    }
  }
}

function coastDistances(source: ElevationRaster, sea: number) {
  const { width, height, values } = source
  const horizontal = new Float32Array(values.length)
  for (let row = 0; row < height; row++) {
    let last = -1
    for (let col = 0; col < width; col++) {
      const index = row * width + col
      if (values[index] <= sea) last = col
      horizontal[index] = (col - last) ** 2
    }
    last = width
    for (let col = width - 1; col >= 0; col--) {
      const index = row * width + col
      if (values[index] <= sea) last = col
      horizontal[index] = Math.min(horizontal[index], (last - col) ** 2)
    }
  }
  const sites = new Int32Array(height)
  const boundaries = new Float64Array(height + 1)
  return (col: number, visit: (index: number, distance: number) => void) => {
    let count = 0
    boundaries[0] = -Infinity
    boundaries[1] = Infinity
    for (let row = 1; row < height; row++) {
      let crossing: number
      do {
        const previous = sites[count]
        crossing = (horizontal[row * width + col] - horizontal[previous * width + col]) / (2 * (row - previous)) + (row + previous) / 2
        if (crossing > boundaries[count]) break
        count--
      } while (count >= 0)
      sites[++count] = row
      boundaries[count] = crossing
      boundaries[count + 1] = Infinity
    }
    count = 0
    for (let row = 0; row < height; row++) {
      while (boundaries[count + 1] < row) count++
      const nearest = sites[count]
      visit(row * width + col, Math.min(Math.sqrt((row - nearest) ** 2 + horizontal[nearest * width + col]), row + 1, height - row))
    }
  }
}

export async function blendTerrain(input: ElevationRaster, donor: ElevationRaster, pixelKm: number, preserveKm: number, sea: number,
  checkpoint: () => Promise<void>) {
  const { width, height } = donor
  const source = resizeElevation(input, width, height)
  const delta = donor.values.map((value, index) => value - source.values[index])
  const horizontal = makeCosineTransform(width)
  const vertical = width === height ? horizontal : makeCosineTransform(height)
  for (let row = 0; row < height; row++) {
    if (row % 64 === 0) await checkpoint()
    horizontal(delta, row * width, 1, false)
  }
  for (let col = 0; col < width; col++) {
    if (col % 64 === 0) await checkpoint()
    vertical(delta, col, width, false)
    for (let row = 0; row < height; row++) {
      const frequency = Math.hypot(col / width, row / height) / (2 * pixelKm)
      const weight = Math.max(0, Math.min(1, frequency * preserveKm - 1))
      delta[row * width + col] *= 0.5 - 0.5 * Math.cos(Math.PI * weight)
    }
    vertical(delta, col, width, true)
  }
  for (let row = 0; row < height; row++) {
    if (row % 64 === 0) await checkpoint()
    horizontal(delta, row * width, 1, true)
  }
  const coastDistance = coastDistances(source, sea)
  for (let col = 0; col < width; col++) {
    if (col % 64 === 0) await checkpoint()
    coastDistance(col, (index, distance) => {
      const original = source.values[index]
      const fade = Math.min(1, Math.max(distance - 1, 0) * pixelKm / (preserveKm / 2))
      const value = Math.fround(original + fade * fade * (3 - 2 * fade) * delta[index])
      delta[index] = original > sea && value > sea ? value : original
    })
  }
  return { width, height, values: delta }
}
