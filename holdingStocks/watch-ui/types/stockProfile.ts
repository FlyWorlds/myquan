export interface StockRelated {
  code: string
  name: string
  relation: string
  board: string
  kind: '行业' | '概念' | string
  role?: string | null
}

export interface StockTheme {
  name: string
  desc?: string
}

export interface StockProfile {
  code: string
  name: string
  full_name?: string | null
  market?: string | null
  industry?: string | null
  csrc_industry?: string | null
  region?: string | null
  chairman?: string | null
  employees?: string | null
  registered_capital?: string | null
  list_date?: string | null
  summary?: string | null
  business_scope?: string | null
  website?: string | null
  valuation?: {
    price?: number | null
    chg_pct?: number | null
    market_cap_yi?: number | null
    float_cap_yi?: number | null
    pe?: number | null
    pe_ttm?: number | null
    pb?: number | null
  }
  boards?: {
    industry?: string[]
    concept?: string[]
  }
  themes?: StockTheme[]
  related?: StockRelated[]
  chain?: {
    upstream?: StockRelated[]
    midstream?: StockRelated[]
    downstream?: StockRelated[]
    note?: string | null
  }
  sources?: string[]
  as_of?: string
  errors?: string[]
  error?: string
}
