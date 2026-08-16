# PandaAI 代码沙箱安全限制 (Sandbox Restrictions)

**来源：** PandaAI 官网导入回测时对 `CodeControl` 节点代码做静态安全校验，命中黑名单直接拒绝执行（不进入回测，属于 fail-fast 校验，不是运行时报错）。以下清单为平台报错弹窗的**原文照抄**（实测确认，2026-07-08）。

写任何要注入 `CodeControl` 节点的策略/因子代码前，先对照本清单。

## 禁止 import 的模块（完整列表）

```
__import__, asyncio, compile, dbm, dir, email, eval, exec, ftplib,
globals, http, imaplib, importlib, input, locals, mimetypes,
multiprocessing, mysql, os, pickle, poplib, pymongo, raw_input,
redis, reload, requests, shelve, smtplib, socket, sqlite3, ssl,
subprocess, sys, telnetlib, threading, urllib, vars, webbrowser
```

## 禁止的危险调用（完整列表）

```
__import__, compile, dir, eval, exec, file, globals, input,
locals, open, raw_input, reload, vars
```

## 对写策略代码的实际影响

- **禁止 `dir()` 做反射/自省。** 平台提示原文："禁止使用 dir() 做反射；获取插件元数据时请依赖声明式 API"——即不要用 `dir(panda_data)` 探测方法是否存在。改用 `hasattr(obj, "method_name")` 逐个探测候选方法名（`hasattr`/`getattr` 不在黑名单中）。
- **禁止 `os`/`sys`/`subprocess`/`pickle`/`sqlite3`/`socket` 等系统与网络模块。** 策略代码只能做纯计算和调用平台注入的 API（`panda_data.*`、`order_shares` 等），不能做文件系统、网络、进程操作。
- **禁止 `open()`。** 不能在策略代码里读写本地文件；需要的数据一律通过 `panda_data` 接口获取。
- **禁止 `eval`/`exec`/`compile`/`__import__`。** 不能动态执行代码或动态导入。
- **已验证安全、可正常使用**：`pandas`、`numpy`、`datetime`、`re`、`json`、`math`、`bisect`——四个内置模板（`simple_backtest`、`complex_stock_selection`、`multi_factor_analysis`、`multi_agent_trading`）的内嵌代码均使用这些模块且通过了平台校验。

## 已知未覆盖的问题

这份清单是从一次报错弹窗中完整抄录的，尚未逐条在平台上单独验证每一项（例如 `pickle`、`redis` 等模块在真实场景中较少触发，是否报错未单独复测）。如果未来某次生成代码遇到清单外的模块被拒绝，请更新本文件并注明日期。
