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
const intradayScan = computed(() => payload.value?.scanMode === 'intraday')
const panicThreshold = 0.7
const panicRate = computed(() => {
  const data = payload.value
  if (data?.scanCoverage?.valid === false) return null
  if (data?.panic?.rate != null) return data.panic.rate
  const coverage = data?.scanCoverage
  return coverage?.valid && coverage.scannedCount > 0 && coverage.warningCount != null
    ? coverage.warningCount / coverage.scannedCount : null
})
const panicAlert = computed(() => panicRate.value != null && panicRate.value > panicThreshold)
const panicProgress = computed(() => Math.min(100, Math.max(0, (panicRate.value ?? 0) * 100)))
const panicHorizon = ref(10)
const panicPeriod = ref('all')
const panicBuckets = computed(() => {
  const study = payload.value?.panicStudy
  const buckets = panicPeriod.value === 'recent' ? study?.recentBuckets : panicPeriod.value === 'earlier' ? study?.earlierBuckets : study?.buckets
  return buckets?.filter(b => b.horizon === panicHorizon.value) || []
})
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
      <div class="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2">
        <p class="text-sm">{{ job.message || '尚未扫描，股票池为空' }}<template v-if="job.total">（{{ job.done || 0 }}/{{ job.total }}）</template></p>
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="font-bold">恐慌度指标</span>
        <span class="group relative inline-flex" tabindex="0" aria-label="恐慌度指标说明" aria-describedby="strategy3-panic-help">
          <i class="flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-ui-hairline-strong text-xs not-italic text-ui-text-3">i</i>
          <span id="strategy3-panic-help" role="tooltip" class="card invisible absolute -left-28 top-full z-50 mt-2 w-72 max-w-[80vw] p-3 text-xs leading-relaxed text-ui-text-2 opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100">
            恐慌度＝前低破位预警股票数 ÷ 有效监测股票总数。盘中扫描在交易日9:25起可用：9:25–9:30取正式开盘价，9:30后取扫描时最新价，低于结构前低A计入盘中预警；缺失或过期报价不计入分母。暂定70%为观察档位，大于70%时显示警戒色，等于70%不触发警戒。历史70%–80%区间的10日扣费盈利比例约68.8%，但样本仅覆盖19个信号日，暂定档位来自完整日线研究，盘中结果仍需后续验证；警戒提示不代表自动买入信号。扫描过期或无有效监测数据时显示“—”。
          </span>
        </span>
        <span class="font-bold tabular-nums" :class="panicAlert ? 'text-ui-danger' : 'text-ui-text'">{{ pct(panicRate) }}</span>
        <div class="relative h-2.5 w-36 rounded-full bg-ui-hairline" role="progressbar" aria-label="恐慌度" :aria-valuenow="panicRate == null ? undefined : panicProgress" :aria-valuetext="panicRate == null ? '暂无有效扫描数据' : pct(panicRate)" :aria-valuemin="0" :aria-valuemax="100">
          <div class="h-full rounded-full transition-all" :class="panicAlert ? 'bg-red-500' : 'bg-accent'" :style="{ width: `${panicProgress}%` }" />
          <span class="absolute -top-0.5 h-3.5 w-px bg-ui-text-3" :style="{ left: `${panicThreshold * 100}%` }" aria-hidden="true" />
        </div>
        <span class="rounded px-2 py-1 text-xs" :class="panicAlert ? 'bg-red-500/15 text-ui-danger' : 'text-ui-text-3'">{{ panicAlert ? '恐慌警戒 · 超过70%' : '暂定警戒线 70%' }}</span>
      </div>
      </div>
      <p v-if="scanError || job.state === 'error'" class="mt-2 text-sm text-red-500">{{ scanError || job.message }}</p>
      <p class="mt-2 text-xs text-ui-text-3">范围：中证1000，剔除ST、科创板、创业板、新三板。符合范围 {{ payload?.scanCoverage?.universeCount ?? 0 }} 只，有效监测 {{ payload?.scanCoverage?.scannedCount ?? 0 }} 只，前低破位预警 {{ payload?.scanCoverage?.warningCount ?? 0 }} 只，鲍鱼捞饭 {{ payload?.scanCoverage?.candidateCount ?? 0 }} 只。{{ intradayScan ? '盘中扫描日' : '扫描日线截至' }} {{ payload?.poolDate || '尚未扫描' }}。</p>
      <p v-if="intradayScan" class="mt-1 text-xs text-accent">盘中快照 · 历史日线截至 {{ payload?.historyDate }} · 报价采集始于 {{ payload?.scanStartedAt }}。9:25–9:30按竞价确定的开盘价，9:30后按采集时最新价；各股票报价时间见列表，点击扫描更新。</p>
      <p v-if="payload?.scanCoverage" class="mt-1 text-xs text-ui-text-3">过期 {{ payload.scanCoverage.counts.stale || 0 }}，缺行情 {{ payload.scanCoverage.counts.missing || 0 }}，失败 {{ payload.scanCoverage.counts.error || 0 }}<template v-if="intradayScan">，缺报价 {{ payload.scanCoverage.counts.missing_quote || 0 }}，旧报价 {{ payload.scanCoverage.counts.stale_quote || 0 }}，无效报价 {{ (payload.scanCoverage.counts.invalid_quote || 0) + (payload.scanCoverage.counts.unconfirmed_quote || 0) + (payload.scanCoverage.counts.future_quote || 0) }}</template>；信号有效：{{ payload.scanCoverage.valid ? '是' : '否' }}。点击按钮会更新行情，可能需要数分钟。</p>
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
    <section class="card p-4">
      <template v-if="payload?.panicStudy">
        <div class="mt-4 flex items-center gap-3"><h4 class="font-bold">恐慌度与买后盈利比例</h4><select v-model="panicHorizon" class="rounded border border-ui-hairline bg-transparent p-1"><option :value="5">持有5根日线</option><option :value="10">持有10根日线</option><option :value="20">持有20根日线</option></select><select v-model="panicPeriod" class="rounded border border-ui-hairline bg-transparent p-1"><option value="all">全部历史</option><option value="earlier">2025年前</option><option value="recent">2025年起</option></select></div>
        <p class="mt-2 text-xs text-ui-text-3">信号日期 {{ payload.panicStudy.period.join(' 至 ') }}，截至 {{ payload.panicStudy.asOf }}。成功＝扣费后收益大于0；以下是固定持有期事件研究。</p>
        <div class="mt-3 overflow-x-auto"><table class="min-w-full text-sm"><thead><tr><th>恐慌度</th><th>完成样本</th><th>信号日数</th><th>盈利比例</th><th>平均收益</th><th>描述性95%区间</th></tr></thead><tbody><tr v-for="b in panicBuckets" :key="b.label" class="border-t border-ui-hairline text-center"><td class="p-2">{{ b.label }}</td><td>{{ b.n }}</td><td>{{ b.days }}</td><td>{{ pct(b.winRate) }}</td><td>{{ num(b.meanReturnPct) }}{{ b.meanReturnPct == null ? '' : '%' }}</td><td>{{ b.interval ? b.interval.map(v => pct(v)).join(' ～ ') : '—' }}</td></tr></tbody></table></div>
        <p class="mt-3 text-xs text-amber-600">{{ payload.panicStudy.note }} 分组左闭右开，最后一组包含100%。样本少或集中在少数日期时，不能据此认定最佳买入阈值。</p>
      </template>
      <p v-else class="mt-3 text-sm text-ui-text-3">尚无匹配本次扫描与配置的历史研究结果，暂不能判断哪个恐慌度区间买后成功率更高。</p>
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
      <p class="mt-2 text-xs text-ui-text-3">{{ intradayScan ? '参考止损及目标按本次盘中报价估算，盘中形态仅供观察，收盘前可变化。' : '参考止损及目标按最新完整日线收盘估算，次开用实际价格重新评估。' }}实际介入时冻结C，买后不会跟随新低下移。</p>
      <div class="mt-3 watch-table-wrap"><table class="watch-sticky-table">
        <thead><tr><th>标的</th><th>状态</th><th>判定价格</th><th>前低A</th><th>前高B</th><th>止跌低点C</th><th>参考止损</th><th>风险距离</th><th>第一目标</th><th>第二目标</th><th>空间/风险</th><th>量比/破位最大</th><th>研究信号</th><th>{{ intradayScan ? '报价时间' : '日线截至' }}</th></tr></thead>
        <tbody><tr v-for="r in rows" :key="r.代码" class="border-t border-ui-hairline" :class="r.候选信号 ? 'bg-emerald-500/10' : ''">
          <td class="p-2"><span v-if="r.候选信号" class="mb-1 inline-block whitespace-nowrap rounded bg-emerald-500/20 px-2 py-1 text-xs font-bold text-emerald-600">{{ r.盘中观察 ? '★ 鲍鱼捞饭 · 盘中候选' : '★ 鲍鱼捞饭 · 已触发' }}</span><StockNameHover :code="r.代码" :name="r.名称"><a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="text-accent">{{ r.名称 }} {{ r.代码 }}</a></StockNameHover></td>
          <td class="p-2">{{ r.状态 }}<span v-if="r.盘中观察" class="block text-xs text-amber-600">盘中观察</span></td><td>{{ num(r.现价) }}<span v-if="r.行情基准" class="block text-xs text-ui-text-3">{{ r.行情基准 === 'auction_open' ? '竞价开盘价' : r.行情基准 === 'live_last' ? '盘中最新价' : '日线收盘价' }}</span></td><td>{{ num(r.前底) }}</td><td>{{ num(r.前高) }}</td><td>{{ num(r.止跌低点) }}</td><td>{{ num(r.参考止损) }}</td><td>{{ pct(r.止损距离) }}</td><td>{{ num(r.第一目标) }}</td><td>{{ num(r.第二目标) }}</td><td>{{ num(r.空间风险比) }}</td><td>{{ num(r.量比) }} / {{ num(r.破位最大量比) }}</td><td><span v-if="r.候选信号" class="rounded bg-emerald-500/15 px-2 py-1 text-emerald-600 font-bold">{{ r.盘中观察 ? '盘中候选' : '鲍鱼捞饭' }}</span><span v-else-if="r.破位预警" class="rounded bg-amber-500/15 px-2 py-1 text-amber-600">破前低预警</span><span v-else>结果已过期</span></td><td>{{ r.数据截至 || '—' }}</td>
        </tr><tr v-if="!rows.length"><td colspan="14" class="p-6 text-center text-ui-text-3">暂无监控票；点击上方按钮扫描，有破前低预警的票才进入列表</td></tr></tbody>
      </table></div>
    </section>
  </div>
</template>
