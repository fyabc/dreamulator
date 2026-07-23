/**
 * GlobeViewer — 3D globe visualisation of planet terrain.
 *
 * Renders an equirectangular terrain texture on a sphere inside an
 * R3F Canvas with OrbitControls.  Supports cell hover / selection
 * via raycasting + KD-tree (same pipeline as 2D MapViewer).
 *
 * Interaction:
 *   - Left drag: rotate
 *   - Right drag / Ctrl+drag: pan
 *   - Scroll: zoom
 *   - Hover: cell info via onCellHover callback
 *   - Double-click: select cell via onCellClick callback
 *   - Zoom out far enough → "转入星系视图" transition → onTransition
 */

import { Suspense, useRef, useState, useEffect, useCallback, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars, Text } from '@react-three/drei'
import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPHERE_RADIUS = 1
const TRANSITION_START_DIST = 4.5
const TRANSITION_END_DIST = 8
const DIST_POLL_MS = 80

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GlobeViewerProps {
  /** Equirectangular terrain texture (2:1). */
  texture: THREE.Texture | null
  /** Called when the zoom-out transition completes. */
  onTransition?: () => void
  /** Transition prompt label. */
  transitionLabel?: string
  /** Called when the cursor moves over the globe. */
  onCellHover?: (lon: number, lat: number) => void
  /** Called on double-click with the cursor's lon/lat. */
  onCellClick?: (lon: number, lat: number) => void
  /** Selected cell positions (unit sphere xyz) for marker rendering. */
  selectedCellPositions?: [number, number, number][]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert a 3D point on the unit sphere to lon/lat (degrees). */
function sphereToLonLat(point: THREE.Vector3): { lon: number; lat: number } {
  const y = THREE.MathUtils.clamp(point.y, -1, 1)
  const lat = Math.asin(y) * THREE.MathUtils.RAD2DEG
  const lon = Math.atan2(point.z, point.x) * THREE.MathUtils.RAD2DEG
  return { lon, lat }
}

// ---------------------------------------------------------------------------
// Scene (inside Canvas)
// ---------------------------------------------------------------------------

interface GlobeSceneProps {
  texture: THREE.Texture | null
  distanceRef: React.MutableRefObject<number>
  onCellHover?: (lon: number, lat: number) => void
  onCellClick?: (lon: number, lat: number) => void
  selectedCellPositions?: [number, number, number][]
}

/** Picks on the sphere and reports lon/lat.  Wrapped in its own component
 *  so `useThree()` gives us the correct R3F context. */
function SphereInteraction({
  onCellHover,
  onCellClick,
}: {
  onCellHover?: (lon: number, lat: number) => void
  onCellClick?: (lon: number, lat: number) => void
}) {
  const sphereRef = useRef<THREE.Mesh>(null)

  const handlePointerMove = useCallback(
    (e: any) => {
      const pt = e.point as THREE.Vector3 | undefined
      if (pt) {
        const { lon, lat } = sphereToLonLat(pt)
        onCellHover?.(lon, lat)
      }
    },
    [onCellHover],
  )

  const handleDoubleClick = useCallback(
    (e: any) => {
      const pt = e.point as THREE.Vector3 | undefined
      if (pt) {
        const { lon, lat } = sphereToLonLat(pt)
        onCellClick?.(lon, lat)
      }
    },
    [onCellClick],
  )

  return (
    <mesh
      ref={sphereRef}
      visible={false}
      onPointerMove={handlePointerMove}
      onDoubleClick={handleDoubleClick}
    >
      <sphereGeometry args={[SPHERE_RADIUS * 1.01, 32, 16]} />
      <meshBasicMaterial visible={false} />
    </mesh>
  )
}

// ---------------------------------------------------------------------------
// Graticule — latitude / longitude lines on the sphere
// ---------------------------------------------------------------------------

const GRID_STEP = 30
const GRID_COLOR = 'rgba(255,255,255,0.12)'
const GRID_R = SPHERE_RADIUS * 1.003

function Graticule() {
  const lines = useMemo(() => {
    const result: { points: [number, number, number][]; key: string }[] = []

    // Latitude lines (circles parallel to equator)
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      const phi = THREE.MathUtils.degToRad(lat)
      const r = GRID_R * Math.cos(phi)
      const y = GRID_R * Math.sin(phi)
      const pts: [number, number, number][] = []
      for (let i = 0; i <= 128; i++) {
        const theta = (i / 128) * Math.PI * 2
        pts.push([r * Math.cos(theta), y, r * Math.sin(theta)])
      }
      result.push({ points: pts, key: `lat-${lat}` })
    }

    // Longitude lines (great circles through poles)
    for (let lon = -180; lon < 180; lon += GRID_STEP) {
      const theta = THREE.MathUtils.degToRad(lon)
      const pts: [number, number, number][] = []
      for (let i = 0; i <= 128; i++) {
        const phi = (i / 128) * Math.PI         // 0 (north) → π (south)
        const r = GRID_R * Math.sin(phi)
        const y = GRID_R * Math.cos(phi)
        pts.push([r * Math.cos(theta), y, r * Math.sin(theta)])
      }
      result.push({ points: pts, key: `lon-${lon}` })
    }

    return result
  }, [])

  return (
    <group>
      {lines.map(({ points, key }) => (
        <line key={key}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              array={new Float32Array(points.flat())}
              count={points.length}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={GRID_COLOR} transparent opacity={0.25} depthTest={true} />
        </line>
      ))}
    </group>
  )
}

