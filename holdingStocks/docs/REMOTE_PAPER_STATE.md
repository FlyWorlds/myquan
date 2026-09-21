# Remote Paper Trading State（Phase R1）

> 研究/纸面账户架构。**不构成投资建议。**  
> R1 **未**切换生产 backend；当前 watch 仍写本地 `holdings.json`。

## 目标

多机（Windows / Mac）共享同一 paper trading **REMOTE SINGLE SOURCE OF TRUTH**，并强制 **SINGLE ACTIVE WRITER**，防止重复 BUY/SELL 与状态分叉。

## 阶段

| Phase | 内容 | 生产 |
|-------|------|------|
| **R1**（本阶段） | State inventory、`PaperStatePort`、schema、迁移 dry-run、lease/fencing 单测 | 仍 **local JSON** |
| R2 | Windows → remote dry-run / staging apply + 校验报告 | 未切 |
| R3 | Windows writer → Postgres；Mac UI read-only | 观察 |
| R4 | Writer lease failover 验证 | 可 Mac 接管 |
| R5 | local JSON 降为 export/backup | remote 为 truth |

## Backend 切换（环境变量）

```text
PAPER_STATE_BACKEND=local_json|memory|postgres
PAPER_DATABASE_URL=postgresql://...   # 仅 server；禁止写入 Nuxt client / 禁止 commit
```

工厂：`paper_state.port.create_paper_state_port()`。  
策略 / `index.py` **不得**直接 import `psycopg`。

## 路径

```text
REMOTE_READ_PATH  = Nuxt → holdingStocks API → PaperStatePort → Postgres
REMOTE_WRITE_PATH = Active Watch Writer → PaperStatePort.apply_trade_mutation (+ lease/fencing)
```

R1 生产仍：

```text
CURRENT = index.py ↔ holdings.json / trades.jsonl / trade_ledger.json
```

## Writer lease

- `LEASE_TTL` = **45s**（`DEFAULT_LEASE_TTL_SEC`）
- `HEARTBEAT_INTERVAL` = **15s**
- 每次 acquire：`writer_id` + `lease_token` + 单调 **`fencing_token`**
- 第二 writer → `ACTIVE_WRITER_EXISTS` / `LeaseConflictError`
- 过期后可 takeover；旧 writer mutation → `StaleWriterError`

## 网络断开

```text
DB unavailable => NEW PAPER MUTATION PAUSED
禁止 local fallback write（REMOTE_STATE_UNAVAILABLE）
```

## 迁移

```bash
cd holdingStocks
python migrate_local_paper_state_to_remote.py              # DRY_RUN
python migrate_local_paper_state_to_remote.py --backend memory
# R2+ only:
# python migrate_local_paper_state_to_remote.py --backend postgres --apply
```

Mac bootstrap：连 remote 读全量；本地旧 JSON 标记 `LOCAL_STATE_IGNORED`，**禁止自动 merge**。

## Schema

见 [`paper_state/schema/001_paper_state.sql`](paper_state/schema/001_paper_state.sql)。

## 测试

```bash
python -m unittest holdingStocks.test_paper_remote_state_r1 -v
# 或
cd holdingStocks && python test_paper_remote_state_r1.py -v
```

## Secrets

仅环境变量 / secret store。禁止 commit `.env`、明文密码、Nuxt bundle 直连 DB。
