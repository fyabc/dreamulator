/**
 * Earth zonal-mean reference climatology — 2° latitude bands, 90N → 88S.
 *
 * Bundled from the backend ``validate_climate`` ``_ZONAL_TEMP_REF`` /
 * ``_ZONAL_PRECIP_REF``: NCEP/NCAR zonal-mean annual surface air temperature
 * (within ~0.5 °C of ERA5 zonally) and GPCP v2.3 zonal-mean annual
 * precipitation.  These are **Earth observations**, so the ΔT/ΔP error
 * heatmaps are Earth-only diagnostics — a fictional world has no observed
 * reference to diff against.
 */

export const ZONAL_TEMP_REF: number[] = [
  -15, -16, -16, -15, -15, -14, -13, -12, -10, -9, -8, -7, -6, -4, -2, 0, 1, 2, 3, 4, 5, 6, 8,
  10, 11, 13, 14, 15, 16, 18, 19, 21, 23, 24, 24, 25, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26,
  26, 26, 26, 25, 25, 25, 24, 24, 23, 23, 22, 22, 21, 20, 19, 18, 17, 16, 15, 13, 12, 10, 9,
  7, 6, 5, 4, 2, 1, -1, -3, -6, -9, -12, -17, -22, -27, -30, -33, -34, -34, -35, -38, -42,
]

export const ZONAL_PRECIP_REF: number[] = [
  189, 184, 180, 183, 206, 226, 251, 295, 343, 395, 471, 549, 609, 682, 744, 819, 876, 884,
  882, 901, 912, 921, 941, 975, 1006, 1019, 1004, 956, 897, 828, 760, 705, 665, 625, 640, 680,
  738, 820, 982, 1296, 1689, 2030, 2170, 1909, 1611, 1466, 1453, 1493, 1458, 1364, 1214, 1060,
  950, 843, 754, 703, 690, 707, 752, 794, 840, 887, 931, 977, 1036, 1069, 1079, 1074, 1052,
  1024, 1033, 1071, 1120, 1164, 1150, 1055, 900, 717, 553, 467, 381, 312, 284, 250, 200, 160,
  136, 129, 136, 145,
]

/** 2° band index for a latitude — 90N → band 0, 88S → band 89. */
function bandIndex(latDeg: number): number {
  const b = Math.round((90 - latDeg) / 2)
  return Math.max(0, Math.min(89, b))
}

/** Zonal-mean observed annual temperature (°C) at a latitude. */
export function zonalTempAt(latDeg: number): number {
  return ZONAL_TEMP_REF[bandIndex(latDeg)]
}

/** Zonal-mean observed annual precipitation (mm/yr) at a latitude. */
export function zonalPrecipAt(latDeg: number): number {
  return ZONAL_PRECIP_REF[bandIndex(latDeg)]
}
