<script setup lang="ts">
const { strategies, loading, error, fetchStrategies } = useRegistry()

onMounted(() => {
  fetchStrategies()
})

useHead({ title: '策略说明 · 持仓盯盘' })
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-6">
      <h1 class="text-2xl font-bold">策略说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        数据来自 <code>strategy</code> 注册表，与 <code>/api/strategies</code> 同源；有回测选股产物的策略会展示最新名单（见 <code>strategy_picks_loader.py</code>）。改策略或跑回测后重启 watch。
      </p>
    </header>

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <div v-else class="space-y-4">
      <div
        v-for="tab in strategies"
        :id="tab.id"
        :key="tab.id"
        class="scroll-mt-24"
      >
        <StrategyInfoPanel :tab="tab" />
        <StrategyPicksPanel :picks="tab.picks" />
        <div v-if="tab.id === 'strategy3' && tab.backtest?.length" class="card mt-3 p-4">
          <h3 class="text-sm font-bold">回测摘要（研究）</h3>
          <p class="mt-1 text-xs text-ui-text-3">区间见 summary.json · 非投资建议</p>
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
          <p v-if="tab.reportPath" class="mt-2 text-xs text-ui-text-3">报告：{{ tab.reportPath }}</p>
        </div>
        <p v-if="tab.aliases?.length" class="mt-2 text-xs text-ui-text-3">
          别名：{{ tab.aliases.join('、') }}
        </p>
        <p v-if="tab.implemented === false" class="mt-1 text-xs text-ui-text-3">（尚未完整实现）</p>
      </div>
    </div>

    <p v-if="!loading && !error && !strategies.length" class="text-sm text-ui-text-2">暂无注册策略。</p>
  </div>
</template>
