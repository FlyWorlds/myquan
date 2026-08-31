import type { StrategyEntry } from '~/types/registry'

/** 旧版 watch API 无 strategy12 时前端兜底。 */
export const FALLBACK_STRATEGIES: StrategyEntry[] = [
  {
    id: 'strategy12',
    label: '策略12-涨停次日低开',
    name: '策略十二·涨停次日低开',
    description:
      '昨日收盘涨停、今日低开未封涨停则开盘买，T+1 收盘清；因子18 恐慌日空仓。中证1000 截面。研究组合，非默认盯盘。',
    aliases: ['s12', 'lu_next_gap', '涨停次日低开', '策略十二'],
    implemented: true,
    is_watch_default: false,
    watch_tab: false,
    registry_kind: 'combo',
    registry_kind_label: '因子组合',
    factors: [
      {
        id: 'factor18',
        name: '因子18-低开跌停情绪',
        role: '过滤',
        filter_desc: '低开开盘跌停家数≥4（恐慌）→ 当日空仓',
      },
      {
        id: 'factor21',
        name: '因子21-涨停次日低开',
        role: '买卖',
        filter_desc: '昨收涨停、今低开 -4.5%～-0.3%；开盘买，T+1 收盘清',
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
