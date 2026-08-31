/** 鼠标悬停 delayMs 后显示，移出短暂延迟后隐藏（便于移入浮层）。 */
export function useHoverDelay(delayMs = 1000) {
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
    enterTimer = setTimeout(() => {
      show.value = true
      enterTimer = null
    }, delayMs)
  }

  function onLeave() {
    if (enterTimer) {
      clearTimeout(enterTimer)
      enterTimer = null
    }
    leaveTimer = setTimeout(() => {
      show.value = false
      leaveTimer = null
    }, 120)
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
