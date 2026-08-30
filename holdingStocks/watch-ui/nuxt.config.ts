// https://nuxt.com/docs/api/configuration/nuxt-config
const watchApiHost = process.env.WATCH_API_HOST || '127.0.0.1'
const watchApiPort = process.env.WATCH_API_PORT || '8765'
const watchApiOrigin = `http://${watchApiHost}:${watchApiPort}`
const devPort = Number(process.env.NUXT_PORT || process.env.PORT || 3000)

export default defineNuxtConfig({
  ssr: false,
  modules: ['@pinia/nuxt', '@nuxtjs/tailwindcss'],
  css: ['~/assets/css/main.css'],
  tailwindcss: {
    cssPath: '~/assets/css/main.css',
  },
  devtools: { enabled: process.env.NODE_ENV === 'development' },
  runtimeConfig: {
    public: {
      watchApiPort,
      watchApiHost,
    },
  },
  devServer: {
    host: '127.0.0.1',
    port: devPort,
  },
  app: {
    head: {
      title: '持仓盯盘',
      htmlAttrs: { lang: 'zh-CN' },
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'A 股持仓盯盘 · 策略一因子1+2 · WebSocket 实时推送' },
      ],
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
        '/ws': { target: `ws://${watchApiHost}:${watchApiPort}`, ws: true },
        '/api': { target: watchApiOrigin },
        '/holdings_watch.json': { target: watchApiOrigin },
      },
    },
  },
  compatibilityDate: '2025-08-30',
})
