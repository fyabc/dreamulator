

## 🗺️ Terrain Data

Terrain generation output for **earth** · planet `earth` · branch `terrain-dev`.

```
terrain-dev/
└── layers/geological/input/maps/earth/
    ├── elevation.png      ← heightmap (16-bit PNG)
    ├── cvt_mesh.json      ← spherical Voronoi mesh
    ├── plates.json        ← tectonic plate definitions
    ├── metadata.json      ← pipeline parameters
    └── timeline/          ← time-evolution snapshots (when enabled)
```

### Quick access

```bash
# Open in file explorer
dreamulator terrain open earth --planet earth --branch terrain-dev

# View info
dreamulator terrain info earth --planet earth --branch terrain-dev
```
