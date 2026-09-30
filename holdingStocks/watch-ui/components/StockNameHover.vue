<script setup lang="ts">
import type { StockProfile, StockRelated } from '~/types/stockProfile'
import { baiduStockUrl } from '~/utils/stockLink'

const props = defineProps<{
  code?: string | number | null
  name?: string | null
  delayMs?: number
}>()

const { load, peek, digitsOf } = useStockProfile()
const { show, onEnter, onLeave, onPanelEnter, onPanelLeave } = useHoverDelay(
  () => {
    if (props.delayMs != null) return props.delayMs
    return peek(props.code) || profile.value ? 40 : 80
  },
  120,
)

const wrapRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})
const panelPlacement = ref<'above' | 'below'>('below')
const profile = ref<StockProfile | null>(null)
const loading = ref(false)

const codeDigits = computed(() => digitsOf(props.code))
const enabled = computed(() => Boolean(codeDigits.value))

const NAV_SAFE_TOP = 56
const PANEL_GAP = 8
const VIEWPORT_MARGIN = 12
const PANEL_WIDTH = 420
const MIN_PANEL_H = 180

function updatePanelPosition() {
  const wrap = wrapRef.value
  const panel = panelRef.value
  if (!wrap || !panel || !show.value) return

  const card = wrap.getBoundingClientRect()
  const width = Math.min(PANEL_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2)
  const viewportBottom = window.innerHeight - VIEWPORT_MARGIN

  let left = card.left
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

async function hydrate() {
  if (!enabled.value) return
  const cached = peek(codeDigits.value)
  if (cached) {
    profile.value = cached
    return
  }
  if (profile.value || loading.value) return
  loading.value = true
  profile.value = await load(codeDigits.value)
  loading.value = false
  await nextTick()
  updatePanelPosition()
}

function prefetch() {
  if (!enabled.value) return
  const cached = peek(codeDigits.value)
  if (cached) {
    profile.value = cached
    return
  }
  void hydrate()
}

watch(show, async (visible) => {
  if (!visible) {
    unbindPositionListeners()
    return
  }
  void hydrate()
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

function fmtYi(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(2)} 亿`
}

function fmtNum(n?: number | null, d = 2) {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toFixed(d)
}

function fmtChg(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function conceptPath(name: string) {
  return `/sectors/concept/${encodeURIComponent(name)}`
}

const industryList = computed(() => {
  const p = profile.value
  const boards = p?.boards?.industry || []
  if (boards.length) return boards
  return p?.industry ? [p.industry] : []
})

const conceptList = computed(() => {
  const p = profile.value
  const fromBoard = p?.boards?.concept || []
  if (fromBoard.length) return fromBoard
  return (p?.themes || []).map((t) => t.name).filter(Boolean)
})

const chainGroups = computed(() => {
  const chain = profile.value?.chain
  return [
    { label: '上游', items: chain?.upstream || [] },
    { label: '产业链', items: chain?.midstream || [] },
    { label: '下游', items: chain?.downstream || [] },
  ].filter((g) => g.items.length)
})

function relatedKey(r: StockRelated, i: number) {
  return `${r.code}-${r.board}-${i}`
}
</script>

<template>
  <span
    v-if="!enabled"
    class="stock-name-hover-fallback"
  >
    <slot />
  </span>
  <span
    v-else
    ref="wrapRef"
    class="stock-name-hover relative inline-flex max-w-full"
    :class="{ 'stock-name-hover-active': show }"
    @mouseenter="prefetch(); onEnter()"
    @mouseleave="onWrapLeave"
    @focusin="prefetch(); onEnter()"
    @focusout="onLeave"
  >
    <slot />
    <Teleport to="body">
      <Transition name="registry-detail">
        <div
          v-if="show"
          ref="panelRef"
          class="registry-detail-panel stock-profile-panel"
          :class="`registry-detail-panel--${panelPlacement}`"
          :style="panelStyle"
          role="tooltip"
          @mouseenter="onPanelEnter"
          @mouseleave="onDetailLeave"
        >
          <div class="registry-detail-panel-body space-y-3 text-sm">
            <header>
              <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <b class="text-base">{{ profile?.name || name || codeDigits }}</b>
                <span class="text-xs text-ui-text-2">{{ profile?.code || codeDigits }}</span>
                <span v-if="profile?.market" class="text-xs text-ui-text-3">{{ profile.market }}</span>
              </div>
              <p v-if="profile?.full_name" class="mt-0.5 text-xs text-ui-text-3">{{ profile.full_name }}</p>
            </header>

            <p v-if="loading && !profile" class="text-xs text-ui-text-3">加载基本面…</p>
            <p v-else-if="profile?.error" class="text-xs text-ui-text-3">{{ profile.error }}</p>

            <template v-if="profile && !profile.error">
              <section class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <div>
                  <span class="text-ui-text-3">总市值</span>
                  <b class="ml-1 tabular-nums">{{ fmtYi(profile.valuation?.market_cap_yi) }}</b>
                </div>
                <div>
                  <span class="text-ui-text-3">流通市值</span>
                  <b class="ml-1 tabular-nums">{{ fmtYi(profile.valuation?.float_cap_yi) }}</b>
                </div>
                <div>
                  <span class="text-ui-text-3">市盈率</span>
                  <b class="ml-1 tabular-nums">{{ fmtNum(profile.valuation?.pe) }}</b>
                </div>
                <div>
                  <span class="text-ui-text-3">市净率</span>
                  <b class="ml-1 tabular-nums">{{ fmtNum(profile.valuation?.pb) }}</b>
                </div>
                <div>
                  <span class="text-ui-text-3">PE(TTM)</span>
                  <b class="ml-1 tabular-nums">{{ fmtNum(profile.valuation?.pe_ttm) }}</b>
                </div>
                <div>
                  <span class="text-ui-text-3">涨跌</span>
                  <b class="ml-1 tabular-nums">{{ fmtChg(profile.valuation?.chg_pct) }}</b>
                </div>
                <div v-if="profile.registered_capital">
                  <span class="text-ui-text-3">注册资本</span>
                  <b class="ml-1">{{ profile.registered_capital }}</b>
                </div>
                <div v-if="profile.list_date">
                  <span class="text-ui-text-3">上市</span>
                  <b class="ml-1">{{ profile.list_date }}</b>
                </div>
                <div v-if="profile.region">
                  <span class="text-ui-text-3">地区</span>
                  <b class="ml-1">{{ profile.region }}</b>
                </div>
                <div v-if="profile.employees">
                  <span class="text-ui-text-3">员工</span>
                  <b class="ml-1">{{ profile.employees }}</b>
                </div>
              </section>

              <section v-if="industryList.length || profile.csrc_industry">
                <h4 class="mb-1 text-xs font-semibold text-ui-text-2">行业 / 所属板块</h4>
                <p v-if="profile.csrc_industry" class="mb-1 text-xs text-ui-text-3">{{ profile.csrc_industry }}</p>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="b in industryList"
                    :key="`hy-${b}`"
                    class="stock-profile-chip"
                  >{{ b }}</span>
                </div>
              </section>

              <section v-if="conceptList.length">
                <h4 class="mb-1 text-xs font-semibold text-ui-text-2">题材 / 概念</h4>
                <div class="flex flex-wrap gap-1">
                  <NuxtLink
                    v-for="b in conceptList"
                    :key="`gn-${b}`"
                    :to="conceptPath(b)"
                    class="stock-profile-chip stock-profile-chip-link"
                  >{{ b }}</NuxtLink>
                </div>
              </section>

              <section v-if="profile.related?.length">
                <h4 class="mb-1 text-xs font-semibold text-ui-text-2">关联股票</h4>
                <ul class="space-y-1 text-xs">
                  <li
                    v-for="(r, i) in profile.related"
                    :key="relatedKey(r, i)"
                    class="flex flex-wrap items-baseline gap-x-2"
                  >
                    <a
                      :href="baiduStockUrl(r.code, r.name)"
                      target="_blank"
                      rel="noopener"
                      class="text-accent hover:underline"
                    >{{ r.name }}</a>
                    <span class="text-ui-text-3">{{ r.code }}</span>
                    <span class="text-ui-text-2">{{ r.relation }}·{{ r.board }}</span>
                  </li>
                </ul>
              </section>

              <section v-if="chainGroups.length || profile.chain?.note">
                <h4 class="mb-1 text-xs font-semibold text-ui-text-2">产业上下游</h4>
                <div v-for="g in chainGroups" :key="g.label" class="mb-1 text-xs">
                  <span class="text-ui-text-2">{{ g.label }}：</span>
                  <a
                    v-for="r in g.items"
                    :key="`${g.label}-${r.code}`"
                    :href="baiduStockUrl(r.code, r.name)"
                    target="_blank"
                    rel="noopener"
                    class="mr-2 text-accent hover:underline"
                  >{{ r.name }}</a>
                </div>
                <p v-if="profile.chain?.note" class="text-xs leading-relaxed text-ui-text-3">
                  {{ profile.chain.note }}
                </p>
              </section>

              <section v-if="profile.summary">
                <h4 class="mb-1 text-xs font-semibold text-ui-text-2">公司简介</h4>
                <p class="text-xs leading-relaxed text-ui-text-3">{{ profile.summary }}</p>
              </section>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>
  </span>
</template>
