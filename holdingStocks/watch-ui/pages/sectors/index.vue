<script setup lang="ts">
import { ROTATION_METRICS } from '~/composables/useSectorsLive'
import type { HotPeriodCard, SectorMember, SectorRotationPayload } from '~/types/sectors'

const { fetchRotation, fetchConceptMembers } = useSectorsApi()
const { mergedKind, liveAt, memberStatsAt, refreshSec, setFocus } = useSectorsLive()
const router = useRouter()
const store = useWatchStore()

const loading = ref(true)
const historyLoading = ref(true)
const error = ref('')
const payload = useState<SectorRotationPayload | null>('sector-rotation-history', () => null)

const boardKind = ref<'概念' | '行业'>('概念')
const metric = ref('涨幅')
const hotPeriod = ref<'1' | '3' | '5' | '10'>('1')
const showBottom = ref(false)
const selected = ref<string | null>(null)
const heatmapRef = ref<{ clearSelection: () => void } | null>(null)

const members = ref<SectorMember[]>([])
const membersLoading = ref(false)
const membersError = ref('')
const membersSource = ref('')
const membersCount = ref(0)
const membersCache = new Map<string, { members: SectorMember[]; source: string; count: number }>()

const topN = computed(() => payload.value?.top_n || 10)
const baseKind = computed(() => {
  const kinds = payload.value?.kinds || {}
  return kinds[boardKind.value] || kinds['概念'] || null
})
const kindData = computed(() => {
  void store.snapshot?.ts
  void store.snapshot?.sectors?.spotAt
  return mergedKind(baseKind.value, topN.value, payload.value?.metrics, boardKind.value)
})

const hotCards = computed<HotPeriodCard[]>(() => {
  const hp = kindData.value?.hot_periods || {}
  const list = hp[hotPeriod.value] || hp['1'] || []
  if (list.length) return list.slice(0, 3)
  // Fallback from top column
  const topCol = kindData.value?.by_metric?.['涨幅']?.top?.[0] || []
  return topCol.slice(0, 3).map((c, idx) => ({
    name: c.name,
    code: c.label || '',
    chg_pct: c.value,
    net_inflow: c.net_inflow ?? null,
    amount: c.amount ?? null,
    period: Number(hotPeriod.value),
    rank: idx + 1,
  }))
})

const selectedStat = computed(() => {
  const name = selected.value
  if (!name) return null
  const st = kindData.value?.board_stats?.[name]
  const liveRow = store.snapshot?.sectors?.conceptToday?.[name]
  const topCol = kindData.value?.by_metric?.[metric.value]?.top?.[0] || []
  const rankInCol = topCol.findIndex(c => c.name === name)
  const chgCols = kindData.value?.by_metric?.['涨幅']?.top || []
  let appear15 = st?.appear_15d ?? 0
  if (!appear15 && chgCols.length) {
    appear15 = chgCols.slice(0, 15).reduce(
      (acc, col) => acc + ((col || []).some(c => c.name === name) ? 1 : 0),
      0,
    )
  }
  return {
    name,
    chgPct: liveRow?.涨跌幅 ?? st?.chg_pct ?? null,
    todayRank: st?.today_rank ?? (rankInCol >= 0 ? rankInCol + 1 : null),
    appear15d: appear15 || 1,
    sessionDate: payload.value?.session || (store.snapshot?.clock || '').slice(0, 10) || '',
  }
})

function memberQuote(code: string | undefined) {
  const raw = String(code || '').trim()
  if (!raw) return null
  const quotes = store.snapshot?.sectors?.quotes || {}
  return quotes[raw] || quotes[raw.padStart(6, '0')] || null
}

const liveMembers = computed(() => {
  return members.value.map((m) => {
    const q = memberQuote(m.代码)
    if (!q) return m
    return {
      ...m,
      现价: q.price ?? m.现价,
      涨跌幅: q.chgPct ?? m.涨跌幅,
    }
  })
})

const sectorsDeferred = computed(() => Boolean(store.snapshot?.sectors?.deferred))
const heatmapEmpty = computed(() => {
  const k = kindData.value
  if (!k) return true
  const cols = k.by_metric?.[metric.value]?.top || []
  return !cols.some(col => Array.isArray(col) && col.length)
})
const waitingSectors = computed(
  () =>
    heatmapEmpty.value &&
    (sectorsDeferred.value || (!payload.value && historyLoading.value)),
)

