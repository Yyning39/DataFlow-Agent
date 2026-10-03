# DB-GPT 改进版运行与验收指南

## 启动

在项目根目录的 PowerShell 中设置 DeepSeek key 后执行：

```powershell
$env:DEEPSEEK_API_KEY = "<your-key>"
.\tools\start_dbgpt_deepseek.ps1 -Model deepseek-v4-flash
```

启动脚本会加载最终版本对比文件 `docs/baseline/bird_v2_v3_v4_final_comparison.json`。

## 版本开关

- v2：`DBGPT_DISABLE_FIELD_SEMANTICS=true`、`DBGPT_SQL_GUARD_ENHANCED=false`
- v3：删除 `DBGPT_DISABLE_FIELD_SEMANTICS`，设置 `DBGPT_SQL_GUARD_ENHANCED=false`
- v4：删除上述两个环境变量

切换环境变量后必须重启服务。

## 评测

22 题严格对比结果位于 `bird_v2_final_eval.json`、`bird_v3_final_eval.json`、`bird_v4_final_eval.json`；55 题扩展基线位于 `bird_v4_55_eval.json`。评测支持 `--checkpoint` 和 `--resume`，单题超时不会丢失已完成结果。

评测结果还包含 `result_shape_match_rate`、`schema_retrieval_empty_rate`、模型生成分项耗时和估算输出 token。若供应商没有返回 usage，可在评测进程中显式提供价格参数后计算成本：

可用 `--db-id financial` 只回归某个数据库，仍使用同一公开 manifest；完整批次不使用该参数。

```powershell
$env:DBGPT_INPUT_PRICE_PER_MILLION = "<provider input price>"
$env:DBGPT_OUTPUT_PRICE_PER_MILLION = "<provider output price>"
```

价格不写入代码；未提供 usage 或价格时成本字段保持 `null`。

## 当前限制

- 当前公开基线是 BIRD Mini-Dev 的 55 题分层样本，不等同于完整 BIRD 全量评测。
- API 响应未提供 token usage，因此成本只能在供应商账单或 usage 接口可用后精确统计。
- Windows 下 Next.js 生产构建可能因大型依赖图触发 EMFILE；定向 TypeScript/ESLint 和后端测试已通过。
