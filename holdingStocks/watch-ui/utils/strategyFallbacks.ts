import type { StrategyEntry } from '~/types/registry'

/** 旧版 watch API 无 strategy12 时前端兜底。 */
export const FALLBACK_STRATEGIES: StrategyEntry[] = [
  {
    id: 'strategy12',
    label: '策略12-情绪门控开盘突破',
    name: '策略十二·情绪门控开盘突破',
    description:
      '因子18 恐慌日禁止新开仓 + 因子1 开盘±2.5% 执行 + 因子2 回撤预警；研究组合，非默认盯盘。',
    aliases: ['s12', 'emotion_gate', '情绪门控', '策略十二'],
    implemented: true,
    is_watch_default: false,
    watch_tab: false,
    registry_kind: 'combo',
    registry_kind_label: '因子组合',
    factors: [
      {
        id: 'factor18',
        name: '因子18-低开跌停情绪',
        role: '门控',
        filter_desc: '中证1000 低开开盘跌停≥4（恐慌）→ 当日禁止新开仓',
      },
      {
        id: 'factor1',
        name: '因子1-开盘突破',
        role: '买卖',
        filter_desc: '同策略一：前日阴/小阳 + 禁双阳跨日；恐慌日不新开',
      },
      {
        id: 'factor2',
        name: '因子2-回撤预警',
        role: '预警/叠加',
        filter_desc: '回测不注资',
      },
    ],
    reportPath: 'backtest/strategy12_emotion_gate/REPORT.md',
  },
]

export function mergeFallbackStrategies(list: StrategyEntry[]): StrategyEntry[] {
  const cleaned = list.filter((s) => s.id !== 'strategy9')
  const ids = new Set(cleaned.map((s) => s.id))
  const extra = FALLBACK_STRATEGIES.filter((s) => !ids.has(s.id))
  return extra.length ? [...cleaned, ...extra] : cleaned
}
