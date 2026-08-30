import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { StrategyTab, WatchSnapshot } from '~/types/snapshot'

function readPrivacyHidden(): boolean {
  if (!import.meta.client) return false
  return localStorage.getItem('holdings_privacy_hidden') === '1'
}

export const useWatchStore = defineStore('watch', () => {
  const snapshot = ref<WatchSnapshot | null>(null)
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

  function togglePrivacy() {
    privacyHidden.value = !privacyHidden.value
    if (import.meta.client) {
      localStorage.setItem('holdings_privacy_hidden', privacyHidden.value ? '1' : '0')
    }
  }

  return { snapshot, strategies, wsStatus, privacyHidden, setSnapshot, setStrategies, togglePrivacy }
})
