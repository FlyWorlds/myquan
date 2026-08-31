<script setup lang="ts">
import type { StrategyEntry } from '~/types/registry'

const props = defineProps<{ tab: StrategyEntry; anchor?: boolean }>()

const factorSummary = computed(() =>
  (props.tab.factors || [])
    .map((f) => f.id)
    .join(' + '),
)

const shortDesc = computed(() => {
  const d = String(props.tab.description || '').trim()
  if (!d) return '暂无简介'
  return d.length > 72 ? `${d.slice(0, 72)}…` : d
})
</script>

<template>
  <article :id="props.anchor !== false ? tab.id : undefined" :class="props.anchor !== false ? 'registry-scroll-target' : undefined">
  <RegistryHoverCard>
    <template #compact>
      <header class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ tab.id }}</span>
          <h2 class="mt-1 truncate text-base font-bold text-ui-text">{{ tab.label || tab.name }}</h2>
          <p class="mt-1 line-clamp-2 text-sm leading-relaxed text-ui-text-2">{{ shortDesc }}</p>
        </div>
        <div class="flex shrink-0 flex-col items-end gap-1">
          <span
            v-if="tab.is_watch_default"
            class="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-bold text-accent"
          >
            盯盘默认
          </span>
          <span
            class="rounded-full px-2 py-0.5 text-xs font-semibold"
            :class="tab.implemented !== false ? 'bg-accent/15 text-accent' : 'bg-ui-fill-active text-ui-text-3'"
          >
            {{ tab.implemented !== false ? '已实现' : '规划中' }}
          </span>
        </div>
      </header>
      <div class="mt-2 grid grid-cols-1 gap-1 text-sm">
        <div><span class="text-ui-text-2">挂载因子</span> <b class="text-accent">{{ factorSummary || '—' }}</b></div>
        <div v-if="tab.picks?.items?.length">
          <span class="text-ui-text-2">选股/信号</span> <b>{{ tab.picks.items.length }} 条</b>
        </div>
      </div>
    </template>

    <template #detail>
      <h3 class="text-base font-bold">{{ tab.label || tab.name }}</h3>
      <p v-if="tab.description" class="mt-2 text-sm leading-relaxed text-ui-text-2">{{ tab.description }}</p>
      <p v-if="tab.aliases?.length" class="mt-2 text-xs text-ui-text-3">别名：{{ tab.aliases.join('、') }}</p>

      <div class="mt-3 overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-left text-ui-text-2">
            <tr>
              <th class="px-2 py-1">因子</th>
              <th class="px-2 py-1">角色</th>
              <th class="px-2 py-1">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in tab.factors" :key="f.id" class="border-t border-ui-hairline">
              <td class="px-2 py-1 whitespace-nowrap"><code class="text-accent">{{ f.id }}</code> · {{ f.name }}</td>
              <td class="px-2 py-1">{{ f.role }}</td>
              <td class="max-w-md px-2 py-1 text-xs text-ui-text-2">{{ f.filter_desc || f.description || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="tab.backtest?.length" class="mt-4">
        <h4 class="text-sm font-semibold">回测摘要（研究）</h4>
        <div class="mt-2 overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="text-left text-ui-text-2">
              <tr>
                <th class="px-2 py-1">阈值</th>
                <th class="px-2 py-1">总收益</th>
                <th class="px-2 py-1">回撤</th>
                <th class="px-2 py-1">夏普</th>
                <th class="px-2 py-1">笔数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in tab.backtest" :key="String(b.entry_pct)" class="border-t border-ui-hairline">
                <td class="px-2 py-1">±{{ ((b.entry_pct || 0) * 100).toFixed(1) }}%</td>
                <td class="px-2 py-1">{{ (b.total_return_pct ?? 0).toFixed(1) }}%</td>
                <td class="px-2 py-1">{{ (b.max_drawdown_pct ?? 0).toFixed(1) }}%</td>
                <td class="px-2 py-1">{{ (b.sharpe_ratio ?? 0).toFixed(2) }}</td>
                <td class="px-2 py-1">{{ b.n_trades ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="tab.reportPath" class="mt-1 text-xs text-ui-text-3">报告：{{ tab.reportPath }}</p>
      </div>

      <div v-if="tab.picks?.items?.length" class="mt-3 rounded-lg border border-ui-hairline bg-ui-ink/30 p-3">
        <StrategyPicksPanel :picks="tab.picks" />
      </div>
    </template>
  </RegistryHoverCard>
  </article>
</template>
