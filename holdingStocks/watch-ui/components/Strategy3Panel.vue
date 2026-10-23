<script setup lang="ts">
import type { Strategy3Payload, StrategyTab } from '~/types/snapshot'
import { baiduStockUrl } from '~/utils/stockLink'
const props = defineProps<{ tab?: StrategyTab; payload?: Strategy3Payload; phase?: string }>()
const manualPayload = ref<Strategy3Payload | null>(null)
const payload = computed(() => manualPayload.value || props.payload)
const job = ref<{ state: string; message?: string; done?: number; total?: number }>({ state: 'idle' })
const scanError = ref('')
const submitting = ref(false)
const scanning = computed(() => submitting.value || ['starting', 'running'].includes(job.value.state))
let scanTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
async function loadScan() {
  try {
    const r = await fetch('/api/strategy3/scan', { cache: 'no-store', signal: AbortSignal.timeout(15000) })
    if (!r.ok) throw new Error(`扫描状态读取失败（${r.status}）`)
    const data = await r.json()
    job.value = data.job
    manualPayload.value = data.payload
    scanError.value = ''
  } catch (e) { scanError.value = e instanceof Error ? e.message : '扫描状态读取失败' }
  finally { if (!disposed) scanTimer = setTimeout(loadScan, scanning.value ? 3000 : 10000) }
}
async function startScan() {
  if (scanning.value) return
  submitting.value = true
  try {
    const r = await fetch('/api/strategy3/scan', { method: 'POST' })
    if (!r.ok) throw new Error(`扫描启动失败（${r.status}）`)
    const data = await r.json(); job.value = data.job; scanError.value = ''
    if (scanTimer) clearTimeout(scanTimer)
    await loadScan()
  } catch (e) { scanError.value = e instanceof Error ? e.message : '扫描启动失败' }
  finally { submitting.value = false }
}
onMounted(() => { void loadScan() })
onBeforeUnmount(() => { disposed = true; if (scanTimer) clearTimeout(scanTimer) })
const rows = computed(() => payload.value?.rows || [])
const policy = computed(() => payload.value?.policy)
const triggerLabel = computed(() => ({ shadow: '放量后下影线', recover: '放量后收复前低', either: '放量后下影线或收复前低' } as Record<string, string>)[payload.value?.factorResearch?.rule.trigger || ''] || '等待研究配置')
const stopLabel = computed(() => {
  const p = policy.value
  if (!p) return '—'
  if (p.stop_mode === 'cost') return `成本跌${(p.stop * 100).toFixed(1)}%`
  const parts = [p.stop_buffer_pct ? `${(p.stop_buffer_pct * 100).toFixed(1)}%` : '', p.stop_buffer_atr ? `${p.stop_buffer_atr}ATR` : ''].filter(Boolean)
  return parts.length ? `C下方${parts.join(' + ')}` : '跌破C即退'
})
const pct = (v?: number | null) => v == null ? '—' : `${(v * 100).toFixed(1)}%`
const num = (v?: number | null) => v == null ? '—' : v.toFixed(2)
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap justify-between gap-2">
        <h3 class="text-base font-bold">鲍鱼捞饭 · 日线破位止跌</h3>
        <div class="flex items-center gap-3">
          <span class="text-xs text-amber-600">手动监控 · 不自动买入</span>
          <button class="rounded-lg bg-accent px-3 py-2 text-sm text-white disabled:opacity-50" :disabled="scanning" @click="startScan">{{ scanning ? '扫描中…' : '扫描中证1000监控票' }}</button>
        </div>
      </div>
      <p class="mt-2 text-sm text-ui-text-2">底分型 A → 向上一笔 → 顶分型 B → 相邻下行笔破 A → 量价衰竭观察</p>
      <p class="mt-2 text-sm">{{ job.message || '尚未扫描，股票池为空' }}<template v-if="job.total">（{{ job.done || 0 }}/{{ job.total }}）</template></p>
      <p v-if="scanError || job.state === 'error'" class="mt-2 text-sm text-red-500">{{ scanError || job.message }}</p>
      <p class="mt-2 text-xs text-ui-text-3">范围：中证1000，剔除ST、科创板、创业板、新三板。符合范围 {{ payload?.scanCoverage?.universeCount ?? 0 }} 只，日线齐备 {{ payload?.scanCoverage?.scannedCount ?? 0 }} 只，前低破位预警 {{ payload?.scanCoverage?.warningCount ?? 0 }} 只，鲍鱼捞饭 {{ payload?.scanCoverage?.candidateCount ?? 0 }} 只。扫描日线截至 {{ payload?.poolDate || '尚未扫描' }}。</p>
      <p v-if="payload?.scanCoverage" class="mt-1 text-xs text-ui-text-3">过期 {{ payload.scanCoverage.counts.stale || 0 }}，缺行情 {{ payload.scanCoverage.counts.missing || 0 }}，失败 {{ payload.scanCoverage.counts.error || 0 }}；信号有效：{{ payload.scanCoverage.valid ? '是' : '否' }}。点击按钮会更新行情，可能需要数分钟。</p>
      <p class="mt-2 text-xs text-amber-600">{{ payload?.cacheNote }}</p>
      <p class="mt-2 text-sm text-accent">已绑定：{{ payload?.boundFactors?.join(" → ") || "因子30 → 因子31 → 因子32" }}</p>
      <div v-if="policy" class="mt-3 grid gap-3 text-sm sm:grid-cols-3">
        <div>破位深度 {{ pct(policy.depth) }}<br>介入：{{ triggerLabel }}</div>
        <div>单票资金上限 {{ pct(policy.slot) }}<br><template v-if="policy.risk_budget">每笔名义风险 {{ pct(policy.risk_budget) }}，按止损距离缩放股数；不补仓</template><template v-else>初仓占额度 {{ pct(policy.initial) }}，不补仓</template></div>
        <div>{{ stopLabel }} · 最长 {{ policy.hold }} 交易日<br>
          {{ policy.stop_trigger === 'intraday' ? '过夜持仓触价退出；买日触线次开处理' : '收盘确认跌破，次开退出' }}<br>
          <template v-if="policy.take_mode === 'structure'">A下先到A减{{ pct(policy.reduce) }}，余仓到B或回落/到期；已收复A则目标B</template>
          <template v-else>涨{{ pct(policy.take) }}减{{ pct(policy.reduce) }}，余仓峰值回落3%退出</template></div>
      </div>
    </section>
    <section v-if="payload?.backtest?.length" class="card overflow-x-auto p-4">
      <h3 class="font-bold">历史回测 · 扩展子集与原30股分开标注，含覆盖/选股偏差</h3>
      <table class="mt-3 min-w-full text-sm">
        <thead><tr><th class="p-2 text-left">区间</th><th>收益</th><th>日线最大回撤</th><th>夏普</th><th>闭环笔数</th><th>胜率</th></tr></thead>
        <tbody><tr v-for="b in payload.backtest" :key="b.label" class="border-t border-ui-hairline">
          <td class="p-2">{{ b.label }}</td><td>{{ num(b.total_return_pct) }}%</td><td>{{ num(b.max_drawdown_pct) }}%</td><td>{{ num(b.sharpe_ratio) }}</td><td>{{ b.n_trades }}</td><td>{{ pct(b.win_rate) }}</td>
        </tr></tbody>
      </table>
    </section>
    <section class="card p-4">
      <h3 class="font-bold">A前低 · B前高 · C破位止跌低点</h3>
      <p class="mt-2 text-xs text-ui-text-3">参考止损及目标按最新完整日线收盘估算，次开用实际价格重新评估；实际介入时冻结C，买后不会跟随新低下移。</p>
      <div class="mt-3 watch-table-wrap"><table class="watch-sticky-table">
        <thead><tr><th>标的</th><th>状态</th><th>前低A</th><th>前高B</th><th>止跌低点C</th><th>参考止损</th><th>风险距离</th><th>第一目标</th><th>第二目标</th><th>空间/风险</th><th>量比/破位最大</th><th>研究信号</th><th>日线截至</th></tr></thead>
        <tbody><tr v-for="r in rows" :key="r.代码" class="border-t border-ui-hairline" :class="r.候选信号 ? 'bg-emerald-500/10' : ''">
          <td class="p-2"><span v-if="r.候选信号" class="mb-1 inline-block whitespace-nowrap rounded bg-emerald-500/20 px-2 py-1 text-xs font-bold text-emerald-600">★ 鲍鱼捞饭 · 已触发</span><StockNameHover :code="r.代码" :name="r.名称"><a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="text-accent">{{ r.名称 }} {{ r.代码 }}</a></StockNameHover></td>
          <td class="p-2">{{ r.状态 }}</td><td>{{ num(r.前底) }}</td><td>{{ num(r.前高) }}</td><td>{{ num(r.止跌低点) }}</td><td>{{ num(r.参考止损) }}</td><td>{{ pct(r.止损距离) }}</td><td>{{ num(r.第一目标) }}</td><td>{{ num(r.第二目标) }}</td><td>{{ num(r.空间风险比) }}</td><td>{{ num(r.量比) }} / {{ num(r.破位最大量比) }}</td><td><span v-if="r.候选信号" class="rounded bg-emerald-500/15 px-2 py-1 text-emerald-600 font-bold">鲍鱼捞饭</span><span v-else-if="r.破位预警" class="rounded bg-amber-500/15 px-2 py-1 text-amber-600">破前低预警</span><span v-else>结果已过期</span></td><td>{{ r.数据截至 || '—' }}</td>
        </tr><tr v-if="!rows.length"><td colspan="13" class="p-6 text-center text-ui-text-3">暂无监控票；点击上方按钮扫描，有破前低预警的票才进入列表</td></tr></tbody>
      </table></div>
    </section>
  </div>
</template>
