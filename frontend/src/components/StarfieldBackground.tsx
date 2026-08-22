/**
 * StarfieldBackground — shared animated space background.
 *
 * Previously duplicated across HomePage, WorldList, WorldInfo, and WorldDetail.
 * Extracted to a single component so the starfield + nebula CSS effects are
 * defined in one place.
 */

export default function StarfieldBackground() {
  return (
    <>
      <div className="starfield" />
      <div className="nebula" />
    </>
  )
}
