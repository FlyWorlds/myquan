<script setup lang="ts">
import type { ConceptDetailPayload, ConceptLeaderScoresPayload } from '~/types/sectors'

const route = useRoute()
const { fetchConceptDetail, fetchConceptLeaderScores } = useSectorsApi()
const { sectors, liveAt, refreshSec, setFocus } = useSectorsLive()
const store = useWatchStore()

const conceptName = computed(() => decodeURIComponent(String(route.params.name || '')))
const loading = ref(true)
const scoreLoading = ref(true)
const error = ref('')
const scoreError = ref('')
const detail = ref<ConceptDetailPayload | null>(null)
const leaderScores = ref<ConceptLeaderScoresPayload | null>(null)

const conceptLive = computed(() => {
  if (sectors.value?.conceptIndex?.name === conceptName.value) {
    return sectors.value.conceptIndex
  }
  const row = sectors.value?.conceptToday?.[conceptName.value]
  if (!row) return null
  return {
    name: conceptName.value,
    code: row.code,
    price: row.close,
    chgPct: row.涨跌幅,
    amount: row.资金,
  }
})

const liveSegments = computed(() => {
  const quotes = sectors.value?.quotes || {}
  if (!detail.value?.segments?.length) return []
  return detail.value.segments.map((seg) => ({
    ...seg,
    leaders: seg.leaders.map((l) => {
      const q = quotes[l.code]
      return {
        ...l,
        livePrice: q?.price ?? null,
        liveChgPct: q?.chgPct ?? null,
      }
    }),
  }))
})

const wsLabel = computed(() => {
  if (liveAt.value) return `实时 ${liveAt.value} · ${refreshSec.value}s`
  return store.wsStatus
})

async function loadScores(refresh = false) {
  scoreLoading.value = true
  scoreError.value = ''
  try {
    leaderScores.value = await fetchConceptLeaderScores(conceptName.value, '2025-01-01', refresh)
    if (leaderScores.value?.error && !leaderScores.value.leaders?.length) {
      scoreError.value = leaderScores.value.error
    }
  } catch (e) {
    scoreError.value = e instanceof Error ? e.message : String(e)
  } finally {
    scoreLoading.value = false
  }
}

