/**
 * i18n — internationalisation scaffold.
 *
 * ## Namespace design
 *
 * | Namespace | Domain | Example key |
 * |-----------|--------|-------------|
 * | `common`  | Shared UI (nav, buttons, status) | `common:nav.home` |
 * | `map`     | Map viewer + globe (layers, controls, labels) | `map:layer.terrain` |
 * | `worlds`  | World management (CRUD, build, branch) | `worlds:action.newWorld` |
 * | `help`    | Help page (sections, content) — future |
 *
 * ## Adding a new language
 *
 * 1. Copy `src/i18n/locales/zh-CN/` → `src/i18n/locales/<code>/`
 * 2. Translate each JSON file (keys MUST stay identical)
 * 3. Add to `resources` below
 * 4. Add to `SUPPORTED_LANGUAGES` array
 *
 * ## Using translations in components
 *
 * ```tsx
 * import { useTranslation } from 'react-i18next'
 * function MyComponent() {
 *   const { t } = useTranslation('common')
 *   return <button>{t('action.create')}</button>
 * }
 * ```
 *
 * The default namespace is `common`, so `useTranslation()` without arguments
 * also works for common keys.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import commonZh from './locales/zh-CN/common.json'
import mapZh from './locales/zh-CN/map.json'
import worldsZh from './locales/zh-CN/worlds.json'
import civmapZh from './locales/zh-CN/civmap.json'
import helpZh from './locales/zh-CN/help.json'
import commonEn from './locales/en/common.json'
import mapEn from './locales/en/map.json'
import worldsEn from './locales/en/worlds.json'
import civmapEn from './locales/en/civmap.json'
import helpEn from './locales/en/help.json'

/** Languages with at least partial translation coverage. */
export const SUPPORTED_LANGUAGES = [
  { code: 'zh-CN', label: '简体中文' },
  { code: 'en', label: 'English' },
] as const

/** localStorage key for the persisted UI language. */
export const LANGUAGE_STORAGE_KEY = 'dreamulator-lang'

/** Resolve the initial language: saved choice → browser preference → zh-CN. */
function getInitialLanguage(): string {
  try {
    const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (saved) return saved
    if (navigator.language?.toLowerCase().startsWith('zh')) return 'zh-CN'
    return 'en'
  } catch {
    // localStorage / navigator unavailable (SSR, private mode) — default.
    return 'zh-CN'
  }
}

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { common: commonZh, map: mapZh, worlds: worldsZh, civmap: civmapZh, help: helpZh },
    en: { common: commonEn, map: mapEn, worlds: worldsEn, civmap: civmapEn, help: helpEn },
  },
  lng: getInitialLanguage(),
  fallbackLng: 'zh-CN',
  defaultNS: 'common',
  ns: ['common', 'map', 'worlds', 'civmap', 'help'],
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
  // Show keys in development so missing translations are obvious.
  parseMissingKeyHandler: (key: string) => {
    if (import.meta.env.DEV) return `⚠${key}`
    return key
  },
})

export default i18n
