<script setup lang="ts">
const { show, onEnter, onLeave, onPanelEnter, onPanelLeave } = useHoverDelay(1000)
</script>

<template>
  <div
    class="registry-hover-wrap relative"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
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
        <p class="mt-2 text-xs text-ui-text-3">悬停 1 秒查看详细说明</p>
      </div>
    </article>

    <Transition name="registry-detail">
      <div
        v-if="show"
        class="registry-detail-panel"
        role="tooltip"
        @mouseenter="onPanelEnter"
        @mouseleave="onPanelLeave"
      >
        <slot name="detail" />
      </div>
    </Transition>
  </div>
</template>
