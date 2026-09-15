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
| `tdx.py` | 通达信行业/概念/成分股 + pytdx |
| `tdx_rotation.py` | 通达信概念轮动 payload |
| `concept_leaders.py` | 概念波段龙头统计 |
| `leader_score.py` | 因子16 概念龙头评分（编排层，真源 `strategy/factor16_leader_score.py`） |
| `api.py` | Web API 数据层 |
| `snapshots/` | 按日快照 |
| `cache/` | 同花顺代码映射、涨停缓存 |

**Web 行情（盯盘 `/sectors`）**：

1. **结构**：通达信概念名单 + 成分（`sectors/cache` 的 `tdxzs.cfg` / `block_gn`；本机通达信安装目录可同步进 cache）
2. **今日列实时**：后台线程约 5s 拉一次现价 → 写入 `snapshot.sectors.conceptToday` → WS 推前端重排最左「今日」列  
   - pytdx 通 → 直拉通达信概念指数  
   - pytdx 挂 → **东财现价对齐通达信名单**（冷却 10 分钟内不再扫服务器，避免卡死）
3. **历史列**：通达信日线排行缓存（磁盘 `tdx_rotation_api.json`，约 1h；点「重载历史」强制刷新）
4. **概念 K 线/波段**：磁盘缓存 + stale-while-revalidate（研究用，不是盘中 tick）

Mac/Win 名单不一致时优先复用未过期太久的通达信轮动磁盘缓存（≤2 天）。行情彻底失败才整表回退东财。

`holdingStocks` watch 服务提供 API，Nuxt 前端 `/sectors` 热力表 + 概念 K 线龙头图。

| 接口 | 说明 |
|------|------|
| `GET /api/sectors/members?name=` | 板块成分股（通达信索引优先，名称对不上则东财） |
| `GET /api/sectors/concept/{名称}?months=6&lite=1` | **lite**：仅 K 线+成分预览（秒开）；不带 `lite` 再补波段龙头 |
| `GET /api/sectors/concept/{名称}?months=6` | 完整：K 线 + 近半年波段龙头（通达信失败则东财；磁盘缓存 + stale-while-revalidate） |
| `GET /api/sectors/concept/{名称}/leaders?start=2025-01-01&top_n=5` | **因子16** 概念龙头 Top5（2025至今；前端在 K 线之后再拉） |
| `GET /api/sectors/focus?concept=名称` | 订阅概念成分/龙头实时报价（随 WS 5s 推送） |
| `GET /api/sectors/status` | 通达信链路可用性（概念表就绪优先于行情连通） |

启动：`cd holdingStocks && python start_watch.py` → 浏览器打开 `http://127.0.0.1:3000/sectors`。点击热力表格子加载成分股。

| 指标 | 来源 | 说明 |
|------|------|------|
| 涨幅 | 通达信概念指数 | pytdx 实时/历史 |
| 成交额 | 通达信概念指数 | 指数 amount 字段 |
| 涨停数 | **可算** | 成分股现价聚合（新浪，~30s 刷新） |
| 涨跌比 | **可算** | 成分上涨家数 ÷ 下跌家数 |
| 主力净额 | **东财补充** | 概念名称近似匹配，非通达信直连 |
| 强度 | **可算** | 合成：涨幅 × (1+涨跌比/5) + 涨停数×0.35 |

Web 筛选框支持以上 6 项；历史列仅涨幅/成交额来自通达信，其余以「今日」列实时为准。

`tdx.py` 为通达信真源；`rotation.py` 默认同花顺；`tdx_rotation.py` + `api.py` + `live.py` 供 Web 通达信概念轮动。
