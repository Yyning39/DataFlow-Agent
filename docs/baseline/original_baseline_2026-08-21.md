# DB-GPT 原版基线记录

日期：2026-08-21  
版本：DB-GPT `0.8.1`（`pyproject.toml`，未修改核心代码）  
运行目录：`D:\1ALL\DB-GPT\DB-GPT-main`  
运行方式：Windows + Python 3.11.9 + 项目 `.venv`  
数据源：内置 `Walmart_Sales` SQLite 数据库

## 1. 启动与健康检查

启动时固定使用以下目录，避免把运行配置写入 C 盘：

```powershell
$env:DBGPT_HOME = 'D:\1ALL\DB-GPT\requirement\dbgpt-home'
.\.venv\Scripts\dbgpt.exe start webserver
```

原版服务监听 `http://127.0.0.1:5670`，本次检查结果如下：

| 检查项 | 结果 | 证据 |
|---|---:|---|
| `/api/health` | 200 | `{"status":"ok"}` |
| `/api/v1/chat/db/list` | 200 | 已加载 `Walmart_Sales` |
| `/api/v1/evaluate/health` | 200 | `{"status":"ok"}` |
| `/api/v2/serve/knowledge/health` | 200 | `{"status":"ok"}` |
| `/openapi.json` | 200 | 292 个 API path |

已发现的核心入口包括：`/api/v1/chat/completions`、`/api/v2/chat/completions`、数据源管理、知识库、会话、多 Agent、AWEL 和评测接口。

## 2. 数据集真值（用于后续对比）

数据库文件：`pilot/examples/Walmart_Sales.db`  
表：`walmart_sales`，共 6,435 行；字段为 `Store`、`Date`、`Weekly_Sales`、`Holiday_Flag`、`Temperature`、`Fuel_Price`、`CPI`、`Unemployment`。

下面是真值查询结果。后续每次改造都使用同一组问题，不能只展示主观回答：

| 编号 | 基线问题 | SQLite 真值 |
|---|---|---:|
| B01 | 表中有多少条记录？ | 6,435 |
| B02 | `Weekly_Sales` 总销售额是多少？ | 6,737,218,987.11 |
| B03 | 平均每条记录销售额是多少？ | 1,046,964.88 |
| B04 | 有多少家门店？ | 45 |
| B05 | 累计销售额最高的门店是哪家？ | Store 20，301,397,792.46 |
| B06 | 节假日与非节假日销售额分别是多少？ | 0：6,231,919,435.55；1：505,299,551.56 |
| B07 | 数据日期范围是什么？ | 原始文本范围：`01-04-2011` 至 `31-12-2010`；日期字段需要规范化后再做时间分析 |

## 3. 原版问答实测

已用原版 API 调用 B01 和 B02，入口和 DB 参数均有效：

```json
{
  "chat_mode": "chat_with_db_execute",
  "select_param": "Walmart_Sales",
  "user_input": "How many rows are in the Walmart sales table?"
}
```

API 能返回 SSE，但模型结果为：`LLMServer Generate Error ... Connection error`。这说明本次不能把 SQL 正确率记为 0%；当前阻塞点是默认 `gpt-4o` 模型服务/网络连接，而不是已经验证出的 SQL 生成错误。待配置可用的模型服务后，再执行 B01-B07 并记录：SQL 生成、SQL 执行、结果数值、耗时和重试次数。

## 4. 原版能力盘点

| 能力 | 原版已有内容 | 当前不足/可展示的改进点 |
|---|---|---|
| 指标知识库 | 有 `MetricInfoAgent` 和 `MetricInfoAction`，可返回指标名、字段、计算规则、维度、阈值等信息 | 更像 Agent 返回结构化信息，尚未形成可版本化、可检索、可约束 SQL 的指标语义层；需要指标定义、同义词、口径冲突和血缘关系 |
| SQL 生成 | DB Chat 的 `chat_with_db_execute` / `chat_with_db_qa` 场景已有 | 缺少统一的 SQL AST 校验、字段/表存在性校验、只读安全策略、自动纠错闭环和错误分类 |
| SQL 校验纠错 | `sql_utils.py` 主要是注释处理； Excel 场景有局部名称修正 | 不是通用数据库校验器；应增加语法校验、Schema 校验、执行前安全检查、错误反馈重写和最大重试次数 |
| 自动分析报告 | 已有 `ReportGenerationAction`、可视化组件、Markdown 报告及 Walmart 分析 Skill | 缺少“结论—SQL—结果—图表”的证据链、引用定位、数值一致性检查和报告质量评分 |
| 多轮对话 | `BaseChat` 管理历史，conversation 服务可持久化消息 | 需要显式的会话状态、指标/筛选条件继承、指代消解、跨轮 SQL 约束；部分 Excel 流程仍有多轮限制 |
| 效果评测 | 已有评测健康端点、Retriever 指标、Answer Relevancy、表格对比服务和公开 benchmark 文件 | 缺少针对 Text-to-SQL 的统一数据集、执行准确率/结果准确率/纠错成功率等端到端指标，以及改造前后自动回归报告 |

## 5. 建议的改造优先级

