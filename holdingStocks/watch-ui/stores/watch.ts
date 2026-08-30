import { defineStore } from 'pinia'
import { shallowRef, ref } from 'vue'
import type { StrategyTab, WatchSnapshot } from '~/types/snapshot'

function readPrivacyHidden(): boolean {
  if (!import.meta.client) return false
  return localStorage.getItem('holdings_privacy_hidden') === '1'
}

export const useWatchStore = defineStore('watch', () => {
  const snapshot = shallowRef<WatchSnapshot | null>(null)
  const strategies = ref<StrategyTab[]>([])
  const wsStatus = ref('连接中…')
  const privacyHidden = ref(readPrivacyHidden())

  function setSnapshot(data: WatchSnapshot) {
    snapshot.value = data
    if (data.strategies?.length) {
      strategies.value = data.strategies
    }
  }

  function setStrategies(list: StrategyTab[]) {
    strategies.value = list
  }

  function setWsStatus(msg: string) {
    wsStatus.value = msg
  }

  function togglePrivacy() {
    privacyHidden.value = !privacyHidden.value
    if (import.meta.client) {
      localStorage.setItem('holdings_privacy_hidden', privacyHidden.value ? '1' : '0')
    }
  }

  const wsDisconnected = computed(
    () =>
      wsStatus.value.includes('断开') ||
      wsStatus.value.includes('重连') ||
      wsStatus.value.includes('不可用'),
  )

  return {
    snapshot,
    strategies,
    wsStatus,
    wsDisconnected,
    privacyHidden,
    setSnapshot,
    setStrategies,
    setWsStatus,
    togglePrivacy,
  }
})
