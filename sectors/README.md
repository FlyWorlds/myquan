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

| 类型 | 来源 | 说明 |
|------|------|------|
| 行业 | 同花顺 `q.10jqka.com.cn/thshy` | 约 90 个行业板块，与 App「行业板块」一致 |
| 概念 | 同花顺 `q.10jqka.com.cn/gn` | 纯概念（剔除沪股通等通道类） |
| 成分股 | 同花顺板块详情页 | 与 App 下钻列表一致 |

**Mac / Windows 通用**：走同花顺官网接口 + akshare，不读本地通达信/同花顺安装目录；另一台电脑只要 `pip install akshare py_mini_racer` 和网络即可。

不可用时回退东财。

## 文件

| 文件 | 作用 |
|------|------|
| `index.py` | CLI 入口 |
| `ths.py` | 同花顺行业/概念/成分股 |
| `data.py` | 成分股回退（东财） |
| `rotation.py` | 指标、历史、快照 |
| `report.py` | 轮动 HTML |
| `snapshots/` | 按日快照 |
| `cache/` | 同花顺代码映射、涨停缓存 |

`tdx.py` 已停用（保留文件仅供参考，默认不再调用）。