// ---------------------------------------------------------------------------
// Polar axis — red N / blue S markers
// ---------------------------------------------------------------------------

const AXIS_R = SPHERE_RADIUS * 1.08

function PolarAxis() {
  const axisPoints = useMemo(() => new Float32Array([
    0, -AXIS_R, 0,
    0, AXIS_R, 0,
  ]), [])

  return (
    <group>
      {/* Axis line */}
      <line>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            array={axisPoints}
            count={2}
            itemSize={3}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#444466" transparent opacity={0.5} />
      </line>

      {/* North marker (red) */}
      <mesh position={[0, AXIS_R, 0]}>
        <coneGeometry args={[0.025, 0.08, 8, 4]} />
        <meshBasicMaterial color="#e53935" />
      </mesh>
      <Text
        position={[0, AXIS_R + 0.1, 0]}
        fontSize={0.12}
        color="#e53935"
        anchorX="center" anchorY="middle"
        font={undefined}  // use default
      >
        N
      </Text>

      {/* South marker (blue) */}
      <mesh position={[0, -AXIS_R, 0]} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[0.025, 0.08, 8, 4]} />
        <meshBasicMaterial color="#42a5f5" />
      </mesh>
      <Text
        position={[0, -AXIS_R - 0.1, 0]}
        fontSize={0.12}
        color="#42a5f5"
        anchorX="center" anchorY="middle"
        font={undefined}
      >
        S
      </Text>
    </group>
  )
}

// ---------------------------------------------------------------------------
// Scene (inside Canvas)
// ---------------------------------------------------------------------------

