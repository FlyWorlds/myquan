# weChat 接入（OpenClaw）

盯盘预警通过 **OpenClaw 微信通道**主动推送，**不调用大模型**（不走 OpenAI / 百炼对话）。

> 说明：本机没有独立的 `openclawd` 可执行文件。日常说的「openclawd / 守护进程」对应 CLI 里的  
> `openclaw daemon …`（旧别名）或 `openclaw gateway …`（推荐）。二者管理的是同一套 Gateway 服务。

## 原理

```
holdingStocks watch 刷新
  → 识别「待买入 / 待卖出」等预警行
  → wechat_notify.py
  → openclaw message send --channel openclaw-weixin
  → 手机微信
```

`openclaw message send` 只发固定文案，不会触发 Agent / LLM。

## 前置条件

1. 已安装 OpenClaw（`which openclaw`），且微信插件已扫码登录。
2. Gateway 守护进程常驻运行（见下一节）。
3. 本机 `openclaw` 在 PATH 中；若用 nvm，盯盘终端需先加载 node 环境。

当前本机 CLI 路径示例：

```bash
which openclaw
# /Users/wangxiangyu/.nvm/versions/node/v24.13.0/bin/openclaw
```

## OpenClaw Daemon / Gateway 接入

首次把 Gateway 装成系统服务（macOS launchd）：

```bash
# 推荐：gateway 子命令
openclaw gateway install
openclaw gateway start
openclaw gateway status

# 等价旧别名（daemon = gateway 服务管理）
openclaw daemon install
openclaw daemon start
openclaw daemon status
```

日常启停：

```bash
openclaw gateway start
openclaw gateway stop
openclaw gateway restart
openclaw gateway status

# 旧别名同样可用
openclaw daemon start
openclaw daemon stop
openclaw daemon restart
openclaw daemon status
```

前台临时跑（调试，不装服务时）：

```bash
openclaw gateway run
# Ctrl+C 结束
```

健康检查：

```bash
openclaw health
openclaw gateway health
openclaw gateway probe
openclaw doctor
openclaw status
openclaw status --all
```

看日志：

```bash
openclaw logs
openclaw logs --follow
openclaw channels logs
```

卸载服务（一般不需要）：

```bash
openclaw gateway stop
openclaw gateway uninstall
# 或
openclaw daemon uninstall
```

### 微信通道登录

```bash
# 通道状态：应看到 openclaw-weixin … running
openclaw channels status
openclaw channels list

# 重新扫码登录微信插件
openclaw channels login --channel openclaw-weixin
# 可选：更详细日志
openclaw channels login --channel openclaw-weixin --verbose

# 登录后重启 Gateway，再确认状态
openclaw gateway restart
openclaw channels status
```

## 配置

文件：`holdingStocks/wechat_notify.json`（本地私有，已 gitignore）。

首次使用：

```bash
cp holdingStocks/wechat_notify.json.example holdingStocks/wechat_notify.json
# 再编辑 account / target
```

| 字段 | 说明 |
|------|------|
| `enabled` | 是否启用自动推送 |
| `channel` | 固定 `openclaw-weixin` |
| `account` | 微信 bot 账号 id（见本地配置，勿提交） |
| `target` | 接收方 openid，形如 `…@im.wechat`（勿提交） |
| `cooldown_sec` | 同一标的同一信号冷却秒数（默认 1800） |
| `openclaw_bin` | CLI 路径，默认 `openclaw`；nvm 环境可写成绝对路径 |
| `timeout_sec` | 发送超时 |

运行时防抖状态写在 `wechat_alert_state.json`（已 gitignore）。

## 盯盘侧用法

在 `holdingStocks` 目录：

```bash
# 发一条测试预警（立刻到微信）
python index.py wechat-test

# 长驻盯盘：默认开启微信推送
python index.py watch --no-open

# 仅盯盘、不推微信
python index.py watch --no-wechat --no-open
```

## 何时推送

满足任一即可推送（并做冷却防抖）：

- 持仓状态为 **待买入** / **待卖出**
- 预警文案含：已触买、将买入、已触止损、将止损

同一 `代码|状态|预警|因子触发` 在 `cooldown_sec` 内只推一次；信号消失后状态会清理，再次进入预警带会重新推。

## 常用命令速查

### Gateway / Daemon

| 目的 | 命令 |
|------|------|
| 安装守护服务 | `openclaw gateway install` |
| 启动 | `openclaw gateway start` |
| 停止 | `openclaw gateway stop` |
| 重启 | `openclaw gateway restart` |
| 状态 | `openclaw gateway status` |
| 前台调试 | `openclaw gateway run` |
| 健康探测 | `openclaw health` / `openclaw gateway probe` |
| 一键体检 | `openclaw doctor` |
| 通道总览 | `openclaw status` |
| 跟日志 | `openclaw logs --follow` |
| 旧别名 | 把上面的 `gateway` 换成 `daemon` 即可 |

### 微信通道

| 目的 | 命令 |
|------|------|
| 通道状态 | `openclaw channels status` |
| 通道列表 | `openclaw channels list` |
| 扫码登录 | `openclaw channels login --channel openclaw-weixin` |
| 通道日志 | `openclaw channels logs` |

### 发消息（不走大模型）

```bash
openclaw message send \
  --channel openclaw-weixin \
  --account YOUR_IM_BOT_ACCOUNT_ID \
  --target "YOUR_OPENID@im.wechat" \
  --message "手工测试"
```

也可用短选项：

```bash
openclaw message send \
  --channel openclaw-weixin \
  --account YOUR_IM_BOT_ACCOUNT_ID \
  -t "YOUR_OPENID@im.wechat" \
  -m "手工测试"
```

`account` / `target` 以本地 `wechat_notify.json` 为准（可从 `wechat_notify.json.example` 复制）。

### 盯盘推送

| 目的 | 命令 |
|------|------|
| 微信自检 | `python index.py wechat-test` |
| 盯盘+推送 | `python index.py watch --no-open` |
| 盯盘不推送 | `python index.py watch --no-wechat --no-open` |

## 推荐开机自检流程

```bash
# 1) Gateway 是否在跑
openclaw gateway status

# 2) 微信通道是否 online
openclaw channels status

# 3) 发一条测试
cd /Users/wangxiangyu/Documents/akquan回测/myquan/holdingStocks
python index.py wechat-test

# 4) 开盯盘
python index.py watch --no-open
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `找不到 openclaw` / 没有 `openclawd` | 用 `openclaw`；守护进程用 `openclaw gateway …` 或 `openclaw daemon …`。确认 nvm/node 已加载，或把 `openclaw_bin` 改成绝对路径 |
| Gateway not reachable | `openclaw gateway restart`；仍失败则 `openclaw doctor` |
| 推送失败 / 收不到 | 重新扫码：`openclaw channels login --channel openclaw-weixin`，再 `gateway restart` |
| `feishu duplicate plugin` 警告 | 飞书插件装了两份，与微信推送无关，可忽略 |
| 不想用 LLM 但仍被扣费 | 只要用 `message send` / 本模块，不会走对话模型；不要在微信里跟机器人闲聊 |
| 服务装了但开机没起来 | `openclaw gateway status` 看 launchd 状态，再 `start` / `install` |

## 相关文件

| 文件 | 职责 |
|------|------|
| `wechat_notify.py` | 发送、格式化、防抖 |
| `wechat_notify.json` | 推送配置 |
| `index.py` | `watch` 刷新后调用；`wechat-test` 子命令 |
| `~/.openclaw/` | OpenClaw 本地状态与插件配置（系统目录，不在本仓库） |
