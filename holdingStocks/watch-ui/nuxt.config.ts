// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  ssr: false,
  modules: ['@pinia/nuxt', '@nuxtjs/tailwindcss'],
  css: ['~/assets/css/main.css'],
  tailwindcss: {
    cssPath: '~/assets/css/main.css',
  },
  devtools: { enabled: false },
  app: {
    head: {
      title: '持仓盯盘',
      htmlAttrs: { lang: 'zh-CN' },
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      script: [
        {
          key: 'theme-init',
          innerHTML:
            "(function(){try{var s=localStorage.getItem('holdings_ui_scheme');document.documentElement.setAttribute('data-ui-scheme',s==='light'?'light':'dark')}catch(e){document.documentElement.setAttribute('data-ui-scheme','dark')}})();",
          tagPriority: 'critical',
        },
      ],
    },
  },
  vite: {
    server: {
      proxy: {
        '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
        '/api': { target: 'http://127.0.0.1:8765' },
        '/holdings_watch.json': { target: 'http://127.0.0.1:8765' },
      },
    },
  },
  compatibilityDate: '2025-08-30',
})