### P0：先建立可测量闭环

1. 固定 B01-B07 及更多业务问题，保存问题、标准 SQL、标准结果和危险 SQL 样例。
2. 接通稳定的模型服务，先测出原版真实基线：SQL 语法通过率、执行成功率、结果正确率、平均耗时、重试次数。
3. 加入统一 Trace：问题、识别的指标、生成 SQL、校验错误、修复 SQL、最终结果和报告引用。

### P1：最能体现 Agent/产品能力的两块

1. 指标语义层：指标定义、口径、字段映射、维度、时间粒度、同义词和版本；生成 SQL 前必须检索并引用指标定义。
2. SQL 校验纠错 Agent：只读白名单、Schema/AST 校验、执行错误分类、基于错误的有限次修复，并保留每次尝试。

### P2：形成可演示产品闭环

1. 证据驱动的自动分析报告：每个数字绑定 SQL 和结果片段，生成图表、结论、风险提示和可追溯引用。
2. 多轮状态：继承上一轮指标、筛选、时间范围和数据源，支持“那华东呢”“换成同比”等追问。
3. 评测看板：展示原版与改造版的指标提升，而不是只展示一次成功案例。

## 6. 后续对比指标

| 指标 | 计算方式 | 原版当前状态 | 改造后目标（待实测） |
|---|---|---|---|
| SQL 语法通过率 | 可解析 SQL / 总问题数 | 待模型服务可用后测 | 提升并按错误类型拆分 |
| SQL 执行成功率 | 成功执行 / 生成 SQL 数 | 待测 | 目标提升 15–25 个百分点 |
| 结果正确率 | 结果与标准结果一致 / 可执行问题数 | 待测 | 目标 ≥80% |
| SQL 纠错成功率 | 修复后成功执行 / 触发校验的问题数 | 原版无统一闭环 | 目标 ≥60% |
| 指标口径遵循率 | 使用正确指标定义和字段 / 总问题数 | 需人工抽样 | 目标 ≥85% |
| 报告事实一致性 | 报告数字可由引用 SQL 重算 / 报告数字数 | 需建立评测 | 目标 ≥90% |
| 多轮状态保持率 | 正确继承上一轮约束 / 多轮问题数 | 需建立评测 | 目标 ≥80% |

## 7. 环境注意事项

本次启动在 `pilot/meta_data/alembic/versions/` 生成了一个空迁移文件：`a28acefc0b56_new_migration.py`。它是启动副作用，当前不删除、不回滚；后续若要整理工作区，应先确认其是否属于项目预期生成物。

## 8. DeepSeek 接入复测（2026-08-21 16:45）

本次已成功加载 `deepseek-v4-flash`：

- `/api/health`：`{"status":"ok"}`
- `/api/v1/model/types`：`deepseek-v4-flash`
- DB Chat 场景：`chat_with_db_execute`
- 问题：`How many rows are in the Walmart sales table?`
- 生成 SQL：`SELECT COUNT(*) AS row_count FROM walmart_sales;`
- 返回结果：`6435`
- 与 SQLite 真值：一致

这说明 DeepSeek API Key、OpenAI 兼容地址和 DB-GPT LLM Worker 已经能够协同工作。启动过程中 Embedding 仍访问 `https://api.openai.com/v1/embeddings` 并返回 401；这不影响本次 DB Chat 问答，但会影响知识库/RAG，后续需要单独配置 Embedding 模型或本地向量模型。

## 9. 原版 B01-B07 实测指标（DeepSeek，未修改代码）

测试接口：`POST /api/v1/chat/completions`；场景：`chat_with_db_execute`；数据源：`Walmart_Sales`。每题均保存生成 SQL 和返回数据，结果正确按数值允许小数误差 `0.01` 判断。

| 编号 | 生成 SQL | 返回结果 | 耗时（秒） | SQL/执行/结果 |
|---|---|---|---:|---|
| B01 | `SELECT COUNT(*) FROM walmart_sales;` | 6,435 | 10.6 | 通过 / 通过 / 正确 |
| B02 | `SELECT SUM(Weekly_Sales) AS Total_Weekly_Sales FROM walmart_sales;` | 6,737,218,987.11 | 17.8 | 通过 / 通过 / 正确 |
| B03 | `SELECT AVG(Weekly_Sales) AS avg_weekly_sales FROM walmart_sales;` | 1,046,964.8775617715 | 13.9 | 通过 / 通过 / 正确 |
| B04 | `SELECT COUNT(DISTINCT Store) AS num_stores FROM walmart_sales;` | 45 | 12.2 | 通过 / 通过 / 正确 |
| B05 | 按门店汇总并降序取 1 条 | Store 20；301,397,792.46 | 9.2 | 通过 / 通过 / 正确 |
| B06 | 按 `Holiday_Flag` 分组汇总 | Holiday：505,299,551.56；Non-Holiday：6,231,919,435.55 | 20.6 | 通过 / 通过 / 正确 |
| B07 | `SELECT MIN(Date), MAX(Date) FROM walmart_sales;` | `01-04-2011` 至 `31-12-2010` | 14.7 | 通过 / 通过 / 正确 |

