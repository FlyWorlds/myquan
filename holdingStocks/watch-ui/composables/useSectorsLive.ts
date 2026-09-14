import type { SectorCell, SectorKindPayload } from '~/types/sectors'
import type { SectorsConceptToday } from '~/types/snapshot'

export const ROTATION_METRICS = [
  '涨幅',
  '涨停数',
  '涨跌比',
  '成交额',
  '主力净额',
  '强度',
] as const

export type RotationMetric = (typeof ROTATION_METRICS)[number]

const METRIC_FIELD: Record<RotationMetric, string> = {
  涨幅: '涨跌幅',
  涨停数: '涨停数',
  涨跌比: '涨跌比',
  成交额: '资金',
  主力净额: '主力净额',
  强度: '强度',
}

export function formatMetricValue(metric: string, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-'
  const x = Number(v)
  if (metric === '涨幅') return `${x.toFixed(2)}%`
  if (metric === '涨停数') return String(Math.round(x))
  if (metric === '涨跌比') return x.toFixed(2)
  if (metric === '强度') return x.toFixed(2)
  const abs = Math.abs(x)
  if (abs >= 1e8) return `${(x / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(x / 1e4).toFixed(1)}万`
  return x.toFixed(0)
}

function boardRowFromLive(name: string, live: SectorsConceptToday) {
  return {
    板块: name,
    label: live.code || '',
    涨跌幅: live.涨跌幅 ?? null,
    涨停数: live.涨停数 ?? 0,
    涨跌比: live.涨跌比 ?? null,
    资金: live.资金 ?? null,
    资金口径: live.资金口径 || '成交额',
    主力净额: live.主力净额 ?? null,
    强度: live.强度 ?? null,
    领涨名称: '',
    领涨涨幅: null,
  }
}

function rankDay(
  boards: Array<Record<string, unknown>>,
  metric: string,
  topN: number,
): [SectorCell[], SectorCell[]] {
  const field = METRIC_FIELD[metric as RotationMetric] || '涨跌幅'
  const rows = boards.filter((b) => b[field] != null)
  rows.sort((a, b) => Number(b[field] || 0) - Number(a[field] || 0))

  const cell = (b: Record<string, unknown>, rank: number): SectorCell => ({
    name: String(b['板块'] || ''),
    value: b[field] as number | null,
    rank,
    label: String(b['label'] || ''),
    metric,
  })

  const top = rows.slice(0, topN).map((b, i) => cell(b, i + 1))
  const weak = rows.length >= topN ? rows.slice(-topN) : rows
  const bottom = weak.map((b, i) => cell(b, topN - i))
  return [top, bottom]
}

export function todaySessionLabel(now = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${m}月${d}日`
}

/** 优先用盯盘 clock（服务器本地日），避免浏览器时区把「今日」算错。 */
export function sessionLabelFromClock(clock?: string, fallback = new Date()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(clock || '').trim())
  if (m) return `${m[2]}月${m[3]}日`
  return todaySessionLabel(fallback)
}

function moveColToFront<T>(cols: T[][], fromIdx: number): T[][] {
  if (fromIdx <= 0 || fromIdx >= cols.length) return cols
  const next = cols.map((col) => [...col])
  const [picked] = next.splice(fromIdx, 1)
  next.unshift(picked)
  return next
}

/** 用 WS 推送的 conceptToday 写入热力表最左「今日」列并重新排名。dates[0] 必须是当日。 */
export function mergeLiveTodayColumn(
  base: SectorKindPayload,
  conceptToday: Record<string, SectorsConceptToday> | undefined,
  topN: number,
  metrics: string[] = [...ROTATION_METRICS],
  opts?: { clock?: string },
): SectorKindPayload {
  if (!conceptToday || !Object.keys(conceptToday).length) return base

  const boards = Object.entries(conceptToday).map(([name, live]) => boardRowFromLive(name, live))
  const todayLabel = sessionLabelFromClock(opts?.clock)
  const baseDates = [...(base.dates || [])]
  const foundIdx = baseDates.indexOf(todayLabel)
  let dates = baseDates
  if (foundIdx < 0) dates = [todayLabel, ...baseDates]
  else if (foundIdx > 0) dates = [todayLabel, ...baseDates.filter((_, i) => i !== foundIdx)]

  const byMetric = { ...base.by_metric }
  for (const metric of metrics) {
    const [top, bottom] = rankDay(boards, metric, topN)
    let tops = (byMetric[metric]?.top || []).map((col) => [...col])
    let bottoms = (byMetric[metric]?.bottom || []).map((col) => [...col])
    if (foundIdx < 0) {
      tops.unshift(top)
      bottoms.unshift(bottom)
    } else if (foundIdx === 0) {
      tops[0] = top
      bottoms[0] = bottom
    } else {
      tops = moveColToFront(tops, foundIdx)
      bottoms = moveColToFront(bottoms, foundIdx)
      tops[0] = top
      bottoms[0] = bottom
    }
    byMetric[metric] = { top: tops, bottom: bottoms }
  }

  return { ...base, dates, by_metric: byMetric }
}

export function useSectorsLive() {
  const store = useWatchStore()
  const sectors = computed(() => store.snapshot?.sectors)
  const liveAt = computed(() => sectors.value?.spotAt || store.snapshot?.updatedAt || '')
  const memberStatsAt = computed(() => sectors.value?.memberStatsAt || '')
  const refreshSec = computed(() => store.snapshot?.refreshSec || 5)

  async function setFocus(concept: string | null) {
    const qs = concept ? `?concept=${encodeURIComponent(concept)}` : ''
    await $fetch(`/api/sectors/focus${qs}`, { cache: 'no-store' })
  }

  function mergedKind(
    base: SectorKindPayload | null,
    topN: number,
    metrics?: string[],
  ): SectorKindPayload | null {
    const live = sectors.value?.conceptToday
    const clock = store.snapshot?.clock || store.snapshot?.updatedAt
    void store.snapshot?.ts
    void sectors.value?.spotAt
    if (!base) return null
    return mergeLiveTodayColumn(base, live, topN, metrics, { clock })
  }

  return { sectors, liveAt, memberStatsAt, refreshSec, setFocus, mergedKind, formatMetricValue }
}
