<script setup lang="ts">
const { show, onEnter, onLeave, onPanelEnter, onPanelLeave } = useHoverDelay(500)

const wrapRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})
const panelPlacement = ref<'above' | 'below'>('below')

const NAV_SAFE_TOP = 56
const PANEL_GAP = 8
const VIEWPORT_MARGIN = 16
const PANEL_WIDTH = 384
const MIN_PANEL_H = 160

function updatePanelPosition() {
  const wrap = wrapRef.value
  const panel = panelRef.value
  if (!wrap || !panel || !show.value) return

  const card = wrap.getBoundingClientRect()
  const width = Math.min(PANEL_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2)
  const viewportBottom = window.innerHeight - VIEWPORT_MARGIN

  let left = card.right - width
  left = Math.max(VIEWPORT_MARGIN, Math.min(left, window.innerWidth - width - VIEWPORT_MARGIN))

  const spaceAbove = card.top - NAV_SAFE_TOP - PANEL_GAP
  const spaceBelow = viewportBottom - card.bottom - PANEL_GAP
  const preferAbove = spaceAbove >= spaceBelow && spaceAbove >= MIN_PANEL_H

  let top = 0
  let maxHeight = 0

  if (preferAbove && spaceAbove >= MIN_PANEL_H) {
    panelPlacement.value = 'above'
    maxHeight = Math.max(MIN_PANEL_H, Math.floor(spaceAbove))
    top = card.top - PANEL_GAP - maxHeight
    if (top < NAV_SAFE_TOP) {
      top = NAV_SAFE_TOP
      maxHeight = Math.max(MIN_PANEL_H, Math.floor(card.top - PANEL_GAP - NAV_SAFE_TOP))
    }
  } else {
    panelPlacement.value = 'below'
    top = card.bottom + PANEL_GAP
    maxHeight = Math.max(MIN_PANEL_H, Math.floor(viewportBottom - top))
  }

  // 保证浮层完全落在视口内，内部 body 滚动
  maxHeight = Math.max(MIN_PANEL_H, Math.min(maxHeight, Math.floor(viewportBottom - top)))

  panelStyle.value = {
    top: `${top}px`,
    left: `${left}px`,
    width: `${width}px`,
    height: `${maxHeight}px`,
    maxHeight: `${maxHeight}px`,
  }
}

function bindPositionListeners() {
  window.addEventListener('scroll', updatePanelPosition, true)
  window.addEventListener('resize', updatePanelPosition)
}

function unbindPositionListeners() {
  window.removeEventListener('scroll', updatePanelPosition, true)
  window.removeEventListener('resize', updatePanelPosition)
}

watch(show, async (visible) => {
  if (!visible) {
    unbindPositionListeners()
    return
  }
  await nextTick()
  updatePanelPosition()
  requestAnimationFrame(updatePanelPosition)
  bindPositionListeners()
})

onUnmounted(unbindPositionListeners)

function onWrapLeave(e: MouseEvent) {
  const rel = e.relatedTarget
  if (rel instanceof Node && panelRef.value?.contains(rel)) return
  onLeave()
}

function onDetailLeave(e: MouseEvent) {
  const rel = e.relatedTarget
  if (rel instanceof Node && wrapRef.value?.contains(rel)) return
  onPanelLeave()
}
</script>

<template>
  <div
    ref="wrapRef"
    class="registry-hover-wrap relative"
    :class="{ 'registry-hover-active': show }"
    @mouseenter="onEnter"
    @mouseleave="onWrapLeave"
    @focusin="onEnter"
    @focusout="onLeave"
  >
    <article
      class="registry-card card overflow-hidden border border-ui-hairline p-0 transition"
      :class="{ 'registry-card-active': show }"
      tabindex="0"
    >
      <div class="p-3">
        <slot name="compact" />
        <p class="mt-2 text-xs text-ui-text-3">悬停 0.5 秒查看详细说明</p>
      </div>
    </article>

    <Teleport to="body">
      <Transition name="registry-detail">
        <div
          v-if="show"
          ref="panelRef"
          class="registry-detail-panel"
          :class="`registry-detail-panel--${panelPlacement}`"
          :style="panelStyle"
          role="tooltip"
          @mouseenter="onPanelEnter"
          @mouseleave="onDetailLeave"
        >
          <div class="registry-detail-panel-body">
            <slot name="detail" />
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
