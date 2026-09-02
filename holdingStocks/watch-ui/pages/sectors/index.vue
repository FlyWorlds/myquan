<script setup lang="ts">
import type { SectorMember, SectorRotationPayload } from '~/types/sectors'

const { fetchRotation, fetchConceptMembers } = useSectorsApi()
const { mergedKind, liveAt, memberStatsAt, refreshSec } = useSectorsLive()
const router = useRouter()
const store = useWatchStore()

const loading = ref(true)
const error = ref('')
const payload = ref<SectorRotationPayload | null>(null)
const metric = ref('涨幅')
const selected = ref<string | null>(null)
const heatmapRef = ref<{ clearSelection: () => void } | null>(null)
const members = ref<SectorMember[]>([])
const membersLoading = ref(false)
const membersError = ref('')
const membersSource = ref('')
const membersCount = ref(0)
const membersCache = new Map<string, { members: SectorMember[]; source: string; count: number }>()

const topN = computed(() => payload.value?.top_n || 10)
const baseKind = computed(() => payload.value?.kinds?.概念 || null)
const kindData = computed(() =>
  mergedKind(baseKind.value, topN.value, payload.value?.metrics),
)

const liveError = computed(() => store.snapshot?.sectors?.error || '')
const heatmapEmpty = computed(() => {
  const k = kindData.value
  if (!k) return true
  const cols = k.by_metric?.[metric.value]?.top || []
  return !cols.some((col) => Array.isArray(col) && col.length)
})

const wsLabel = computed(() => {
  const st = store.wsStatus
  if (liveAt.value) return `实时 ${liveAt.value} · ${refreshSec.value}s`
  return st
})

async function loadMembers(name: string) {
  membersLoading.value = true
  membersError.value = ''
  const cached = membersCache.get(name)
  if (cached) {
    members.value = cached.members
    membersSource.value = cached.source
    membersCount.value = cached.count
    membersLoading.value = false
    return
  }
  const packed = payload.value?.kinds?.概念?.members?.[name]
  if (packed?.length) {
    members.value = packed
    membersSource.value = payload.value?.source || ''
    membersCount.value = packed.length
    membersCache.set(name, { members: packed, source: membersSource.value, count: packed.length })
    membersLoading.value = false
    return
  }
  try {
    const data = await fetchConceptMembers(name, 80)
    members.value = data.members || []
    membersSource.value = data.source || ''
    membersCount.value = data.count || members.value.length
    if (data.error && !members.value.length) {
      membersError.value = data.error
    }
    membersCache.set(name, {
      members: members.value,
      source: membersSource.value,
      count: membersCount.value,
    })
  } catch (e) {
    members.value = []
    membersCount.value = 0
    membersError.value = e instanceof Error ? e.message : String(e)
  } finally {
    membersLoading.value = false
  }
}

async function load(refresh = false) {
  loading.value = true
  error.value = ''
  try {
    payload.value = await fetchRotation(20, 10, refresh)
    membersCache.clear()
    if (selected.value) await loadMembers(selected.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function onSelect(name: string) {
  selected.value = name
  void loadMembers(name)
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
}

function fmtChg(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  const x = Number(v)
  return `${x >= 0 ? '+' : ''}${x.toFixed(2)}%`
}

onMounted(() => load())
</script>

<template>
  <div class="page-shell space-y-4 py-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-bold">板块轮动</h1>
        <p class="mt-1 text-sm text-ui-text-2">
          {{ payload?.source || '概念' }} · 今日列随盯盘 {{ refreshSec }}s 推送刷新；点击格子看成分股，再点一次进波段龙头
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-ui-text-3">{{ wsLabel }}</span>
        <button class="btn btn-ghost" :disabled="loading" @click="load(true)">重载历史</button>
      </div>
    </div>

    <div v-if="loading" class="rounded-xl border border-ui-hairline bg-ui-surface p-8 text-center text-ui-text-2">
      正在拉取概念轮动（首次较慢）…
    </div>
    <div v-else-if="error" class="rounded-xl border border-ui-hairline bg-ui-surface p-6 text-watch-up">
      {{ error }}
    </div>
    <div
      v-else-if="heatmapEmpty"
      class="rounded-xl border border-ui-hairline bg-ui-surface p-6 text-sm text-ui-text-2"
    >
      {{ liveError || '暂无板块数据。可点「重载历史」重试。' }}
    </div>
    <template v-else-if="kindData">
      <div class="flex flex-wrap items-center gap-3 rounded-xl border border-ui-hairline bg-ui-surface px-4 py-3">
        <label class="text-sm text-ui-text-2">指标</label>
        <select v-model="metric" class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm">
          <option v-for="m in payload?.metrics || []" :key="m" :value="m">{{ m }}</option>
        </select>
        <div class="ml-auto flex flex-wrap items-center gap-2 text-sm">
          <template v-if="selected">
            <span>选中板块: <strong>{{ selected }}</strong></span>
            <button class="btn btn-ghost text-watch-accent" @click="goDetail">查看龙头</button>
            <button class="btn btn-ghost" @click="clearSelected">取消高亮</button>
          </template>
          <span v-else class="text-ui-text-2">点击格子选中板块，下方显示成分股</span>
        </div>
      </div>

      <SectorHeatmap
        ref="heatmapRef"
        :kind="kindData"
        :top-n="topN"
        :metric="metric"
        @select="onSelect"
        @drill="onDrill"
      />

      <p class="text-xs text-ui-text-3">
        历史 {{ payload?.updated_at }} · {{ kindData.fund_note }} · 共 {{ kindData.board_count }} 个概念
        <span v-if="memberStatsAt" class="text-ui-text-3"> · 涨停/涨跌比 {{ memberStatsAt }}</span>
      </p>

      <section
        v-if="selected"
        class="rounded-xl border border-ui-hairline bg-ui-surface p-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-semibold">
            {{ selected }} · 成分股
            <span class="ml-2 text-xs font-normal text-ui-text-3">
              {{ membersSource }} {{ membersCount ? `· ${membersCount} 只` : '' }}
            </span>
          </h3>
        </div>
        <p v-if="membersLoading" class="mt-3 text-sm text-ui-text-2">正在加载成分股…</p>
        <p v-else-if="membersError" class="mt-3 text-sm text-watch-up">{{ membersError }}</p>
        <p v-else-if="!members.length" class="mt-3 text-sm text-ui-text-2">
          暂无成分数据（通达信索引或东财都没对上这个名称）
        </p>
        <div v-else class="mt-3 max-h-80 overflow-auto">
          <table class="w-full min-w-[520px] text-sm">
            <thead>
              <tr class="text-left text-ui-text-2">
                <th class="pb-2 pr-2">代码</th>
                <th class="pb-2 pr-2">名称</th>
                <th class="pb-2 pr-2 text-right">现价</th>
                <th class="pb-2 text-right">涨跌幅</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="m in members"
                :key="m.代码"
                class="border-t border-ui-hairline"
              >
                <td class="py-1.5 pr-2 font-mono text-xs">{{ m.代码 }}</td>
                <td class="py-1.5 pr-2">{{ m.名称 || m.代码 }}</td>
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
      </section>
    </template>
  </div>
</template>
