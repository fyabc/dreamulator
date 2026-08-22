/**
 * LanguageSwitcher — dropdown to switch the UI language.
 *
 * Persists the choice to localStorage and defaults to the browser language on
 * first load (see i18n/index.ts getInitialLanguage).
 */

import { useTranslation } from 'react-i18next'
import { LANGUAGE_STORAGE_KEY, SUPPORTED_LANGUAGES } from '../i18n'

export default function LanguageSwitcher() {
  const { i18n } = useTranslation()

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const lng = e.target.value
    void i18n.changeLanguage(lng)
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, lng)
    } catch {
      // Ignore storage errors (private mode) — the in-memory switch still works.
    }
  }

  return (
    <select
      value={i18n.language}
      onChange={handleChange}
      aria-label="Language"
      className="w-full mt-2 px-2 py-1 rounded bg-space-surface text-xs text-gray-400 border border-space-border hover:text-gray-200 focus:outline-none focus:border-neon-cyan"
    >
      {SUPPORTED_LANGUAGES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  )
}
