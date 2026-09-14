import { defineStore } from 'pinia'
import { shallowRef, ref, computed } from 'vue'
import type { StrategyTab, WatchSnapshot } from '~/types/snapshot'

function readPrivacyHidden(): boolean {
  if (!import.meta.client) return false
  return localStorage.getItem('holdings_privacy_hidden') === '1'
}

function isFeedAlertStatus(msg: string): boolean {
  return (
    msg.includes('不可用') ||
    msg.includes('行情中断') ||
    msg.includes('网络异常') ||
    msg.includes('服务停滞') ||
    (msg.includes('断开') && !msg.includes('兜底'))
  )
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

  const wsDisconnected = computed(() => isFeedAlertStatus(wsStatus.value))

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
