# v9 最终验收记录

## 线上环境

- 服务端口：`127.0.0.1:5670`
- 模型：`deepseek-v4-flash`
- v9：`schema_index_version=v9`、`schema_local_hybrid_used=1`、`schema_retrieval_source=local_hybrid`
- 进程已在 2026-08-27 14:01:35 重启并加载本轮代码。

## 验收项

| 验收项 | 结果 | 证据 |
|---|---|---|
| 首次索引/索引刷新 | 通过 | D 盘 `schema_index/v9` 与 `schema_documents/v9` 已生成；schema hash 变化时自动重建 |
| 缓存命中 | 通过 | Financial 同一问题两轮均 `schema_local_hybrid_cache_hit=1`；第二轮本地检索 0.003s |
| 失败回退 | 通过 | v8 控制组关闭混合召回后 `schema_local_hybrid_used=0`、`schema_local_selection_used=1`，原路径仍可用 |
| SQL 与结果 | 通过 | Financial 分组问题两轮均返回正确 GROUP BY SQL 与 F/M 结果 |
| 前端诊断契约 | 通过 | 线上 payload 含 `timings`、`semantic_intent`、`result_row_count`、`result_column_count`、`analysis_report`；现有 Diagnostics/报告组件可读取 |

## 结论

v9 目标已完成：Schema 召回从不可观测的空 Chroma 结果，提升为可版本化、可缓存、可回退的本地混合检索；完整公开问题集 A/B 已量化收益。剩余的主要质量问题是模型 SQL 口径与行数限制策略，后续应单独建立“结果完整性”优化目标。

