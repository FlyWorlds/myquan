# 贡献说明

本仓库为私有的克拉曼特殊情况投资 Skill 交付仓库。提交应保持可复核、可复现，并遵守 `BUILD开发与生产规则V2.md` 所要求的开发产物和生产产物边界。

## 提交前要求

1. 在独立分支完成实现与文档修改，避免把无关变更混入同一提交。
2. 逻辑、接口、字段或版本有变化时，同步更新 `开发产物/SKILL.md`、`生产产物/SKILL.md` 和 `开发产物/references/api_guide.md`。
3. 运行：

   ```powershell
   python 开发产物\scripts\test.py
   python 开发产物\scripts\validate_build.py
   ```

4. 只有全市场正式扫描才能覆盖默认 `生产产物/数据库.parquet`；定向诊断必须写入独立输出路径。
5. Markdown 文件与提交信息使用 UTF-8 编码；提交信息应明确说明改动范围，例如“重写特殊情况投资 Skill 首页”或“修复 Panda 接口字段映射”。

## 禁止提交

- Panda Data 用户名、密码、令牌、`.env` 文件或系统环境变量导出。
- 本地运行日志、断点缓存、浏览器截图、临时扫描 Parquet 或 Python 缓存。
- 未经验证的第三方数据源、手工改写的生产 Parquet 和无法解析的 `result_json`。
- 买卖方向、具体仓位、收益承诺或将研究候选标记为交易信号的文案。

## 审查重点

- `run(input_data, config=None)` 与 `validate_input(input_data)` 的稳定性。
- 点时证据、失败封闭承保和生产主键没有被破坏。
- `research_digest` 与 `qualified_special_situation` 的消费边界仍然分离。
- 文档、测试、版本号和生产结果相互一致。
