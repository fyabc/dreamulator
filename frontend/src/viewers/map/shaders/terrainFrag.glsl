uniform sampler2D uElevation;   // 16-bit heightmap as R channel
uniform sampler2D uColorRamp;   // 1D LUT: normalised elevation → RGB
uniform float uSeaLevel;         // normalised sea level [0, 1]
uniform float uHillshadeStrength; // 0..1
uniform float uWaterDepthFactor;  // how much deeper water gets darker

varying vec2 vUv;

// Sample elevation at a UV offset (for hillshading)
float sampleElev(vec2 uv, vec2 offset, vec2 texelSize) {
  vec2 sampleUv = clamp(uv + offset * texelSize, vec2(0.0), vec2(1.0));
  return texture2D(uElevation, sampleUv).r;
}

void main() {
  float elev = texture2D(uElevation, vUv).r;

  // ---- Base color from color ramp ----
  vec3 baseColor = texture2D(uColorRamp, vec2(elev, 0.5)).rgb;

  // ---- Hillshading ----
  vec2 texelSize = vec2(1.0) / vec2(textureSize(uElevation, 0));
  float dx = sampleElev(vUv, vec2(1.0, 0.0), texelSize)
           - sampleElev(vUv, vec2(-1.0, 0.0), texelSize);
  float dy = sampleElev(vUv, vec2(0.0, 1.0), texelSize)
           - sampleElev(vUv, vec2(0.0, -1.0), texelSize);

  // Light from NW (45° azimuth, 45° altitude)
  vec3 lightDir = normalize(vec3(-1.0, 1.0, 1.0));
  vec3 normal = normalize(vec3(-dx * uHillshadeStrength * 8.0,
                                -dy * uHillshadeStrength * 8.0,
                                1.0));
  float shade = max(dot(normal, lightDir), 0.0);
  shade = 0.4 + 0.6 * shade; // ambient + diffuse

  vec3 color = baseColor * shade;

  // ---- Water depth darkening ----
  if (elev < uSeaLevel) {
    float depth = (uSeaLevel - elev) / max(uSeaLevel, 0.001);
    color *= mix(1.0, 1.0 - uWaterDepthFactor, depth);

    // Slight specular highlight on water surface
    float spec = pow(max(dot(normal, lightDir), 0.0), 32.0);
    color += vec3(0.05, 0.08, 0.12) * spec;
  }

  gl_FragColor = vec4(color, 1.0);
}
