/**
 * GlobeViewer — 3D globe visualisation of planet terrain.
 *
 * Renders an equirectangular terrain texture on a sphere inside an
 * R3F Canvas with OrbitControls.  Shares the same rendering stack
 * as StellarSystemViewer (R3F + drei).
 *
 * Interaction:
 *   - Left drag: rotate
 *   - Right drag / Ctrl+drag: pan
 *   - Scroll: zoom
 *   - Zoom out far enough → "转入星系视图" progress bar → navigate
 */

import { Suspense, useRef, useState, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPHERE_RADIUS = 1
/** Camera distance at which the transition prompt first appears. */
const TRANSITION_START_DIST = 4.5
/** Camera distance at which the transition completes (max zoom-out). */
const TRANSITION_END_DIST = 8
/** Update interval for reading camera distance (ms). */
const DIST_POLL_MS = 80

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GlobeViewerProps {
  /** Pre-computed equirectangular terrain texture (2:1 aspect ratio). */
  texture: THREE.Texture | null
  /** Called when the zoom-out transition completes (progress hits 100%). */
  onTransition?: () => void
  /** Label shown during the transition prompt. */
  transitionLabel?: string
}

interface GlobeSceneProps {
  texture: THREE.Texture | null
  /** Writable ref — updated each frame with the current camera distance. */
  distanceRef: React.MutableRefObject<number>
}

// ---------------------------------------------------------------------------
// Scene (inside Canvas)
// ---------------------------------------------------------------------------

function GlobeScene({ texture, distanceRef }: GlobeSceneProps) {
  const controlsRef = useRef<any>(null)

  // Read camera distance each frame for the transition UI
  useFrame(({ camera }) => {
    distanceRef.current = camera.position.length()
  })

  return (
    <>
      {/* Starfield background */}
      <Stars radius={50} depth={30} count={2000} factor={4} saturation={0} fade speed={0.2} />

      {/* Subtle ambient so the dark side isn't pitch black */}
      <ambientLight intensity={0.25} />

      {/* Directional "sun" light — gives the globe a realistic day/night terminator */}
      <directionalLight position={[5, 2, 5]} intensity={1.2} />

      {/* The planet sphere */}
      <mesh>
        <sphereGeometry args={[SPHERE_RADIUS, 64, 32]} />
        {texture ? (
          <meshStandardMaterial map={texture} roughness={0.9} metalness={0.05} />
        ) : (
          <meshStandardMaterial color="#4488aa" roughness={0.8} metalness={0.1} />
        )}
      </mesh>

      {/* Thin atmosphere rim (back-side transparent shell) */}
      <mesh scale={1.015}>
        <sphereGeometry args={[SPHERE_RADIUS, 48, 24]} />
        <meshBasicMaterial
          color={new THREE.Color(0.4, 0.6, 1.0)}
          transparent
          opacity={0.08}
          side={THREE.BackSide}
          depthWrite={false}
        />
      </mesh>

      {/* OrbitControls — rotate, zoom, pan */}
      <OrbitControls
        ref={controlsRef}
        enableDamping
        dampingFactor={0.08}
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

function TransitionPrompt({
  progress,
  label,
}: {
  progress: number  // 0..1
  label: string
}) {
  if (progress <= 0) return null

  const pct = Math.round(progress * 100)

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
      <div className="flex flex-col items-center gap-2">
        <span className="text-xs text-neon-cyan/80 tracking-wider animate-pulse">
          {label}
        </span>
        <div className="w-48 h-1.5 rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-neon-cyan/60 to-neon-cyan transition-[width] duration-75 ease-linear"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-[10px] text-gray-500 font-mono tabular-nums">
          {pct}%
        </span>
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
}: GlobeViewerProps) {
  const distanceRef = useRef(TRANSITION_START_DIST - 1)
  const [progress, setProgress] = useState(0)
  const navigateRef = useRef(false)

  // Poll camera distance and compute transition progress
  useEffect(() => {
    const interval = setInterval(() => {
      const dist = distanceRef.current
      if (dist <= TRANSITION_START_DIST) {
        setProgress(0)
        return
      }
      const p = Math.min(1, (dist - TRANSITION_START_DIST) /
        (TRANSITION_END_DIST - TRANSITION_START_DIST))
      setProgress(p)

      // Navigate when progress hits 100% (only once)
      if (p >= 1 && onTransition && !navigateRef.current) {
        navigateRef.current = true
        setTimeout(() => {
          onTransition()
        }, 300)
      }
      // Reset flag when zooming back in
      if (p < 0.98) {
        navigateRef.current = false
      }
    }, DIST_POLL_MS)
    return () => clearInterval(interval)
  }, [onTransition])

  // Reset progress when texture changes (planet switch)
  useEffect(() => {
    setProgress(0)
    navigateRef.current = false
  }, [texture])

  return (
    <div className="w-full relative" style={{ height: '70vh', minHeight: '500px' }}>
      {/* Transition prompt overlay */}
      <TransitionPrompt progress={progress} label={transitionLabel} />

      <Suspense
        fallback={
          <div className="flex items-center justify-center h-full text-gray-500">
            加载 3D 地球...
          </div>
        }
      >
        <Canvas
          camera={{ position: [0, 0, 2.8], fov: 40 }}
          gl={{
            antialias: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.0,
          }}
          style={{ background: '#030308', borderRadius: '0.75rem' }}
        >
          <GlobeScene texture={texture} distanceRef={distanceRef} />
        </Canvas>
      </Suspense>
    </div>
  )
}
