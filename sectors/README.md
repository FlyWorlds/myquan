# 板块轮动

行业 / 概念 Tab；按涨幅、涨停数、资金排序；前 10 / 后 10 **近 5 日**热力表；点击板块高亮追踪并下钻个股。

## 用法

```bash
cd myquan/sectors

python index.py
python index.py --no-limitup          # 跳过涨停统计，更快
python index.py --days 5 --no-members --no-open
```

报告：`sectors_rotation.html`

## 数据口径

| 类型 | 历史列 | 今日列 |
|------|--------|--------|
| 行业 | 申万二级行业日涨跌 | 东财实时 |
| 概念 | 同花顺概念指数日涨跌 | 东财实时 |

## 文件

| 文件 | 作用 |
|------|------|
| `index.py` | CLI 入口 |
| `data.py` | 成分股拉取 |
| `rotation.py` | 指标、申万历史、日快照 |
| `report.py` | 轮动 HTML |
| `snapshots/` | 按日快照 |
| `cache/` | 涨停数缓存 |
