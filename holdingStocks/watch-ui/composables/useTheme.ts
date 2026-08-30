import type { UiScheme } from '~/types/theme'
import { UI_SCHEME_STORAGE_KEY } from '~/types/theme'

function readStoredScheme(): UiScheme {
  if (!import.meta.client) return 'dark'
  try {
    return localStorage.getItem(UI_SCHEME_STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function useTheme() {
  const scheme = useState<UiScheme>('ui-scheme', readStoredScheme)

  const isDark = computed(() => scheme.value === 'dark')

  function applyScheme(next: UiScheme) {
    scheme.value = next
    if (!import.meta.client) return
    document.documentElement.setAttribute('data-ui-scheme', next)
    try {
      localStorage.setItem(UI_SCHEME_STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
  }

  function initScheme() {
    applyScheme(readStoredScheme())
  }

  function toggleScheme() {
    applyScheme(scheme.value === 'dark' ? 'light' : 'dark')
  }

  return { scheme, isDark, applyScheme, initScheme, toggleScheme }
}