### 基线统计

- SQL 转化率：`7/7 = 100%`
- SQL 语法/执行成功率：`7/7 = 100%`
- 结果正确率：`7/7 = 100%`
- 平均响应时间：`14.1 秒`
- 中位响应时间：`13.9 秒`
- 响应时间范围：`9.2–20.6 秒`
- 本轮模型连接错误：`0`

这组结果是当前环境、当前模型和固定问题集下的原版基线，不代表 DB-GPT 在所有数据库或所有问题上的准确率。后续改造必须使用同一问题集、同一数据源和相同评判规则，才能比较提升幅度。

## 10. 改造版 V1 B01-B07 对比评测（DeepSeek，2026-08-21）

本轮已重启服务以加载第一版改造代码：指标语义层 `MetricRegistry`、SQL 只读校验/有限纠错 `SqlGuard`，以及统一评测脚本 `tools/dbgpt_baseline_eval.py`。评测条件与 V0 完全一致：同一模型、同一数据源、同一问题集和同一真值判断规则。

| 编号 | 生成 SQL（关键部分） | 返回结果 | 耗时（秒） | SQL/执行/结果 |
|---|---|---|---:|---|
| B01 | `SELECT COUNT(*) AS row_count FROM walmart_sales;` | 6,435 | 9.48 | 通过 / 通过 / 正确 |
| B02 | `SELECT SUM(Weekly_Sales) AS Total_Weekly_Sales FROM walmart_sales;` | 6,737,218,987.11 | 17.00 | 通过 / 通过 / 正确 |
| B03 | `SELECT AVG(Weekly_Sales) AS avg_weekly_sales FROM walmart_sales;` | 1,046,964.8775617715 | 11.49 | 通过 / 通过 / 正确 |
| B04 | `SELECT COUNT(DISTINCT Store) AS store_count FROM walmart_sales;` | 45 | 20.78 | 通过 / 通过 / 正确 |
| B05 | 按门店汇总、降序并 `LIMIT 1` | Store 20；301,397,792.46 | 17.07 | 通过 / 通过 / 正确 |
| B06 | 按 `Holiday_Flag` 分组汇总 | Holiday：505,299,551.56；Non-Holiday：6,231,919,435.55 | 32.20 | 通过 / 通过 / 正确 |
| B07 | `SELECT MIN(Date), MAX(Date) FROM walmart_sales;` | `01-04-2011` 至 `31-12-2010` | 16.58 | 通过 / 通过 / 正确 |

### V0/V1 汇总

| 指标 | V0 原版 | V1 改造版 | 变化 |
|---|---:|---:|---:|
| SQL 转化率 | 7/7 = 100% | 7/7 = 100% | 持平 |
| SQL 执行成功率 | 7/7 = 100% | 7/7 = 100% | 持平 |
| 结果正确率 | 7/7 = 100% | 7/7 = 100% | 持平 |
| 平均响应时间 | 14.10 秒 | 17.80 秒 | +3.70 秒（约 +26.2%） |
| 中位响应时间 | 13.90 秒 | 17.00 秒 | +3.10 秒 |
| 响应时间范围 | 9.20–20.60 秒 | 9.48–32.20 秒 | 长尾增加 |

### 评测结论

在当前 7 个基础问题上，V0 已经达到 100% 转化、执行和结果正确率，因此 V1 没有继续拉高这些指标的空间。第一版改造的价值应通过新增的困难集体现：危险 SQL 拦截率、故意注入错误后的纠错成功率、指标口径遵循率、复杂多轮问题正确率、报告数字的证据一致性，以及在加入校验/重试后的平均耗时。当前 V1 平均耗时上升，说明后续需要增加 SQL Guard 命中率、重试次数和端到端耗时分解，证明安全性与可解释性收益。

## 11. 改造点专项对比报告

由于 B01-B07 基础集在 V0 中已经达到 100% 正确率，另使用确定性组件测试评估新增能力：

- 指标口径匹配率：V0 `0/4` → V1 `4/4`
- 危险 SQL 预执行拦截率：V0 `0/3` → V1 `3/3`
- 执行失败后的纠错成功率：V0 `0/3` → V1 `3/3`
- SQL 执行可追踪率：V0 `0/1` → V1 `1/1`

完整报告见：[V0/V1 改进点评测报告](D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v0_v1_improvement_report.md)。这组结果是组件级专项评测，不等同于大规模模型准确率；端到端结果仍以本报告第 10 节的同集回归为准。

V1 现在支持按数据源加载指标配置：`configs/metrics/{datasource}.json`；部署时也可以使用 `DBGPT_METRICS_DIR` 指向外部配置目录。找不到配置时会回退到内置默认定义，保证原有 Walmart 流程兼容。

## 12. V2 重启后校验

V2 服务健康检查和模型检查通过。B01-B07 首轮端到端结果为 `6/7`，其中 B02 首轮没有返回可解析 SQL；单题重试后恢复为 `7/7`。通用指标配置、危险 SQL 拦截、SQL 纠错和 Trace 专项均通过。完整记录见：[V2 校验报告](D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v2_validation_report.md)。
