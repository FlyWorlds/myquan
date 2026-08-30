import type { SectorCell, SectorKindPayload, SectorRotationPayload } from '~/types/sectors'
import type { SectorsConceptToday } from '~/types/snapshot'

function boardRowFromLive(name: string, live: SectorsConceptToday) {
  return {
    板块: name,
    label: live.code || '',
    涨跌幅: live.涨跌幅 ?? null,
    涨停数: 0,
    资金: live.资金 ?? null,
    资金口径: live.资金口径 || '成交额',
    领涨名称: '',
    领涨涨幅: null,
  }
}

function rankDay(
  boards: Array<Record<string, unknown>>,
  metric: string,
  topN: number,
): [SectorCell[], SectorCell[]] {
  const field = metric === '涨幅' ? '涨跌幅' : metric === '涨停数' ? '涨停数' : '资金'
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

/** 用 WS 推送的 conceptToday 覆盖热力表最后一列（今日）并重新排名。 */
export function mergeLiveTodayColumn(
  base: SectorKindPayload,
  conceptToday: Record<string, SectorsConceptToday> | undefined,
  topN: number,
): SectorKindPayload {
  if (!conceptToday || !Object.keys(conceptToday).length) return base

  const boards = Object.entries(conceptToday).map(([name, live]) => boardRowFromLive(name, live))
  const metrics = ['涨幅', '涨停数', '资金'] as const
  const byMetric = { ...base.by_metric }

  for (const metric of metrics) {
    const [top, bottom] = rankDay(boards, metric, topN)
    const tops = (byMetric[metric]?.top || []).map((col) => [...col])
    const bottoms = (byMetric[metric]?.bottom || []).map((col) => [...col])
    const last = Math.max(tops.length - 1, 0)
    tops[last] = top
    bottoms[last] = bottom
    byMetric[metric] = { top: tops, bottom: bottoms }
  }

  return { ...base, by_metric: byMetric }
}

export function useSectorsLive() {
  const store = useWatchStore()
  const sectors = computed(() => store.snapshot?.sectors)
  const liveAt = computed(() => sectors.value?.spotAt || store.snapshot?.updatedAt || '')
  const refreshSec = computed(() => store.snapshot?.refreshSec || 5)

  async function setFocus(concept: string | null) {
    const qs = concept ? `?concept=${encodeURIComponent(concept)}` : ''
    await $fetch(`/api/sectors/focus${qs}`, { cache: 'no-store' })
  }

  function mergedKind(
    base: SectorKindPayload | null,
    topN: number,
  ): SectorKindPayload | null {
    if (!base) return null
    return mergeLiveTodayColumn(base, sectors.value?.conceptToday, topN)
  }

  return { sectors, liveAt, refreshSec, setFocus, mergedKind }
}
