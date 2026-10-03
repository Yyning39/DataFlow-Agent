# DB-GPT 1–5 步改进总计划

这五步是一个连续项目目标，不是五个互相独立、完成一步就结束的任务。

| 步骤 | 目标 | 当前状态 | 可展示成果 |
| --- | --- | --- | --- |
| 1 | 用同一模型、数据集、服务参数完成 v2/v3/v4 对比 | 进行中 | BIRD Mini-Dev 22 题，SQL 转化率、执行成功率、结果正确率、P50/P95 |
| 2 | 降低模型延迟并避免单题长尾阻塞 | 已实现，待在线复测 | 非思考模型、首 token/生成耗时、单题硬超时、checkpoint 续跑 |
| 3 | SQL 安全、结构和结果质量校验 | 已实现，待在线复测 | 只读边界、表校验、结构检查、有限纠错、结果异常告警 |
| 4 | 通用语义建模与歧义澄清 | 已实现组件，待交互验证 | 字段定义、别名、value mapping、来源/置信度、resolved/clarification_required |
| 5 | 前端可视化和可解释报告 | 已有基础能力，待联调 | SQL、语义依据、校验告警、analysis_report、版本对比面板 |

## 版本定义

- **v2**：Schema 兜底、SQL Guard、值提示等工程基础能力；关闭字段语义注册表用于严格消融。
- **v3**：v2 + 配置化字段语义和 value mapping，解决不同数据库对状态值编码的歧义。
- **v4**：v3 + 结构级 SQL 校验、结果级质量告警、澄清状态和可恢复评测能力。

## 严格评测约束

三版必须固定：同一 DeepSeek 非思考模型、同一 API 服务、同一 BIRD Mini-Dev manifest、同一数据库文件、同一超时和结果判断规则。历史 v2/v3 文件存在模型代理差异，只能作为工程参考，不能冒充严格 A/B。

## 可复现实验命令

在当前 PowerShell 中先设置真实 `DEEPSEEK_API_KEY`，再用项目脚本加载直连 DeepSeek 的配置。不要让主服务把模型地址指向 5699 桥接端口：

```powershell
.\tools\start_dbgpt_deepseek.ps1
```

```powershell
$env:PYTHONPATH = "packages/dbgpt-core/src;packages/dbgpt-app/src"
\.venv\Scripts\python.exe tools\dbgpt_bird_eval.py `
  --url http://127.0.0.1:5670 `
  --model deepseek-v4-flash `
  --data-root D:\1ALL\DB-GPT\datasets\bird_mini_dev\data `
  --manifest docs\baseline\bird_mini_dev_eval_manifest.json `
  --reuse-registered `
  --variant v4 `
  --case-timeout 180 `
  --checkpoint docs\baseline\bird_v4_checkpoint.json `
  --output docs\baseline\bird_v4_eval.json
```

分别切换 `--variant v2`、`v3`、`v4` 生成三份结果；v2 评测前设置
`$env:DBGPT_DISABLE_FIELD_SEMANTICS = "true"` 并重启服务，v3/v4 清除该变量并重启。
三份运行必须使用同一模型、API 地址、manifest SHA-256、超时设置和数据库注册。

中断后追加 `--resume` 即可从 checkpoint 跳过已完成题。每次切换 v2/v3/v4 的语义开关或校验版本，都应使用新的 `--run-id` 和输出文件。

生成对比 JSON 后，可在服务启动前设置 `DBGPT_VERSION_COMPARISON_FILE`，聊天结果会自动显示 `Version Comparison` 面板：

```powershell
$env:DBGPT_VERSION_COMPARISON_FILE = "D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v2_v3_v4_comparison.json"
```
