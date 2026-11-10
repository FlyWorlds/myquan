export interface TradingPlan {
  id: string
  title: string
  code?: string
  name?: string
  date: string
  direction: '买入' | '卖出' | '加仓' | '减仓' | '观察' | string
  target_price?: number | null
  stop_loss?: number | null
  target_profit?: number | null
  planned_position?: string
  strategy_tag?: string
  content?: string
  status: 'pending' | 'executed' | 'cancelled' | string
  pinned: boolean
  created_at?: string
  updated_at?: string
}
