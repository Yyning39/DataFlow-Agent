# v9 Schema/语义检索诊断与执行记录

## 诊断结论（2026-08-27）

- 线上入口是 `DBSummaryClient.get_db_summary` → `DBSchemaRetriever` → Chroma `similar_search_with_scores`。
- 项目已经存在 Chroma 数据：`pilot/data/chromadb/chroma.sqlite3`，能够看到多个 `*_profile` / `*_profile_field` collection；因此问题不是“完全没有向量库”。
- 当前服务请求中 `timings.schema_retrieval_empty=1`，同时 `schema_local_selection_used=1`、`schema_source_local_complete=1`。这说明线上请求经常没有拿到向量候选，最后依赖本地全表/关键词兜底；旧兜底能保证小库可用，但不提供可复现的向量召回分数和版本化索引。
- 环境探测：`chromadb 0.6.3`、`openai 1.74.0` 可用；`faiss`、`rank_bm25`、`sklearn`、`sentence_transformers` 未安装。为避免占用 C 盘和引入大模型下载，本轮不安装这些依赖。

## v9 已执行的改动

1. 新增 `SchemaHybridRetriever`：使用标准库实现 token overlap + 256 维确定性 hashing-vector cosine 的混合评分，支持缓存命中、索引版本、候选数、最高分和耗时诊断。
2. `ChatWithDbAutoExecute.generate_input_values` 在只读获取完整 schema 后调用本地混合检索；保留现有 Chroma 候选并补齐本地候选，失败时继续走原有兜底。
3. 启动脚本设置 `DBGPT_SCHEMA_HYBRID=true` 和 `DBGPT_SCHEMA_INDEX_DIR=D:\1ALL\DB-GPT\requirement\dbgpt-home\schema_index\v9`。索引是新增缓存，不移动或删除源数据。
4. 新增 `tools/build_schema_semantic_documents.py`，从 SQLite 只读生成 table/column/relationship/sample-value 文档和 `manifest.json`，输出到 `D:\1ALL\DB-GPT\requirement\dbgpt-home\schema_documents\v9`。

## 离线验证

- `test_schema_hybrid_retriever`：2/2 通过（相关表排序、索引持久化/缓存命中、空 schema 安全）。
- 与既有 v8 组件测试合计：15/15 通过。
- Schema 文档生成：BIRD Mini-Dev 11 个数据库、75 张表、984 个文档（table/column/relationship/sample-value，以及配置存在时的 metric/semantic-field 元数据）。

## 下一步验收

重启服务后，以同一模型、同一问题集执行 v8 与 v9 对比，至少记录：

- `schema_retrieval_empty`、`schema_local_hybrid_used`、`schema_local_hybrid_cache_hit`；
- SQL 转化率、执行成功率、严格结果正确率、结果形状正确率；
- `schema_seconds`、模型生成耗时、SQL 执行耗时；
- 首次索引与缓存命中的延迟差异。