const liveSource = computed(
  () => payload.value?.source || store.snapshot?.sectors?.source || '同花顺热点轮动',
)
const wsLabel = computed(() => {
  const st = store.wsStatus
  if (liveAt.value) return `实时 ${liveAt.value} · ${refreshSec.value}s · ${liveSource.value}`
  return st
})

async function loadMembers(name: string) {
  membersError.value = ''
  const cacheKey = `${boardKind.value}:${name}`
  const cached = membersCache.get(cacheKey)
  if (cached) {
    members.value = cached.members
    membersSource.value = cached.source
    membersCount.value = cached.count
    membersLoading.value = false
    return
  }
  const packed = payload.value?.kinds?.[boardKind.value]?.members?.[name]
  if (packed?.length) {
    members.value = packed
    membersSource.value = payload.value?.source || ''
    membersCount.value = packed.length
    membersLoading.value = false
    const hasQuotes = packed.some(m => m.现价 != null || m.涨跌幅 != null)
    if (hasQuotes) {
      membersCache.set(cacheKey, {
        members: packed,
        source: membersSource.value,
        count: packed.length,
      })
      return
    }
  } else {
    members.value = []
    membersSource.value = ''
    membersCount.value = 0
    membersLoading.value = true
  }
  try {
    const data = await fetchConceptMembers(name, 80, boardKind.value)
    if (data.members?.length) {
      members.value = data.members
      membersSource.value = data.source || ''
      membersCount.value = data.count || data.members.length
      membersCache.set(cacheKey, {
        members: members.value,
        source: membersSource.value,
        count: membersCount.value,
      })
    } else if (!packed?.length && data.error) {
      membersError.value = data.error
    }
  } catch (e) {
    if (!packed?.length) {
      members.value = []
      membersSource.value = ''
      membersCount.value = 0
      membersError.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    membersLoading.value = false
  }
}

function ensureDefaultSelection() {
  if (selected.value) return
  const firstCard = hotCards.value[0]?.name
  const firstCell = kindData.value?.by_metric?.[metric.value]?.top?.[0]?.[0]?.name
  const pick = firstCard || firstCell
  if (pick) {
    selected.value = pick
    void setFocus(pick)
    void loadMembers(pick)
  }
}

async function load(refresh = false) {
  historyLoading.value = true
  if (!kindData.value) loading.value = true
  error.value = ''
  try {
    const next = await fetchRotation(20, 10, refresh)
    const previousColumns = payload.value?.kinds?.概念?.dates?.length || 0
    const nextColumns = next.kinds?.概念?.dates?.length || 0
    if (!payload.value || nextColumns >= previousColumns || refresh) {
      payload.value = next
    }
    membersCache.clear()
    ensureDefaultSelection()
    if (selected.value) await loadMembers(selected.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
    historyLoading.value = false
  }
}

function onSelect(name: string) {
  if (!name) return
  selected.value = name
  void setFocus(name)
  void loadMembers(name)
}

function onCardClick(card: HotPeriodCard) {
  if (!card?.name) return
  if (selected.value === card.name) {
    onDrill(card.name)
    return
  }
  onSelect(card.name)
}

function onDrill(name: string) {
  router.push(`/sectors/concept/${encodeURIComponent(name)}`)
}

function goDetail() {
  if (selected.value) {
    router.push(`/sectors/concept/${encodeURIComponent(selected.value)}`)
  }
}

function clearSelected() {
  selected.value = null
  members.value = []
  membersError.value = ''
  membersSource.value = ''
  membersCount.value = 0
  heatmapRef.value?.clearSelection?.()
  void setFocus(null)
}

function fmtChg(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  const x = Number(v)
  return `${x >= 0 ? '+' : ''}${x.toFixed(2)}%`
}

function fmtYi(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return null
  const abs = Math.abs(Number(v))
  if (abs >= 1e8) return `${(abs / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(abs / 1e4).toFixed(0)}万`
  return `${abs.toFixed(0)}`
}

watch(boardKind, () => {
  selected.value = null
  ensureDefaultSelection()
})

onMounted(() => load())
onBeforeUnmount(() => {
  void setFocus(null)
})
</script>

<template>
  <div class="page-shell space-y-4 py-5">
    <!-- 顶部栏：对齐同花顺「热点轮动」标题与刷新控制 -->
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-gradient-to-r from-[#e11d2e] to-[#f0483e] px-5 py-3.5 text-white shadow-sm">
      <div class="flex items-center gap-3">
        <h1 class="text-lg font-bold tracking-wide">热点轮动</h1>
        <span class="rounded-full bg-white/20 px-2.5 py-0.5 text-xs font-medium">
          同花顺优先 · 数据库存储
        </span>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span class="text-xs text-white/85">{{ wsLabel }}</span>
        <button
          class="rounded-lg bg-white/20 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/30 disabled:opacity-50"
          :disabled="historyLoading"
          @click="load(true)"
        >
          {{ historyLoading ? '刷新中…' : '刷新轮动' }}
        </button>
      </div>
    </div>

    <p v-if="error" role="status" class="text-sm text-watch-up">{{ error }}</p>

    <!-- 双下拉筛选栏：概念板块 / 行业板块 + 涨幅 / 资金 / 指标 -->
    <div class="grid grid-cols-2 gap-3 sm:flex sm:items-center sm:justify-between rounded-xl border border-ui-hairline bg-ui-surface px-4 py-2.5">
      <div class="flex items-center gap-2">
        <select
          v-model="boardKind"
          class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-1.5 text-sm font-semibold focus:outline-none"
        >
          <option value="概念">概念板块</option>
          <option value="行业">行业板块</option>
        </select>
        <select
          v-model="metric"
          class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-1.5 text-sm font-semibold focus:outline-none"
        >
          <option
            v-for="m in payload?.metrics?.length ? payload.metrics : ROTATION_METRICS"
            :key="m"
            :value="m"
          >
            {{ m }}
          </option>
        </select>
      </div>

      <div class="flex items-center justify-end gap-3 text-xs text-ui-text-2">
        <label class="inline-flex cursor-pointer items-center gap-1.5">
          <input v-model="showBottom" type="checkbox" class="rounded border-ui-hairline">
          <span>显示后{{ topN }}名</span>
        </label>
        <span class="hidden sm:inline text-ui-text-3">
          共 {{ kindData?.board_count || 0 }} 个{{ boardKind }}
        </span>
      </div>
    </div>

    <!-- 热门板块卡片区（1日 | 3日 | 5日 | 10日） -->
    <section class="rounded-xl border border-ui-hairline bg-ui-surface p-4 shadow-sm">
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-base font-bold">热门板块</h2>
        <div class="flex items-center gap-1 text-xs">
          <button
            v-for="p in (['1', '3', '5', '10'] as const)"
            :key="p"
            type="button"
            class="rounded-md px-2.5 py-1 font-medium transition"
            :class="
              hotPeriod === p
                ? 'bg-[#e11d2e]/10 text-[#e11d2e] font-bold'
                : 'text-ui-text-2 hover:bg-ui-page'
            "
            @click="hotPeriod = p"
          >
            {{ p }}日
          </button>
        </div>
      </div>

      <div v-if="hotCards.length" class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <button
          v-for="card in hotCards"
          :key="card.name"
          type="button"
          class="flex flex-col items-center justify-center rounded-xl border-2 px-4 py-3.5 text-center transition"
          :class="
            selected === card.name
              ? 'border-[#e11d2e] bg-[#e11d2e]/[0.05]'
              : 'border-ui-hairline bg-ui-page/60 hover:border-ui-text-3'
          "
          @click="onCardClick(card)"
        >
          <span class="text-sm font-bold truncate max-w-full">{{ card.name }}</span>
          <span
            class="mt-1.5 text-xl font-extrabold tracking-tight"
            :class="(card.chg_pct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
          >
            {{ fmtChg(card.chg_pct) }}
          </span>
          <div class="mt-2 flex items-center justify-center gap-1.5 text-xs">
            <template v-if="card.net_inflow != null && fmtYi(card.net_inflow)">
              <span
                class="rounded px-1.5 py-0.5 text-[11px] font-semibold"
                :class="
                  card.net_inflow >= 0
                    ? 'bg-watch-up/15 text-watch-up'
                    : 'bg-watch-down/15 text-watch-down'
                "
              >
                {{ card.net_inflow >= 0 ? '净买' : '净卖' }}
              </span>
              <span
                class="font-semibold"
                :class="card.net_inflow >= 0 ? 'text-watch-up' : 'text-watch-down'"
              >
                {{ fmtYi(card.net_inflow) }}
              </span>
            </template>
            <template v-else-if="card.amount != null && fmtYi(card.amount)">
              <span class="rounded bg-ui-surface px-1.5 py-0.5 text-[11px] text-ui-text-2">
                成交
              </span>
              <span class="font-medium text-ui-text-2">{{ fmtYi(card.amount) }}</span>
            </template>
            <span v-else class="text-ui-text-3">点击追踪轮动</span>
          </div>
        </button>
      </div>
      <div v-else class="mt-3 py-6 text-center text-sm text-ui-text-3">
        {{ historyLoading ? '正在加载热门板块…' : '暂无热门板块数据' }}
      </div>
    </section>

    <!-- 多日轮动排名表 -->
    <SectorHeatmap
      ref="heatmapRef"
      :kind="kindData || { dates: [], by_metric: {}, members: {}, fund_note: '', board_count: 0 }"
      :loading="historyLoading || waitingSectors"
      :top-n="topN"
      :metric="metric"
      :selected-name="selected"
      :show-bottom="showBottom"
      @select="onSelect"
      @drill="onDrill"
    />

    <!-- 同花顺同款底部选中板块摘要栏 -->
    <section
      v-if="selected && selectedStat"
      class="rounded-xl border-2 border-[#e11d2e]/40 bg-ui-surface p-4 shadow-md"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-baseline gap-3">
          <h3 class="text-lg font-bold">{{ selectedStat.name }}</h3>
          <span
            class="text-lg font-extrabold"
            :class="(selectedStat.chgPct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
          >
            {{ fmtChg(selectedStat.chgPct) }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-lg bg-[#e11d2e] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-[#c81928]"
            @click="goDetail"
          >
            <span>板块K线 / 波段详情</span>
            <span>&gt;</span>
          </button>
          <button type="button" class="btn btn-ghost text-xs" @click="clearSelected">
            取消选中
          </button>
        </div>
      </div>

      <div class="mt-2 flex flex-wrap items-center gap-4 text-xs text-ui-text-2">
        <span>{{ selectedStat.sessionDate || '今日' }}</span>
        <span>
          排名
          <strong class="text-ui-text">{{ selectedStat.todayRank ?? '-' }}</strong>
        </span>
        <span class="text-ui-text-3">|</span>
        <span>
          近15个交易日 上榜
          <strong class="text-[#e11d2e]">{{ selectedStat.appear15d }}次</strong>
        </span>
        <span v-if="membersSource" class="ml-auto text-ui-text-3">
          成分来源：{{ membersSource }} {{ membersCount ? `· ${membersCount} 只` : '' }}
        </span>
      </div>

      <!-- 成分股列表 -->
      <div class="mt-3 border-t border-ui-hairline pt-3">
        <p v-if="membersLoading" class="text-sm text-ui-text-2">正在加载成分股…</p>
        <p v-else-if="membersError" class="text-sm text-watch-up">{{ membersError }}</p>
        <p v-else-if="!members.length" class="text-sm text-ui-text-2">暂无成分股数据</p>
        <div v-else class="max-h-72 overflow-auto">
          <table class="w-full min-w-[520px] text-sm">
            <thead>
              <tr class="text-left text-xs text-ui-text-2">
                <th class="pb-2 pr-2">代码</th>
                <th class="pb-2 pr-2">名称</th>
                <th class="pb-2 pr-2 text-right">现价</th>
                <th class="pb-2 text-right">涨跌幅</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="m in liveMembers"
                :key="m.代码"
                class="border-t border-ui-hairline"
              >
                <td class="py-1.5 pr-2 font-mono text-xs">{{ m.代码 }}</td>
                <td class="py-1.5 pr-2">
                  <StockNameHover :code="m.代码" :name="m.名称">
                    {{ m.名称 || m.代码 }}
                  </StockNameHover>
                </td>
                <td class="py-1.5 pr-2 text-right font-mono">
                  {{ m.现价 != null ? Number(m.现价).toFixed(2) : '-' }}
                </td>
                <td
                  class="py-1.5 text-right font-semibold"
                  :class="(m.涨跌幅 ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
                >
                  {{ fmtChg(m.涨跌幅) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <p class="text-xs text-ui-text-3">
      <span v-if="historyLoading">轮动历史加载中… · </span>
      <span v-else>更新时间 {{ payload?.updated_at }} · </span>
      {{ kindData?.fund_note }}
      <span v-if="memberStatsAt" class="text-ui-text-3"> · 涨停/涨跌比 {{ memberStatsAt }}</span>
    </p>
  </div>
</template>
