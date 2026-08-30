import type { RouterConfig } from '@nuxt/schema'

export default {
  scrollBehavior(to) {
    if (to.hash) {
      return { el: to.hash, behavior: 'smooth', top: 80 }
    }
    return { top: 0 }
  },
} satisfies RouterConfig
