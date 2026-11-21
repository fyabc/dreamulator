# Earth relief illustration

The homepage globe uses the NOAA ETOPO1 global relief model (Amante and Eakins, 2009, DOI `10.7289/V5C8276M`). It is an illustration, not a map layer or simulation result. The input is a 4096 × 2048, 16-bit elevation raster from the Earth reference workflow. The orthographic view starts at 24.10° N, 121.45° E and completes one rotation in 32 seconds. The page uses `earth-relief.webp` as both the first frame and the reduced-motion fallback. The renderer projects 60 distinct views per second into a silent 640 × 640 MP4, so the homepage does not need a WebGL scene.

The homepage displays the still while it downloads the complete video. The player then reads from a browser-local object URL, so it does not make network requests while playing or looping.

Run the following command from the repository root with `ffmpeg` installed, substituting the path to the Earth reference elevation raster:

```sh
uv run python scripts/media/render_home_earth.py /path/to/earth-heightmap.png frontend/src/assets \
  --min-m -10765.70718582069 --max-m 7487.436824468134
```
