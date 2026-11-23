/** Build version plus the short commit hash when the build had git metadata. */
export default function VersionStamp({ label }: { label?: string }) {
  return (
    <span title={__GIT_COMMIT__ ? `commit ${__GIT_COMMIT__}` : undefined}>
      {label ? `${label} ` : ''}v{__APP_VERSION__}
      {__GIT_COMMIT__ && <span className="text-gray-500"> · {__GIT_COMMIT__}</span>}
    </span>
  )
}