function GlobeScene({
  texture,
  distanceRef,
  onCellHover,
  onCellClick,
  selectedCellPositions,
}: GlobeSceneProps) {
  const controlsRef = useRef<any>(null)

  useFrame(({ camera }) => {
    distanceRef.current = camera.position.length()
  })

  return (
    <>
      <Stars radius={50} depth={30} count={2000} factor={4} saturation={0} fade speed={0.2} />
      <ambientLight intensity={0.25} />
      <directionalLight position={[5, 2, 5]} intensity={1.2} />

      {/* Visible planet sphere */}
      <mesh>
        <sphereGeometry args={[SPHERE_RADIUS, 64, 32]} />
        {texture ? (
          <meshStandardMaterial map={texture} roughness={0.9} metalness={0.05} />
        ) : (
          <meshStandardMaterial color="#4488aa" roughness={0.8} metalness={0.1} />
        )}
      </mesh>

      {/* Invisible hit-target sphere for raycasting */}
      <SphereInteraction onCellHover={onCellHover} onCellClick={onCellClick} />

      {/* Selected cell markers */}
      {selectedCellPositions?.map((pos, i) => (
        <mesh key={i} position={[pos[0] * 1.012, pos[1] * 1.012, pos[2] * 1.012]}>
          <sphereGeometry args={[0.008, 8, 4]} />
          <meshBasicMaterial color="#f0c040" />
        </mesh>
      ))}

      {/* Graticule (lat/lon lines) */}
      <Graticule />

      {/* Polar axis + N/S markers */}
      <PolarAxis />

      {/* Atmosphere shell */}
      <mesh scale={1.015}>
        <sphereGeometry args={[SPHERE_RADIUS, 48, 24]} />
        <meshBasicMaterial
          color={new THREE.Color(0.4, 0.6, 1.0)}
          transparent opacity={0.08}
          side={THREE.BackSide} depthWrite={false}
        />
      </mesh>

      <OrbitControls
        ref={controlsRef}
        enableDamping dampingFactor={0.08}
        minDistance={SPHERE_RADIUS * 1.05}
        maxDistance={TRANSITION_END_DIST}
        maxPolarAngle={Math.PI * 0.85}
        target={[0, 0, 0]}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Transition overlay (outside Canvas)
// ---------------------------------------------------------------------------

function TransitionPrompt({ progress, label }: { progress: number; label: string }) {
  if (progress <= 0) return null
  const pct = Math.round(progress * 100)
  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
      <div className="flex flex-col items-center gap-2">
        <span className="text-xs text-neon-cyan/80 tracking-wider animate-pulse">{label}</span>
        <div className="w-48 h-1.5 rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-neon-cyan/60 to-neon-cyan transition-[width] duration-75 ease-linear"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[10px] text-gray-500 font-mono tabular-nums">{pct}%</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GlobeViewer({
  texture,
  onTransition,
  transitionLabel = '转入星系视图',
  onCellHover,
  onCellClick,
  selectedCellPositions,
}: GlobeViewerProps) {
  const distanceRef = useRef(TRANSITION_START_DIST - 1)
  const [progress, setProgress] = useState(0)
  const navigateRef = useRef(false)

  useEffect(() => {
    const interval = setInterval(() => {
      const dist = distanceRef.current
      if (dist <= TRANSITION_START_DIST) { setProgress(0); return }
      const p = Math.min(1, (dist - TRANSITION_START_DIST) / (TRANSITION_END_DIST - TRANSITION_START_DIST))
      setProgress(p)
      if (p >= 1 && onTransition && !navigateRef.current) {
        navigateRef.current = true
        setTimeout(() => onTransition(), 300)
      }
      if (p < 0.98) navigateRef.current = false
    }, DIST_POLL_MS)
    return () => clearInterval(interval)
  }, [onTransition])

  useEffect(() => { setProgress(0); navigateRef.current = false }, [texture])

  return (
    <div className="w-full relative" style={{ height: '70vh', minHeight: '500px' }}>
      <TransitionPrompt progress={progress} label={transitionLabel} />
      <Suspense fallback={<div className="flex items-center justify-center h-full text-gray-500">加载 3D 地球...</div>}>
        <Canvas
          camera={{ position: [0, 0, 2.8], fov: 40 }}
          gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.0 }}
          style={{ background: '#030308', borderRadius: '0.75rem' }}
        >
          <GlobeScene
            texture={texture}
            distanceRef={distanceRef}
            onCellHover={onCellHover}
            onCellClick={onCellClick}
            selectedCellPositions={selectedCellPositions}
          />
        </Canvas>
      </Suspense>
    </div>
  )
}
