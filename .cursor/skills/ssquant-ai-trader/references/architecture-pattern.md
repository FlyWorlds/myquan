# AI 交易员技能架构模式

## 核心设计原则

### 1. 双模式执行 (Dual-Mode Execution)
根据用户描述的可自动化程度自动选择：
- **全自动**: 规则清晰 → 生成代码 → SIMNOW 自动执行
- **半自动**: 规则模糊 → AI 分析 → 用户确认 → 执行
- **混合**: 部分清晰 → 代码 + AI 判断点结合

判断信号：
- 全自动信号：明确指标、数值、仓位、时间规则
- 半自动信号：模糊形态、主观量价、趋势情绪判断

### 2. 生成器模式 (Generator Pattern)
交易员 Skill 不应是"一次性运行时"，而应生成**持久化、可复用的专属 Skill 文件**。

流程：用户描述 → 解析部署 → 调用 `skill_manage(action='create')` 生成独立 Skill → 用户下次可直接加载。

### 3. 环境检测优先 (Step 0)
任何交易相关 Skill 加载后，**必须先检查 SSQuant 环境**：
```python
python -c "import ssquant; print('SSQuant v' + ssquant.__version__)"
```
未安装 → 引导安装；版本过低 → 提示升级；CTP 不可用 → 警告但不阻断回测。

### 4. 风控自动叠加
无论用户是否提到，必须自动叠加：
- 单笔止损 (ATR×2 或用户指定)
- 日亏损 5% 熔断
- 连续亏损 3 笔暂停
- 保证金占用 > 70% 拒绝新开仓

### 5. SSQuant 深度集成
- 代码生成必须使用 **IndicatorCache v2** (`register_indicator` + `get_indicator`)
- 运行必须通过 `UnifiedStrategyRunner` 和 `RunMode.SIMNOW`
- 数据必须来自 SSQuant 的 `data_server` 或 `backtest_data.db`

## Skill 关系图

```
trader-generator (工厂入口)
    │ 作用：接收自然语言 → 解析 → 委托部署 → 生成持久化 Skill
    ↓
ai-trader (执行引擎)
    │ 作用：代码生成/SIMNOW 部署/Cron 监控/通知推送
    ↓
生成的专属 Skill (如 rb-ma-cross-trader)
    │ 作用：固化配置，下次直接加载恢复运行
    ↓
SSQuant 框架 (底层执行)
    └─ StrategyAPI / UnifiedRunner / CTP / IndicatorCache
```

## 常见陷阱

1. **错误判断模式**：用户描述模糊但强行全自动，导致行为不符合预期。宁可保守用半自动。
2. **忘记固化 Skill**：部署成功后必须调用 `skill_manage` 生成持久化文件，否则下次无法直接加载。
3. **环境变量未检查**：未检测 SSQuant 安装状态就直接生成代码，导致运行失败。
4. **Skill Name 冲突**：生成前检查是否已存在同名 Skill，询问用户覆盖或追加版本号。
