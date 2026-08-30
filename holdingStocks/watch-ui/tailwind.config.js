/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
    './app.vue',
  ],
  theme: {
    extend: {
      colors: {
        ui: {
          surface: 'var(--ui-surface)',
          page: 'var(--ui-page)',
          ink: 'var(--ui-ink)',
          text: 'var(--ui-text)',
          'text-2': 'var(--ui-text-2)',
          'text-3': 'var(--ui-text-3)',
          hairline: 'var(--ui-hairline)',
          'hairline-strong': 'var(--ui-hairline-strong)',
          'fill-hover': 'var(--ui-fill-hover)',
          'fill-active': 'var(--ui-fill-active)',
          danger: 'var(--ui-danger)',
        },
        accent: 'var(--watch-accent)',
        up: 'var(--watch-up)',
        down: 'var(--watch-down)',
        line: 'var(--ui-hairline-strong)',
        muted: 'var(--ui-text-2)',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
      },
      boxShadow: {
        ui: 'var(--ui-shadow)',
        'ui-lg': 'var(--ui-shadow-lg)',
      },
      transitionTimingFunction: {
        ui: 'var(--ui-ease)',
      },
    },
  },
  plugins: [],
}
