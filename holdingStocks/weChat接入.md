# 微信接入（OpenClaw · 仅消息推送）

盯盘预警 / 策略触发通过 **OpenClaw 微信通道**主动推送到手机，**不调用大模型**（不走 OpenAI 对话）。

> 不要在微信里跟机器人闲聊：闲聊会触发 Agent → 模型鉴权（常见 401）。  
> 本方案只做 **机器人 → 你** 的出站推送。

---

## 原理

```
holdingStocks watch 刷新
  → 识别「待买入 / 待卖出」预警 或 「止损成交」等策略触发
  → wechat_notify.py
  → openclaw message send --channel openclaw-weixin
  → 手机微信（机器人会话）
```

`openclaw message send` 只发固定文案，**不会**触发 Agent / LLM。

---

## Windows 本机环境（当前）

| 项 | 值 |
|----|-----|
| Node | nvm `v24.15.0`（`C:\Users\EDY\AppData\Roaming\nvm\v24.15.0`） |
| OpenClaw | `2026.7.1-2` |
| 微信插件 | `@tencent-weixin/openclaw-weixin`（渠道 id: `openclaw-weixin`） |
| Gateway | 计划任务 `OpenClaw Gateway`，端口 `18789` |
| 入站策略 | `dmPolicy=allowlist` + 空 `allowFrom`（丢弃私信，避免 401） |

加载 Node（新开终端若 `openclaw` 找不到时）：

```powershell
. $HOME\.openclaw\use-node24.ps1
# 或
$env:PATH = "$env:APPDATA\nvm\v24.15.0;$env:PATH"
```

---

## 一次性安装

### 1. OpenClaw + 微信插件

```powershell
# Node ≥ 24.15（或官方要求的版本区间）
nvm install 24.15.0 64
# 管理员终端：
nvm use 24.15.0

npm install -g openclaw@latest
npx -y @tencent-weixin/openclaw-weixin-cli@latest install
```

### 2. 扫码登录

```powershell
openclaw channels login --channel openclaw-weixin
# 手机微信扫码确认后：
openclaw gateway restart
openclaw channels status --probe
# 期望：openclaw-weixin … enabled, configured, running
```

### 3. 仅推送、不接大模型

```powershell
openclaw config set channels.openclaw-weixin.dmPolicy allowlist
openclaw config set channels.openclaw-weixin.allowFrom "[]"
openclaw gateway restart
```

空 `allowFrom` 会告警「所有 DM 将被丢弃」——这是预期行为。

### 4. Gateway 服务

```powershell
openclaw gateway install
openclaw gateway start
openclaw gateway status
```

---

## 盯盘侧配置

文件：`holdingStocks/wechat_notify.json`（**已 gitignore**，勿提交）。

```powershell
cd D:\Akquan\myquan\holdingStocks
copy wechat_notify.json.example wechat_notify.json
# 编辑 account / target / openclaw_bin / node_bin_dir
```

| 字段 | 说明 |
|------|------|
| `enabled` | 是否启用自动推送 |
| `channel` | 固定 `openclaw-weixin` |
| `account` | 微信 bot 账号 id（如 `xxxx-im-bot`） |
| `target` | 接收方，形如 `…@im.wechat`（扫码登录账号的 userId） |
| `cooldown_sec` | 同一标的同一信号冷却秒数（默认 1800） |
| `openclaw_bin` | CLI 路径；Windows 建议写 `…\nvm\v24.15.0\openclaw.cmd` |
| `node_bin_dir` | Node 目录，发送前拼进 PATH |
| `timeout_sec` | 发送超时 |

查本机 id（勿把 token 贴出）：

```powershell
# account：~/.openclaw/openclaw-weixin/accounts/ 下文件名（无 .json）
# target：对应账户 json 里的 userId 字段
```

运行时防抖状态：`wechat_alert_state.json`（已 gitignore）。

---

## 何时推送（已做）

| 类型 | 条件 | 文案标题 |
|------|------|----------|
| **启动完成** | `watch` 绑定端口成功后 | 【盯盘启动完成】 |
| **触发预警** | 因子触发=`已触发`（含日期）；或已触买/已触止损=是 | 【触发预警】 |
| **接近预警** | 因子触发=`接近`；或将买入/将止损；或近买点/近止损 | 【接近预警】 |
| **盯盘预警** | 持仓状态「待买入/待卖出」等 | 【盯盘预警】 |
| **策略触发** | 自动结算（止损成交等，`已实现`） | 【策略触发】 |

判定与页面卡片预警一致。同一信号键在 `cooldown_sec` 内只推一次（默认 1800s）；`接近→已触发` 会换键再推；信号消失后状态清理，再次进入预警带会重新推。

`watch` 每次刷新行情后都会扫描；默认开启，可用 `--no-wechat` 关闭。

---

## 盯盘用法

```powershell
cd D:\Akquan\myquan\holdingStocks

# 微信自检
python index.py wechat-test

# 长驻盯盘（默认开微信推送）
python index.py watch --interval 5 --port 8765 --no-open
# 页面：http://127.0.0.1:8765/holdings_report.html

# 仅盯盘、不推微信
python index.py watch --no-wechat --no-open
```

手工推送：

```powershell
openclaw message send `
  --channel openclaw-weixin `
  --account YOUR_IM_BOT_ACCOUNT_ID `
  --target "YOUR_OPENID@im.wechat" `
  --message "手工测试"
```

或：

```powershell
. $HOME\.openclaw\weixin-notify.ps1 -Message "手工测试"
```

---

## 推荐开机自检

```powershell
. $HOME\.openclaw\use-node24.ps1
openclaw gateway status
openclaw channels status --probe
cd D:\Akquan\myquan\holdingStocks
python index.py wechat-test
python index.py watch --interval 5 --port 8765 --no-open
```

启动成功后手机会收到 **【盯盘启动完成】**。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `找不到 openclaw` | 加载 Node24 PATH，或在 `wechat_notify.json` 写绝对 `openclaw_bin` + `node_bin_dir` |
| Gateway not reachable | `openclaw gateway restart`；仍失败 `openclaw doctor` |
| 推送失败 / 收不到 | 重新扫码登录后 `gateway restart`；检查 `account`/`target` |
| 微信里回机器人出现 401 | 入站已关；勿闲聊。若仍触发，确认 `dmPolicy=allowlist` 且 `allowFrom=[]` |
| `nvm use` 拒绝访问 | 管理员终端执行 `nvm use 24.15.0`，保证 `C:\Program Files\nodejs` 指向 v24 |
| 端口被占用 | 停掉旧 watch 或换 `--port` |

---

## 相关文件

| 路径 | 职责 |
|------|------|
| `wechat_notify.py` | 发送、格式化、防抖、启动完成 |
| `wechat_notify.json` | 本地推送配置（私有） |
| `wechat_notify.json.example` | 配置模板 |
| `index.py` | `watch` 刷新后调用；`wechat-test`；启动完成推送 |
| `~/.openclaw/` | OpenClaw 状态与微信凭证（系统目录） |
| `~/.openclaw/use-node24.ps1` | Windows Node24 环境脚本 |
| `~/.openclaw/weixin-notify.ps1` | 快捷手工推送 |
