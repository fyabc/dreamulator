/**
 * GlobeViewer — 3D globe visualisation of planet terrain.
 *
 * Renders an equirectangular terrain texture on a sphere inside an
 * R3F Canvas with OrbitControls.  Shares the same rendering stack
 * as StellarSystemViewer (R3F + drei), making future integration
 * (Route A: planet ↔ solar-system zoom transition) straightforward.
 *
 * Interaction:
 *   - Left drag: rotate
 *   - Right drag / Ctrl+drag: pan
 *   - Scroll: zoom
 */

import { Suspense, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GlobeViewerProps {
  /** Pre-computed equirectangular terrain texture (2:1 aspect ratio). */
  texture: THREE.Texture | null
}

interface GlobeSceneProps {
  texture: THREE.Texture | null
}

function GlobeScene({ texture }: GlobeSceneProps) {
  const controlsRef = useRef<any>(null)
  const sphereRadius = 1

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
        <sphereGeometry args={[sphereRadius, 64, 32]} />
        {texture ? (
          <meshStandardMaterial map={texture} roughness={0.9} metalness={0.05} />
        ) : (
          <meshStandardMaterial color="#4488aa" roughness={0.8} metalness={0.1} />
        )}
      </mesh>

      {/* Thin atmosphere rim (back-side transparent shell) */}
      <mesh scale={1.015}>
        <sphereGeometry args={[sphereRadius, 48, 24]} />
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
        minDistance={sphereRadius * 1.05}
        maxDistance={sphereRadius * 8}
        maxPolarAngle={Math.PI * 0.85} // prevent going exactly to poles
        target={[0, 0, 0]}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GlobeViewer({ texture }: GlobeViewerProps) {
  return (
    <div className="w-full" style={{ height: '70vh', minHeight: '500px' }}>
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
          <GlobeScene texture={texture} />
        </Canvas>
      </Suspense>
    </div>
  )
}
