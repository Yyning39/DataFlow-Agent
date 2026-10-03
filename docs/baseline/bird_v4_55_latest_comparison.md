# v4 公开 BIRD Mini-Dev 回归对比

## 口径

- 数据：同一公开 `bird_mini_dev_eval_manifest_5perdb.json`，11 个数据库、55 题。
- 模型：`deepseek-v4-flash`；temperature=0；服务：`http://127.0.0.1:5670`。
- 旧基线：`bird_v4_55_eval.json`，单题超时 180 秒。
- 新回归：`bird_v4_55_latest_eval.json`，单题超时 60 秒；因此延迟和转换率只作参考，不能视为严格 A/B。

## 指标

| 指标 | 旧 v4 55 题 | 新 v4 55 题 | 变化 |
|---|---:|---:|---:|
| SQL 转换/执行率 | 87.27% | 76.36% | -10.91 pp |
| 严格结果正确率 | 34.55% | 36.36% | +1.82 pp |
| 结果形状匹配率 | 未记录 | 61.82% | 新增观测 |
| 超时率 | 0% | 1.82% | +1.82 pp |
| 平均总延迟 | 7.29s | 9.90s | +2.61s |
| P50 总延迟 | 6.34s | 6.68s | +0.34s |
| Schema fallback | 未拆分 | 0% | 新增口径 |
| 向量 Schema 检索为空率 | 未记录 | 100% | 新增观测 |
| provider usage 可用率 | 未记录 | 0% | 当前网关未返回 |

## 解读与限制

1. 结果正确率在同一公开样本上由 34.55% 升至 36.36%，但提升很小，不能宣称模型能力已显著提升。
2. 新回归使用更短的 60 秒预算，且 DeepSeek 流式服务存在生成波动；转换率下降不能单独归因于本轮代码，应使用相同超时和多次重复运行做最终 A/B。
3. Schema fallback=0% 表示最终本地 Schema 可用，不代表向量索引健康；检索为空率 100% 是独立的索引健康信号。
4. 结果形状匹配率揭示了 q159 一类问题：SQL 可执行且过滤条件正确，但投影列数超出问题意图。系统目前只告警、不擅自删列。
5. token 当前为输出字符估算，成本字段为 `null`；只有网关返回 usage 或显式价格配置后，才能给出可计费成本。

## 可复现命令

```powershell
.\.venv\Scripts\python.exe tools\dbgpt_bird_eval.py `
  --url http://127.0.0.1:5670 `
  --model deepseek-v4-flash `
  --variant v4 `
  --data-root D:\1ALL\DB-GPT\datasets\bird_mini_dev\data `
  --manifest docs\baseline\bird_mini_dev_eval_manifest_5perdb.json `
  --output docs\baseline\bird_v4_55_latest_eval.json `
  --checkpoint docs\baseline\bird_v4_55_latest_checkpoint.json `
  --reuse-registered --case-timeout 60 --skip-refresh
```