async function load(refresh = false) {
  loading.value = true
  error.value = ''
  try {
    detail.value = await fetchConceptDetail(conceptName.value, 6, refresh)
    if (detail.value?.error) error.value = detail.value.error
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function reloadAll(refresh = false) {
  await Promise.all([load(refresh), loadScores(refresh)])
}

onMounted(async () => {
  await setFocus(conceptName.value)
  await Promise.all([load(), loadScores()])
})

onBeforeUnmount(() => {
  void setFocus(null)
})

watch(conceptName, async () => {
  await setFocus(conceptName.value)
  await Promise.all([load(), loadScores()])
})
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-4 px-4 py-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <NuxtLink to="/sectors" class="text-sm text-ui-text-2 hover:text-ui-text">← 板块轮动</NuxtLink>
        <h1 class="mt-2 text-xl font-bold">
          {{ conceptName }}
          <span v-if="detail?.code" class="ml-2 text-sm font-normal text-ui-text-2">{{ detail.code }}</span>
        </h1>
        <p v-if="conceptLive" class="mt-1 text-sm">
          <span class="font-semibold">{{ conceptLive.price?.toFixed(2) ?? '-' }}</span>
          <span
            class="ml-2 font-semibold"
            :class="(conceptLive.chgPct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
          >
            {{ conceptLive.chgPct != null ? `${conceptLive.chgPct >= 0 ? '+' : ''}${conceptLive.chgPct.toFixed(2)}%` : '-' }}
          </span>
          <span class="ml-3 text-ui-text-3">{{ wsLabel }}</span>
        </p>
        <p v-else class="mt-1 text-sm text-ui-text-2">
          {{ detail?.source || '概念' }}指数 · 近半年 K 线 · 波段龙头
        </p>
      </div>
      <button class="btn btn-ghost" :disabled="loading || scoreLoading" @click="reloadAll(true)">
        重载
      </button>
    </div>

    <div v-if="loading" class="rounded-xl border border-ui-hairline bg-ui-surface p-8 text-center text-ui-text-2">
      正在加载概念详情…
    </div>
    <div v-else-if="error" class="rounded-xl border border-ui-hairline bg-ui-surface p-6 text-watch-up">
      {{ error }}
    </div>
    <template v-else-if="detail">
      <section class="rounded-xl border border-ui-hairline bg-ui-surface p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 class="text-sm font-semibold">因子龙头 Top5（2025至今）</h3>
            <p class="mt-1 text-xs text-ui-text-3">
              因子16（F13质量带 + 因子1 + 缠论笔）· 排序见 docs/FACTOR16.md
            </p>
          </div>
          <span v-if="leaderScores?.updated_at" class="text-xs text-ui-text-3">
            {{ leaderScores.updated_at }}
          </span>
        </div>
        <div
          v-if="scoreLoading"
          class="mt-4 rounded-lg border border-ui-hairline bg-ui-bg/50 p-6 text-center text-sm text-ui-text-2"
        >
          正在回测成分股（因子13+因子1+缠论，首次较慢）…
        </div>
        <div v-else-if="scoreError" class="mt-4 text-sm text-watch-up">{{ scoreError }}</div>
        <div v-else-if="leaderScores?.leaders?.length" class="mt-4 overflow-x-auto">
          <table class="w-full min-w-[720px] text-sm">
            <thead>
              <tr class="text-left text-ui-text-2">
                <th class="pb-2 pr-2">#</th>
                <th class="pb-2 pr-2">标的</th>
                <th class="pb-2 pr-2 text-right">F13分</th>
                <th class="pb-2 pr-2 text-center">过带</th>
                <th class="pb-2 pr-2 text-right">盈亏比</th>
                <th class="pb-2 pr-2 text-right">胜率%</th>
                <th class="pb-2 pr-2 text-right">超额%</th>
                <th class="pb-2 pr-2 text-right">回撤%</th>
                <th class="pb-2 pr-2 text-right">收益%</th>
                <th class="pb-2 pr-2 text-right">缠论比</th>
                <th class="pb-2 text-right">现价</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="l in leaderScores.leaders"
                :key="l.code"
                class="border-t border-ui-hairline"
              >
                <td class="py-2 pr-2">{{ l.rank }}</td>
                <td class="py-2 pr-2">
                  {{ l.name }}
                  <span class="text-ui-text-3">{{ l.code }}</span>
                </td>
                <td class="py-2 pr-2 text-right font-mono">
                  {{ l.score_quality != null ? l.score_quality.toFixed(3) : '-' }}
                </td>
                <td class="py-2 pr-2 text-center">{{ l.f13_pass ? '✓' : '·' }}</td>
                <td class="py-2 pr-2 text-right font-semibold">
                  {{ l.pl_ratio != null ? l.pl_ratio.toFixed(2) : '-' }}
                </td>
                <td class="py-2 pr-2 text-right">
                  {{ l.win_rate != null ? l.win_rate.toFixed(1) : '-' }}
                </td>
                <td
                  class="py-2 pr-2 text-right"
                  :class="(l.excess_pct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
                >
                  {{ l.excess_pct != null ? `${l.excess_pct >= 0 ? '+' : ''}${l.excess_pct.toFixed(2)}` : '-' }}
                </td>
                <td class="py-2 pr-2 text-right text-watch-down">
                  {{ l.mdd_pct != null ? l.mdd_pct.toFixed(2) : '-' }}
                </td>
                <td
                  class="py-2 pr-2 text-right"
                  :class="(l.ret_pct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
                >
                  {{ l.ret_pct != null ? `${l.ret_pct >= 0 ? '+' : ''}${l.ret_pct.toFixed(2)}` : '-' }}
                </td>
                <td class="py-2 pr-2 text-right text-ui-text-2">
                  {{ l.chan_pl_ratio != null ? l.chan_pl_ratio.toFixed(2) : '-' }}
                </td>
                <td class="py-2 text-right">
                  {{
                    sectors?.quotes?.[l.code]?.price != null
                      ? sectors.quotes[l.code].price!.toFixed(2)
                      : '-'
                  }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="leaderScores.scoring?.rank" class="mt-2 text-xs text-ui-text-3">
            {{ leaderScores.scoring.rank }} · 候选 {{ leaderScores.candidate_count ?? '-' }} 只
          </p>
        </div>
        <p v-else class="mt-4 text-sm text-ui-text-2">暂无满足条件的评分龙头</p>
      </section>

      <ConceptKlineChart :detail="detail" />

      <div class="grid gap-4 lg:grid-cols-2">
        <section
          v-for="seg in liveSegments"
          :key="`${seg.start_date}-${seg.end_date}`"
          class="rounded-xl border border-ui-hairline bg-ui-surface p-4"
        >
          <h3 class="text-sm font-semibold">
            {{ seg.start_date }} ~ {{ seg.end_date }}
            <span class="ml-2 text-ui-text-2">{{ seg.days }}日 · 指数 +{{ seg.gain_pct }}%</span>
          </h3>
          <table class="mt-3 w-full text-sm">
            <thead>
              <tr class="text-left text-ui-text-2">
                <th class="pb-2">排名</th>
                <th class="pb-2">龙头</th>
                <th class="pb-2 text-right">区间涨幅</th>
                <th class="pb-2 text-right">现价</th>
                <th class="pb-2 text-right">今日</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in seg.leaders" :key="l.code" class="border-t border-ui-hairline">
                <td class="py-2">{{ l.rank }}</td>
                <td class="py-2">{{ l.name }} <span class="text-ui-text-3">{{ l.code }}</span></td>
                <td class="py-2 text-right font-semibold text-watch-up">+{{ l.return_pct.toFixed(2) }}%</td>
                <td class="py-2 text-right">{{ l.livePrice != null ? l.livePrice.toFixed(2) : '-' }}</td>
                <td
                  class="py-2 text-right font-semibold"
                  :class="(l.liveChgPct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'"
                >
                  {{ l.liveChgPct != null ? `${l.liveChgPct >= 0 ? '+' : ''}${l.liveChgPct.toFixed(2)}%` : '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="rounded-xl border border-ui-hairline bg-ui-surface p-4">
        <h3 class="text-sm font-semibold">成分股预览（{{ detail.member_count }} 只）</h3>
        <p class="mt-2 flex flex-wrap gap-2 text-xs text-ui-text-2">
          <span
            v-for="m in detail.members_preview"
            :key="m.code"
            class="rounded-md border border-ui-hairline px-2 py-1"
          >
            {{ m.name }} {{ m.code }}
            <template v-if="sectors?.quotes?.[m.code]">
              · {{ sectors.quotes[m.code].price?.toFixed(2) }}
              <span :class="(sectors.quotes[m.code].chgPct ?? 0) >= 0 ? 'text-watch-up' : 'text-watch-down'">
                {{ sectors.quotes[m.code].chgPct != null ? `${sectors.quotes[m.code].chgPct!.toFixed(2)}%` : '' }}
              </span>
            </template>
          </span>
        </p>
      </section>

      <p class="text-xs text-ui-text-3">
        波段 {{ detail.updated_at }} · 现价随盯盘 {{ refreshSec }}s 刷新 · {{ detail.source }}
      </p>
    </template>
  </div>
</template>
