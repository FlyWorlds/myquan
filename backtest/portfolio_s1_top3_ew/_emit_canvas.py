"""Emit portfolio-s1-top3-ew.canvas.tsx from _canvas_payload.json."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "_canvas_payload.json").read_text(encoding="utf-8"))
meta = data["meta"]

year_rows = [
    [r["年份"], r["组合策略%"], r["等权持有%"], r["超额%"], r["策略回撤%"], r["持有回撤%"]]
    for r in data["year_rows"]
]
year_tones = [r["_tone"] for r in data["year_rows"]]
recent_rows = [
    [r["日期"], str(r["持仓数"]), r["持仓"], r["买入"], r["卖出"]] for r in data["recent"]
]


def lit(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


tsx = f"""import {{
  BarChart,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  LineChart,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useHostTheme,
}} from "cursor/canvas";

const META = {lit(meta)};

const EQUITY_CATS = {lit(data["equity_cats"])};
const EQUITY_STRAT = {lit(data["equity_strat"])};
const EQUITY_BH = {lit(data["equity_bh"])};
const DD = {lit(data["dd"])};

const YEAR_CATS = {lit(data["year_cats"])};
const YEAR_STRAT = {lit(data["year_strat"])};
const YEAR_BH = {lit(data["year_bh"])};
const YEAR_EXCESS = {lit(data["year_excess"])};
const YEAR_ROWS = {lit(year_rows)};
const YEAR_TONES = {lit(year_tones)} as const;

const HOLD_DIST_CATS = {lit(data["hold_dist_cats"])};
const HOLD_DIST_VALS = {lit(data["hold_dist_vals"])};
const HOLD_CATS = {lit(data["hold_cats"])};
const HOLD_AVG = {lit(data["hold_avg"])};

const BUY_YEAR_CATS = {lit(data["buy_year_cats"])};
const BUY_YEAR_VALS = {lit(data["buy_year_vals"])};
const BUY_NAME_CATS = {lit(data["buy_name_cats"])};
const BUY_NAME_VALS = {lit(data["buy_name_vals"])};

const RECENT_ROWS = {lit(recent_rows)};

