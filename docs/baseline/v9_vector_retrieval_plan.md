# v9 向量/语义检索提升计划

| 步骤 | 目标 | 状态 | 产物 |
|---|---|---|---|
| v9-0 | 诊断现有 Embedding、Chroma、SchemaRetriever 链路 | 已完成 | `v9_schema_retrieval_diagnosis.md` |
| v9-1 | 生成通用、可版本化的 schema/语义文档 | 已完成 | `tools/build_schema_semantic_documents.py`、D 盘 v9 文档目录 |
| v9-2 | 接入本地词法 + hashing-vector 混合召回，并保留原有 fallback | 已完成（待线上重启） | `schema_hybrid_retriever.py`、`chat.py` |
| v9-3 | 统一问题集做 v8/v9 三轮对照评测 | 待执行 | 复用 `tools/dbgpt_bird_eval.py` 和严格 55 题清单 |
| v9-4 | 索引刷新、缓存命中、失败回退和前端诊断验收 | 待执行 | v9 acceptance report |

本方案不把任何 BIRD 问题写进召回器；表名、列名、关系和少量真实样例均从当前数据源只读生成，因此可迁移到新数据库。Embedding/FAISS 等外部后端可在后续按同一文档协议替换，当前版本不依赖额外下载。

