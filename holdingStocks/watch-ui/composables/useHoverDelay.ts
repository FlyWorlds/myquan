/** 鼠标悬停 delayMs 后显示，移出短暂延迟后隐藏（便于移入浮层）。 */
export function useHoverDelay(delayMs: number | (() => number) = 1000, leaveMs = 220) {
  const show = ref(false)
  let enterTimer: ReturnType<typeof setTimeout> | null = null
  let leaveTimer: ReturnType<typeof setTimeout> | null = null

  function clearTimers() {
    if (enterTimer) {
      clearTimeout(enterTimer)
      enterTimer = null
    }
    if (leaveTimer) {
      clearTimeout(leaveTimer)
      leaveTimer = null
    }
  }

  function onEnter() {
    if (leaveTimer) {
      clearTimeout(leaveTimer)
      leaveTimer = null
    }
    if (show.value) return
    const wait = typeof delayMs === 'function' ? delayMs() : delayMs
    enterTimer = setTimeout(() => {
      show.value = true
      enterTimer = null
    }, Math.max(0, wait))
  }

  function onLeave() {
    if (enterTimer) {
      clearTimeout(enterTimer)
      enterTimer = null
    }
    leaveTimer = setTimeout(() => {
      show.value = false
      leaveTimer = null
    }, leaveMs)
  }

  function onPanelEnter() {
    if (leaveTimer) {
      clearTimeout(leaveTimer)
      leaveTimer = null
    }
  }

  function onPanelLeave() {
    onLeave()
  }

  function dismiss() {
    clearTimers()
    show.value = false
  }

  onUnmounted(clearTimers)

  return { show, onEnter, onLeave, onPanelEnter, onPanelLeave, dismiss }
}
