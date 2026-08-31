<script setup lang="ts">
import type { SectorRotationPayload } from '~/types/sectors'

const { fetchRotation } = useSectorsApi()
const { mergedKind, liveAt, memberStatsAt, refreshSec } = useSectorsLive()
const router = useRouter()
const store = useWatchStore()

const loading = ref(true)
const error = ref('')
const payload = ref<SectorRotationPayload | null>(null)
const metric = ref('涨幅')
const selected = ref<string | null>(null)
const heatmapRef = ref<{ clearSelection: () => void } | null>(null)

const topN = computed(() => payload.value?.top_n || 10)
const baseKind = computed(() => payload.value?.kinds?.概念 || null)
const kindData = computed(() =>
  mergedKind(baseKind.value, topN.value, payload.value?.metrics),
)

const wsLabel = computed(() => {
  const st = store.wsStatus
  if (liveAt.value) return `实时 ${liveAt.value} · ${refreshSec.value}s`
  return st
})

async function load(refresh = false) {
  loading.value = true
  error.value = ''
  try {
    payload.value = await fetchRotation(20, 10, refresh)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function onSelect(name: string) {
  selected.value = name
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
  heatmapRef.value?.clearSelection?.()
}

onMounted(() => load())
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-4 px-4 py-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-bold">板块轮动</h1>
        <p class="mt-1 text-sm text-ui-text-2">
          通达信概念 · 今日列随盯盘 {{ refreshSec }}s 推送刷新；点击格子进入波段龙头
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-ui-text-3">{{ wsLabel }}</span>
        <button class="btn btn-ghost" :disabled="loading" @click="load(true)">重载历史</button>
      </div>
    </div>

    <div v-if="loading" class="rounded-xl border border-ui-hairline bg-ui-surface p-8 text-center text-ui-text-2">
      正在拉取通达信概念历史（首次较慢）…
    </div>
    <div v-else-if="error" class="rounded-xl border border-ui-hairline bg-ui-surface p-6 text-watch-up">
      {{ error }}
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
          <span v-else class="text-ui-text-2">点击格子选中板块</span>
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
    </template>
  </div>
</template>
