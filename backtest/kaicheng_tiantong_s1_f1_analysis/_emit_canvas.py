"""从 _canvas_payload.json 生成 Cursor Canvas 侧边栏报告。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANVAS = Path(
    "/Users/wangxiangyu/.cursor/projects/Users-wangxiangyu-Documents-akquan-myquan/canvases/kaicheng-tiantong-s1-f1.canvas.tsx"
)


def lit(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def main() -> None:
    data = json.loads((ROOT / "_canvas_payload.json").read_text(encoding="utf-8"))
    meta = data["meta"]

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
const P = META["组合"];
const KC = META["凯盛科技"];
const TT = META["天通股份"];

const EQUITY_CATS = {lit(data["equity_cats"])};
const EQUITY_PORT = {lit(data["equity_port"])};
const EQUITY_BH = {lit(data["equity_bh"])};
const EQUITY_KC = {lit(data["equity_kc"])};
const EQUITY_TT = {lit(data["equity_tt"])};

const MONTH_CATS = {lit(data["month_cats"])};
const MONTH_EXCESS = {lit(data["month_excess"])};

const YEAR_CATS = {lit(data["year_cats"])};
const YEAR_EX_PORT = {lit(data["year_ex_port"])};
const YEAR_EX_KC = {lit(data["year_ex_kc"])};
const YEAR_EX_TT = {lit(data["year_ex_tt"])};
const YEAR_TR_KC = {lit(data["year_trades_kc"])};
const YEAR_TR_TT = {lit(data["year_trades_tt"])};
const YEAR_ROWS = {lit(data["year_rows"])};
const YEAR_TONES = {lit(data["year_tones"])} as const;

const ROLL_CATS = {lit(data["roll_cats"])};
const ROLL_PORT = {lit(data["roll_port"])};
const ROLL_KC = {lit(data["roll_kc"])};
const ROLL_TT = {lit(data["roll_tt"])};

const RECENT_ROWS = {lit(data["recent_rows"])};

export default function KaichengTiantongS1F1() {{
  const theme = useHostTheme();
  const caption = {{
    fontSize: 12,
    color: theme.textSecondary,
  }} as const;

  return (
    <Stack gap={{20}} style={{{{ padding: 20, maxWidth: 1100 }}}}>
      <Stack gap={{6}}>
        <H1>凯盛 + 天通 · 策略一 · 因子1</H1>
        <Row gap={{8}} style={{{{ flexWrap: "wrap" }}}}>
          <Pill tone="info">独立半仓等权</Pill>
          <Pill>凯盛 2.5% / 天通 3%</Pill>
          <Pill tone="neutral">{{META["区间"]}}</Pill>
        </Row>
        <Text style={{caption}}>
          数据源：backtest/kaicheng_tiantong_s1_f1_analysis · 仅因子1 · 平权=两票收盘价等权持有
        </Text>
      </Stack>

      <Grid columns={{4}} gap={{12}}>
        <Stat
          label="组合累计策略"
          value={{"+" + P["累计策略%"].toFixed(0) + "%"}}
          tone="success"
        />
        <Stat
          label="组合累计超额"
          value={{"+" + P["累计超额%"].toFixed(0) + " pct"}}
          tone="success"
        />
        <Stat
          label="超额月胜率"
          value={{P["超额月胜率%"] + "%"}}
        />
        <Stat
          label="滚动12M超额"
          value={{"+" + P["滚动12M最新超额%"].toFixed(1) + "%"}}
          tone="info"
        />
      </Grid>

      <Grid columns={{4}} gap={{12}}>
        <Stat
          label="凯盛累计超额"
          value={{"+" + KC["累计超额%"].toFixed(0) + " pct"}}
          tone="success"
        />
        <Stat
          label="天通累计超额"
          value={{"+" + TT["累计超额%"].toFixed(0) + " pct"}}
          tone="success"
        />
        <Stat
          label="2025 组合超额"
          value={{((P["2025超额%"] >= 0 ? "+" : "") + P["2025超额%"].toFixed(1) + "%")}}
          tone={{P["2025超额%"] >= 0 ? "success" : "danger"}}
        />
        <Stat
          label="2026 YTD 超额"
          value={{"+" + P["2026YTD超额%"].toFixed(1) + "%"}}
          tone="success"
        />
      </Grid>

      <Callout tone="info">
        因子1 未见单调衰减：2020–2022 累计超额 +40.8 pct，2023–2026 累计 +141.0 pct。
        2025 末滚动12M 超额探底（约 +9%），2026 回升至 +53%。2021 单边牛市与 2025 低波动年为主要跑输阶段。
      </Callout>

      <Card>
        <CardHeader>组合净值（月末，万元）</CardHeader>
        <CardBody>
          <LineChart
            categories={{EQUITY_CATS}}
            series={{[
              {{ name: "组合策略", data: EQUITY_PORT, tone: "info" }},
              {{ name: "组合平权", data: EQUITY_BH, tone: "neutral" }},
              {{ name: "凯盛策略", data: EQUITY_KC, tone: "warning" }},
              {{ name: "天通策略", data: EQUITY_TT, tone: "success" }},
            ]}}
            height={{280}}
            beginAtZero
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            Y 轴：权益（万元，各票独立 10 万）· X 轴：月末 · 名义本金 10 万
          </Text>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>分月超额（组合 vs 平权持有，%）</CardHeader>
        <CardBody>
          <BarChart
            categories={{MONTH_CATS}}
            series={{[{{ name: "超额%", data: MONTH_EXCESS, tone: "info" }}]}}
            height={{220}}
            referenceLines={{[{{ value: 0, label: "0", tone: "neutral" }}]}}
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            Y 轴：月超额（%）· 正值=跑赢平权持有 · 共 {{MONTH_CATS.length}} 个月
          </Text>
        </CardBody>
      </Card>

      <H2>分年超额与交易频率</H2>
      <Grid columns={{2}} gap={{16}}>
        <Card>
          <CardHeader>年度超额对比（%）</CardHeader>
          <CardBody>
            <BarChart
              categories={{YEAR_CATS}}
              series={{[
                {{ name: "组合", data: YEAR_EX_PORT, tone: "info" }},
                {{ name: "凯盛", data: YEAR_EX_KC, tone: "warning" }},
                {{ name: "天通", data: YEAR_EX_TT, tone: "success" }},
              ]}}
              height={{240}}
              referenceLines={{[{{ value: 0, label: "0", tone: "neutral" }}]}}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>因子1 闭环笔数</CardHeader>
          <CardBody>
            <BarChart
              categories={{YEAR_CATS}}
              series={{[
                {{ name: "凯盛", data: YEAR_TR_KC, tone: "warning" }},
                {{ name: "天通", data: YEAR_TR_TT, tone: "success" }},
              ]}}
              height={{240}}
            />
            <Text style={{{{ ...caption, marginTop: 8 }}}}>
              Y 轴：闭环交易笔数 · 2025 笔数下降但 2026 回升
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>滚动 12 个月累计超额（% · 月末）</CardHeader>
        <CardBody>
          <LineChart
            categories={{ROLL_CATS}}
            series={{[
              {{ name: "组合", data: ROLL_PORT, tone: "info" }},
              {{ name: "凯盛", data: ROLL_KC, tone: "warning" }},
              {{ name: "天通", data: ROLL_TT, tone: "success" }},
            ]}}
            height={{240}}
            referenceLines={{[{{ value: 0, label: "0", tone: "neutral" }}]}}
          />
          <Text style={{{{ ...caption, marginTop: 8 }}}}>
            252 交易日滚动窗口 · 2021 末约 -49% · 2024 末峰值约 +82%
          </Text>
        </CardBody>
      </Card>

      <Table
        headers={{["年份", "组合策略%", "平权持有%", "超额%", "年内回撤%"]}}
        rows={{YEAR_ROWS}}
        rowTone={{[...YEAR_TONES]}}
        columnAlign={{["left", "right", "right", "right", "right"]}}
        stickyHeader
      />

      <Divider />
      <H2>2024 以来分月（组合）</H2>
      <Table
        headers={{["月份", "策略%", "平权%", "超额%"]}}
        rows={{RECENT_ROWS}}
        columnAlign={{["left", "right", "right", "right"]}}
        stickyHeader
        striped
      />
    </Stack>
  );
}}
"""
    CANVAS.write_text(tsx, encoding="utf-8")
    print(f"Wrote {CANVAS} ({CANVAS.stat().st_size} bytes)")


if __name__ == "__main__":
    payload_script = ROOT / "build_viz.py"
    if not (ROOT / "_canvas_payload.json").exists():
        subprocess.run([sys.executable, str(payload_script)], check=True)
    main()