export default function PortfolioS1Top3Ew() {{
  const theme = useHostTheme();
  const caption = {{
    fontSize: 12,
    color: theme.textSecondary,
  }} as const;

  return (
    <Stack gap={{20}} style={{{{ padding: 20, maxWidth: 1100 }}}}>
      <Stack gap={{6}}>
        <H1>策略一 · 因子1 · 三票等权组合</H1>
        <Row gap={{8}} style={{{{ flexWrap: "wrap" }}}}>
          <Pill tone="info">{{META.names}}</Pill>
          <Pill>{{META.range}}</Pill>
          <Pill tone="neutral">初始 30 万 · 各票独立 10 万</Pill>
        </Row>
        <Text style={{caption}}>
          数据源：backtest/portfolio_s1_top3_ew（equity / yearly / daily_holdings / trades）· 净值曲线按月末抽样
        </Text>
      </Stack>

      <Grid columns={{4}} gap={{12}}>
        <Stat
          label="总收益率"
          value={{META.total.toFixed(1) + "%"}}
          tone="success"
        />
        <Stat
          label="年化收益"
          value={{META.ann.toFixed(1) + "%"}}
          tone="success"
        />
        <Stat
          label="超额 vs 等权持有"
          value={{META.excess.toFixed(1) + "%"}}
          tone="success"
        />
        <Stat
          label="最大回撤"
          value={{META.mdd.toFixed(1) + "%"}}
          tone="warning"
        />
      </Grid>

      <Grid columns={{4}} gap={{12}}>
        <Stat label="等权持有总收益" value={{META.bh.toFixed(1) + "%"}} />
        <Stat
          label="期末权益"
          value={{(META.end_equity / 10000).toFixed(1) + " 万"}}
        />
        <Stat label="持仓日占比" value={{META.hold_pct + "%"}} />
        <Stat
          label="买卖次数"
          value={{META.n_buys + " / " + META.n_sells}}
        />
      </Grid>

      <Callout tone="info">
        最大回撤发生在 {{META.mdd_date}}；日均持仓 {{META.avg_hold}}{" "}
        票。超额 = 策略总收益 − 三票等权买入持有总收益。
      </Callout>

      <Card>
        <CardHeader>组合净值（月末，万元）</CardHeader>
        <CardBody>
          <LineChart
            categories={{EQUITY_CATS}}
            series={{[
              {{ name: "策略组合", data: EQUITY_STRAT, tone: "success" }},
              {{ name: "等权买入持有", data: EQUITY_BH, tone: "neutral" }},
            ]}}
            height={{280}}
            beginAtZero
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            Y 轴：权益（万元）· X 轴：月末
          </Text>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>策略回撤路径（月末时点回撤 %）</CardHeader>
        <CardBody>
          <LineChart
            categories={{EQUITY_CATS}}
            series={{[{{ name: "回撤%", data: DD, tone: "danger" }}]}}
            height={{220}}
            beginAtZero
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            Y 轴：回撤（%）· 相对历史峰值
          </Text>
        </CardBody>
      </Card>

      <H2>分年收益与回撤</H2>
      <Grid columns={{2}} gap={{16}}>
        <Card>
          <CardHeader>年度收益率对比（%）</CardHeader>
          <CardBody>
            <BarChart
              categories={{YEAR_CATS}}
              series={{[
                {{ name: "组合策略", data: YEAR_STRAT, tone: "success" }},
                {{ name: "等权持有", data: YEAR_BH, tone: "neutral" }},
              ]}}
              height={{240}}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>年度超额（策略 − 持有，%）</CardHeader>
          <CardBody>
            <BarChart
              categories={{YEAR_CATS}}
              series={{[{{ name: "超额%", data: YEAR_EXCESS, tone: "info" }}]}}
              height={{240}}
            />
          </CardBody>
        </Card>
      </Grid>

      <Table
        headers={{[
          "年份",
          "组合策略%",
          "等权持有%",
          "超额%",
          "策略回撤%",
          "持有回撤%",
        ]}}
        rows={{YEAR_ROWS}}
        rowTone={{[...YEAR_TONES]}}
        columnAlign={{["left", "right", "right", "right", "right", "right"]}}
        stickyHeader
      />

      <H2>持仓状态</H2>
      <Grid columns={{2}} gap={{16}}>
        <Card>
          <CardHeader>日持仓票数分布（交易日）</CardHeader>
          <CardBody>
            <BarChart
              categories={{HOLD_DIST_CATS}}
              series={{[{{ name: "天数", data: HOLD_DIST_VALS, tone: "info" }}]}}
              height={{220}}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>分年买入次数</CardHeader>
          <CardBody>
            <BarChart
              categories={{BUY_YEAR_CATS}}
              series={{[{{ name: "买入", data: BUY_YEAR_VALS, tone: "warning" }}]}}
              height={{220}}
            />
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>月均持仓票数</CardHeader>
        <CardBody>
          <LineChart
            categories={{HOLD_CATS}}
            series={{[{{ name: "日均持仓数", data: HOLD_AVG, tone: "info" }}]}}
            height={{200}}
            beginAtZero
            yMax={{3}}
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            Y 轴：票数（0–3）· X 轴：月份
          </Text>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>各标的买入次数</CardHeader>
        <CardBody>
          <BarChart
            categories={{BUY_NAME_CATS}}
            series={{[{{ name: "买入次数", data: BUY_NAME_VALS, tone: "neutral" }}]}}
            height={{200}}
            horizontal
          />
        </CardBody>
      </Card>

      <Divider />
      <H2>最近进出（18 个有事件交易日）</H2>
      <Table
        headers={{["日期", "持仓数", "持仓", "买入", "卖出"]}}
        rows={{RECENT_ROWS}}
        columnAlign={{["left", "right", "left", "left", "left"]}}
        stickyHeader
        striped
      />
    </Stack>
  );
}}
"""

out = Path(r"C:\Users\EDY\.cursor\projects\d-Akquan-myquan\canvases\portfolio-s1-top3-ew.canvas.tsx")
out.write_text(tsx, encoding="utf-8")
print("wrote", out, "bytes", out.stat().st_size)
