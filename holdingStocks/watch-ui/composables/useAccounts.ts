import { ref, computed } from 'vue'
import type { AccountProfile } from '~/types/snapshot'

const accounts = ref<AccountProfile[]>([])
const activeAccountId = ref<string>('acc_default')
const loadingAccounts = ref(false)
let initialized = false

export function useAccounts() {
  function initActiveAccount() {
    if (initialized) return
    initialized = true
    if (import.meta.client) {
      const saved = localStorage.getItem('myquan_active_account_id')
      if (saved) {
        activeAccountId.value = saved
      }
    }
  }

  async function fetchAccounts(): Promise<AccountProfile[]> {
    loadingAccounts.value = true
    try {
      const res = await $fetch<{ accounts: AccountProfile[]; active_account_id?: string }>('/api/accounts')
      if (res && Array.isArray(res.accounts)) {
        accounts.value = res.accounts
        // 如果 localStorage 中没有设定，则跟随服务端
        if (import.meta.client && !localStorage.getItem('myquan_active_account_id') && res.active_account_id) {
          activeAccountId.value = res.active_account_id
        }
      }
      return accounts.value
    } catch (e) {
      console.warn('[Accounts] 获取账户列表失败:', e)
      return accounts.value
    } finally {
      loadingAccounts.value = false
    }
  }

  async function switchAccount(aid: string) {
    if (!aid) return
    activeAccountId.value = aid
    if (import.meta.client) {
      localStorage.setItem('myquan_active_account_id', aid)
    }
    try {
      await $fetch('/api/accounts/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: { account_id: aid },
      })
    } catch (e) {
      console.warn('[Accounts] 同步活跃账户失败:', e)
    }
  }

  const activeAccount = computed(() => {
    return accounts.value.find((a) => a.id === activeAccountId.value) || accounts.value[0] || null
  })

  const isSubAccount = computed(() => {
    return Boolean(activeAccountId.value && activeAccountId.value !== 'acc_default')
  })

  return {
    accounts,
    activeAccountId,
    loadingAccounts,
    activeAccount,
    isSubAccount,
    initActiveAccount,
    fetchAccounts,
    switchAccount,
  }
}
