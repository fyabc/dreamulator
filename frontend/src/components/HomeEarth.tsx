import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import earthRelief from '../assets/earth-relief.webp'
import earthRotation from '../assets/earth-rotation.mp4'
import AtlasIcon from './AtlasIcon'

const reducedMotionQuery = '(prefers-reduced-motion: reduce)'

async function downloadRotation(signal: AbortSignal) {
  const response = await fetch(earthRotation, { signal })
  if (!response.ok) throw new Error(`Earth rotation download failed (${response.status})`)
  return response.blob()
}

export default function HomeEarth() {
  const { t } = useTranslation('common')
  const video = useRef<HTMLVideoElement>(null)
  const userPaused = useRef(false)
  const [posterReady, setPosterReady] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia(reducedMotionQuery).matches)
  const [mediaFailed, setMediaFailed] = useState(false)
  const [mediaReady, setMediaReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [hasStarted, setHasStarted] = useState(false)
  const canAnimate = !reducedMotion && !mediaFailed

  useEffect(() => {
    const preference = matchMedia(reducedMotionQuery)
    const update = () => {
      setReducedMotion(preference.matches)
      if (preference.matches) {
        setMediaReady(false)
        setPlaying(false)
        setHasStarted(false)
      }
    }
    preference.addEventListener('change', update)
    return () => preference.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    const player = video.current
    if (!canAnimate || !posterReady || !player) return

    const download = new AbortController()
    let localSource: string | undefined
    let downloadStarted = false
    let visible = false
    const syncPlayback = () => {
      if (!visible || document.hidden || userPaused.current) {
        player.pause()
        return
      }
      if (!downloadStarted) {
        downloadStarted = true
        void downloadRotation(download.signal).then(blob => {
          if (download.signal.aborted) return
          localSource = URL.createObjectURL(blob)
          player.src = localSource
        }).catch(() => {
          if (!download.signal.aborted) setMediaFailed(true)
        })
      }
      if (localSource && player.paused && player.readyState >= player.HAVE_FUTURE_DATA) {
        void player.play().catch(() => undefined)
      }
    }
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      syncPlayback()
    })
    observer.observe(player)
    player.addEventListener('canplay', syncPlayback)
    document.addEventListener('visibilitychange', syncPlayback)
    return () => {
      observer.disconnect()
      player.removeEventListener('canplay', syncPlayback)
      document.removeEventListener('visibilitychange', syncPlayback)
      download.abort()
      player.pause()
      if (localSource) {
        player.removeAttribute('src')
        player.load()
        URL.revokeObjectURL(localSource)
      }
    }
  }, [canAnimate, posterReady])

  const toggleRotation = () => {
    const player = video.current
    if (!player?.hasAttribute('src')) return
    userPaused.current = !player.paused
    if (userPaused.current) {
      player.pause()
    } else {
      void player.play().catch(() => undefined)
    }
  }

  const imageDescription = t('home.atlas.imageDescription')

  return (
    <figure className="atlas-hero-figure">
      <div className="atlas-hero-globe">
        <img src={earthRelief} alt={imageDescription} width={960} height={960} fetchPriority="high"
          onLoad={() => setPosterReady(true)} onError={() => setPosterReady(true)} />
        {canAnimate && (
          <>
            <video ref={video} className={hasStarted ? 'atlas-rotation-started' : undefined}
              muted loop playsInline preload="auto" aria-hidden="true"
              onCanPlay={() => setMediaReady(true)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
              onPlaying={() => setHasStarted(true)} onError={() => setMediaFailed(true)} />
            {mediaReady && (
              <button type="button" className="atlas-rotation-control" onClick={toggleRotation}
                aria-label={t(playing ? 'home.atlas.pauseRotation' : 'home.atlas.playRotation')}>
                <AtlasIcon name={playing ? 'pause' : 'play'} className="size-4" />
              </button>
            )}
          </>
        )}
      </div>
    </figure>
  )
}
