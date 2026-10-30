<script setup lang="ts">
const props = defineProps<{ text?: string }>()
const opened = ref(false)
const tooltip = ref<HTMLElement | null>(null)
const tooltipId = useId()
const position = ref({ left: '12px', top: '12px' })
let anchor: HTMLElement | null = null

async function show(event: MouseEvent | FocusEvent) {
  if (!props.text) return
  anchor = event.currentTarget as HTMLElement
  const box = anchor.getBoundingClientRect()
  position.value = { left: `${Math.max(12, Math.min(box.left, window.innerWidth - 372))}px`, top: `${box.bottom + 8}px` }
  opened.value = true
  await nextTick()
  if (!opened.value || !tooltip.value || !anchor) return
  const size = tooltip.value.getBoundingClientRect()
  position.value = {
    left: `${Math.max(12, Math.min(box.left, window.innerWidth - size.width - 12))}px`,
    top: `${Math.max(12, box.bottom + 8 + size.height > window.innerHeight - 12 ? box.top - size.height - 8 : box.bottom + 8)}px`,
  }
}
function hide() { opened.value = false; anchor = null }
onMounted(() => {
  window.addEventListener('scroll', hide, true)
  window.addEventListener('resize', hide)
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', hide, true)
  window.removeEventListener('resize', hide)
})
</script>

<template>
  <span
    class="inline-flex"
    :tabindex="text ? 0 : undefined"
    :aria-describedby="opened && text ? tooltipId : undefined"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
    @keydown.esc="hide"
  >
    <slot />
    <Teleport to="body">
      <div
        v-if="opened && text"
        :id="tooltipId"
        ref="tooltip"
        role="tooltip"
        class="card pointer-events-none fixed z-[10000] w-[360px] max-w-[calc(100vw-24px)] space-y-1.5 border border-accent/40 px-3 py-2.5 text-left text-xs leading-relaxed text-ui-text shadow-2xl"
        :style="position"
      >
        <p v-for="(line, index) in text.split('\n')" :key="index" class="break-words" :class="index === 0 ? 'font-semibold text-accent' : 'text-ui-text-2'">{{ line }}</p>
      </div>
    </Teleport>
  </span>
</template>
