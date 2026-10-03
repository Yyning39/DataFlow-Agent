# DB-GPT v2 / v3 BIRD Mini-Dev 对比

## 评测范围

- 数据集：公开 BIRD Mini-Dev SQLite，22 题、11 个数据库
- v2 结果：`bird_v2_eval_schema_fallback.json`
- v3 结果：`bird_v3_direct_nonthinking_eval.json`
- v3 使用 DB-GPT `proxy/deepseek` 适配器、`deepseek-v4-flash` 非思考模式和字段语义注册表。

## 结果

| 指标 | v2 | v3 | 变化 |
|---|---:|---:|---:|
| SQL 转化率 | 18/22 = 81.8% | 19/22 = 86.4% | +4.6 个百分点 |
| 执行成功率 | 18/22 = 81.8% | 19/22 = 86.4% | +4.6 个百分点 |
| 结果正确率 | 5/22 = 22.7% | 7/22 = 31.8% | +9.1 个百分点 |
| 平均端到端耗时 | 44.74s | 6.93s | -84.5% |
| 平均模型生成耗时 | 44.47s | 7.07s | -84.1% |
| 平均 SQL 执行耗时 | 0.057s | 0.051s | 基本不变 |

v3 还记录了平均值提示准备耗时 `0.075s`、平均首 token `0.668s` 和平均每题 `0.53` 条枚举值告警。

## 结论与限制

v3 在本次公开集运行中同时提高了 SQL 覆盖率和结果正确率，并显著降低了响应时间；数据库执行不是瓶颈，主要收益来自非思考模式和原生 DeepSeek 适配器。

这不是严格的单变量实验：历史 v2 运行使用了不同的代理/模型配置，v3 同时启用了字段语义注册表。因此不能把全部提升归因于语义层。下一轮应固定 `deepseek-v4-flash` 非思考模式，仅切换语义注册表开关，形成严格 v2/v3 消融对比。

## 可复现文件

- v2：`docs/baseline/bird_v2_eval_schema_fallback.json`
- v3：`docs/baseline/bird_v3_direct_nonthinking_eval.json`
- v3 评测脚本：`tools/dbgpt_bird_eval.py`
