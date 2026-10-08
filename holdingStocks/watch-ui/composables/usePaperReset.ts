export function usePaperReset() {
  const resetting = ref(false)
  const error = ref('')

  async function resetPaper(confirmText?: string) {
    const ok = window.confirm(
      confirmText
      || '确认清空全部纸面持仓并重置账户到默认资金？\n当日成交会归档；交割单历史保留。此操作不可撤销。',
    )
    if (!ok) return null
    resetting.value = true
    error.value = ''
    try {
      const res = await fetch('/api/holdings/reset', { method: 'POST' })
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean
        error?: string
        account_total?: number
        session?: string
      }
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      return data
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      return null
    } finally {
      resetting.value = false
    }
  }

  return { resetting, error, resetPaper }
}
