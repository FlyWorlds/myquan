import type { FactorCategory, FactorEntry } from '~/types/registry'

/** 与 strategy/factors/categories.py 对齐：即使旧版 /api/factors 无 category 也能分组。 */
export const FACTOR_CATEGORY_CATALOG: FactorCategory[] = [
  { id: 'execution', label: '开盘执行', hint: '开盘突破买卖、止损与 T+1。' },
  { id: 'drawdown', label: '回撤补仓', hint: '回撤加减仓预警，默认回测不注资。' },
  { id: 'take_profit', label: '止盈持股', hint: '牛市持股 / 放宽止损。' },
  { id: 'momentum', label: '动量', hint: '动量、近高、ETF 轮动、价格选股。' },
  { id: 'reversal', label: '反转', hint: '超跌反转、流动性门控。' },
  { id: 'chan', label: '缠论', hint: '结构买卖点与笔盈亏比。' },
  { id: 'sentiment', label: '情绪题材', hint: '涨停/跌停情绪、题材共振、前瞻主题。' },
  { id: 'quality', label: '选股质量', hint: '契合池、熊盾、龙头排序。' },
]

const FACTOR_CATEGORY_BY_ID: Record<string, string> = {
  factor1: 'execution',
  factor2: 'drawdown',
  factor3: 'momentum',
  factor4: 'take_profit',
  factor5: 'sentiment',
  factor6: 'momentum',
  factor7: 'momentum',
  factor8: 'chan',
  factor9: 'momentum',
  factor10: 'momentum',
  factor11: 'momentum',
  factor12: 'reversal',
  factor13: 'quality',
  factor13a: 'quality',
  factor13b: 'quality',
  factor14: 'sentiment',
  factor15: 'sentiment',
  factor16: 'quality',
  factor17: 'chan',
  factor18: 'sentiment',
  factor19: 'reversal',
  factor20: 'reversal',
  factor21: 'reversal',
  factor22: 'momentum',
  factor23: 'take_profit',
  factor24: 'sentiment',
  factor25: 'take_profit',
  factor26: 'execution',
  cf1: 'reversal',
}

const CATALOG_IDS = new Set(FACTOR_CATEGORY_CATALOG.map((c) => c.id))

export function resolveFactorCategory(factor: FactorEntry): string {
  const raw = String(factor.category || '').trim()
  if (raw && CATALOG_IDS.has(raw)) return raw
  const byId = FACTOR_CATEGORY_BY_ID[String(factor.id || '')]
  if (byId) return byId
  return 'momentum'
}

export function withResolvedCategory(factor: FactorEntry): FactorEntry {
  const category = resolveFactorCategory(factor)
  const cat = FACTOR_CATEGORY_CATALOG.find((c) => c.id === category)
  return {
    ...factor,
    category,
    category_label: factor.category_label || cat?.label || category,
  }
}

/** 旧版 watch API 不含 17/18 时，前端兜底补进列表（热更新即可看见）。 */
export const FALLBACK_FACTORS: FactorEntry[] = [
  {
    id: 'factor17',
    name: '因子17-缠论笔盈亏比',
    category: 'chan',
    category_label: '缠论',
    implemented: true,
    description:
      '日线笔归因：因子1费用后盈亏按买入笔记账，跨笔卖点平移；可 bind_factor(\'factor17\') 挂到任意策略。评估因子，不单独下单。',
    rules_text:
      '因子17-缠论笔盈亏比\n  · 级别：日线·笔（CZSC）\n  · 交易对照：因子1 开盘±pct，费用口径 strategy.costs\n  · 记账：闭环收益记入买入所在笔；卖点跨笔则卖价平移\n  · 向上笔让利 / 向下笔防守 / 盈亏比（费用后）\n  · 挂策略：bind_factor("factor17", role="custom")\n研究用途，非投资建议。',
    used_by: [],
  },
  {
    id: 'factor18',
    name: '因子18-低开跌停情绪',
    category: 'sentiment',
    category_label: '情绪题材',
    implemented: true,
    description: '中证1000 低开开盘跌停家数：平静≤0 / 恐慌≥4；策略十二恐慌日空仓。',
    rules_text:
      '因子18-低开跌停情绪\n  · 宇宙：中证1000\n  · 低开开盘即跌停 → 平静≤0 · 正常1～3 · 恐慌≥4\n  · 策略十二：恐慌日空仓\n研究用途，非投资建议。',
    used_by: [
      {
        id: 'strategy12',
        name: '策略十二·涨停次日低开',
        label: '策略12-涨停次日低开',
        role: '择时',
        registry_kind: 'combo',
      },
    ],
  },
  {
    id: 'factor19',
    name: '因子19-低开反包',
    category: 'reversal',
    category_label: '反转',
    implemented: true,
    description:
      '压力日低开 -8%～-0.5%，开盘买入、T+1 收盘清。旧假设，组合未过关。',
    rules_text:
      '因子19-低开反包\n  · 择时：因子18 家数≥1\n  · 个股：gap ∈ [-8%, -0.5%]\n  · 执行：开盘买入；T+1 收盘清仓\n研究用途，非投资建议。',
    used_by: [],
  },
  {
    id: 'factor20',
    name: '因子20-跌停次日开板',
    category: 'reversal',
    category_label: '反转',
    implemented: true,
    description: '昨日收盘跌停、今日开盘未封死。已否决，组合未过关。',
    rules_text:
      '因子20-跌停次日开板\n  · 昨收跌停且今开未封\n  · 恐慌日空仓\n研究用途，未过关。',
    used_by: [],
  },
  {
    id: 'factor21',
    name: '因子21-涨停次日低开',
    category: 'reversal',
    category_label: '反转',
    implemented: true,
    description:
      '昨日收盘涨停、今日低开 -4.5%～-0.3% 且未封涨停；因子18 恐慌日空仓；开盘买、T+1 收盘清。',
    rules_text:
      '因子21-涨停次日低开\n  · 昨收涨停且今低开带内\n  · 恐慌日空仓\n  · 开盘买入，T+1 收盘清\n研究用途，非投资建议。',
    used_by: [
      {
        id: 'strategy12',
        name: '策略十二·涨停次日低开',
        label: '策略12-涨停次日低开',
        role: '选股',
        registry_kind: 'combo',
      },
    ],
  },
  {
    id: 'factor22',
    name: '因子22-收盘动量',
    category: 'momentum',
    category_label: '动量',
    implemented: true,
    description:
      '因子1 止损后，收盘≥当日最低价×(1+pct) 则同日再买；默认 pct=1%；已挂策略一。',
    rules_text:
      '因子22-收盘动量\n  · 前置：因子1 当日已止损\n  · 收盘≥low×(1+pct) 再买\n  · 默认 pct=1%，可选收阳/收阴\n已挂策略一。',
    used_by: [
      {
        id: 'strategy1',
        name: '援军战法',
        label: '策略一',
        role: '止损后再买',
        registry_kind: 'combo',
      },
    ],
  },
]

export function mergeFallbackFactors(list: FactorEntry[]): FactorEntry[] {
  const ids = new Set(list.map((f) => f.id))
  const extra = FALLBACK_FACTORS.filter((f) => !ids.has(f.id))
  return [...list, ...extra]
}
