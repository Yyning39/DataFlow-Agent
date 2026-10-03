# v0 / v1 / v2 对比测试记录

生成时间：2026-08-21

## 结论先行

三版代码的确定性能力回归已经完成：v0 没有统一指标注册、SQL Guard 和执行纠错；v1 增加这些能力；v2 在 v1 基础上增加按数据源加载配置和未知数据源隔离。专项测试通过率分别为 0%、100%、100%。

同一模型、同一服务、同一 Walmart 问题集的历史端到端回归结果为：v0 7/7、v1 7/7、v2 首轮 6/7（针对失败题重试后 7/7）。这组结果保留用于回归基线，但 Walmart 是单一数据源，不能代表跨领域 Text-to-SQL 泛化能力。

## 确定性专项对比

| 能力 | v0 原版 | v1 | v2 |
|---|---:|---:|---:|
| 通用指标语义匹配 | 0/4 | 4/4 | 4/4 |
| 危险 SQL 预执行拦截 | 0/3 | 3/3 | 3/3 |
| 执行失败后的有限纠错 | 0/3 | 3/3 | 3/3 |
| SQL 执行 Trace | 0/1 | 1/1 | 1/1 |
| 未知数据源不误用 Walmart 指标 | 不支持 | 不支持 | 通过 |

专项用例使用 orders、marketing_events 等通用业务表，不依赖 Walmart 字段；原始明细见 [v0_v1_improvement_report.md](v0_v1_improvement_report.md) 和 [v2_validation_report.md](v2_validation_report.md)。

## 端到端基线（同一模型和同一 B01-B07 问题集）

| 版本 | SQL 转化率 | 执行成功率 | 结果正确率 | 备注 |
|---|---:|---:|---:|---|
| v0 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 原版 |
| v1 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 指标/Guard 版 |
| v2 首轮 | 6/7 = 85.7% | 6/7 = 85.7% | 6/7 = 85.7% | 1 题无可解析 SQL/data |
| v2 重试后 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 失败题重试恢复 |

## 公开数据集测试准备与限制

已从公开 BIRD Mini-Dev SQLite 数据集生成固定 manifest，保留原始 question、gold SQL、数据库文件和源文件 SHA256，未手写问题：

- 完整子集：22 题、11 个数据库：`docs/baseline/bird_mini_dev_eval_manifest.json`
- 快速子集：1 题，用于连通性验证：`docs/baseline/bird_mini_dev_eval_manifest_1.json`
- 评测脚本：`tools/dbgpt_bird_eval.py`
- 评测结果现在额外记录 `schema_seconds`、`schema_table_count`、`schema_fallback_used`、
  `model_generation_seconds`、`model_first_token_seconds` 和 `sql_execution_seconds`，并在 summary 中给出各项平均值。

早期运行曾因重复注册数据库、SQLite 锁和 embedding 外网请求导致快速失败或长时间等待。修复评测流程后，v1 和 v2 已完成各 22 题；v0 也有一份 22 题旧结果，但若要做严格同条件比较，仍应使用当前的独立 run-id、schema refresh 和本地 embedding 流程重跑 v0。

## 可复现命令

```powershell
.venv\Scripts\python.exe tools\dbgpt_improvement_eval.py
.venv\Scripts\python.exe tools\dbgpt_bird_eval.py `
  --url http://127.0.0.1:5670 `
  --model deepseek-v4-flash `
  --data-root D:\1ALL\DB-GPT\datasets\bird_mini_dev\data `
  --manifest docs\baseline\bird_mini_dev_eval_manifest.json `
  --output docs\baseline\bird_v2_eval.json
```

后续若要得到严格可比的公开集三版准确率，建议使用同一 run-id 按同一 manifest 依次重跑 v0、v1、v2；评测代码和数据已固定，届时只会新增结果文件，不会改变测试集。

## 本轮继续完成的更新

- 自动分析报告已接入数据库结果视图，返回 `analysis_report` 字段。
- SQL Guard 增加错误分类、可选 schema 表引用校验和 `strict_schema` 配置。
- 增加数据源白名单、敏感字段黑名单的 opt-in 权限边界（`DBGPT_ALLOWED_DATASOURCES`、`DBGPT_DENIED_COLUMNS`）。
- 增强多轮提示，要求安全继承上一轮数据库、筛选条件和维度。
- 增加 schema 召回兜底：小型数据库检索结果为空或不完整时自动补齐全表结构，避免相关表未召回导致模型直接放弃生成 SQL。
- 公开 BIRD manifest 的 11 个 SQLite 数据库、22 条官方 SQL 已通过无模型多数据源烟测：`databases=11 cases=22 multisource_smoke=ok`。

## 2026-08-26 在线复核

- 使用独立更新版服务端口 `5674`（不影响用户现有的 `5670`）完成真实请求验证。
- Walmart 查询返回 `SELECT COUNT(*) AS row_count FROM walmart_sales`，结果为 `6435`，响应中的 `chart-view` 已包含 `analysis_report` 字段及数值摘要。
- BIRD 批量评测启动后前两题实际耗时约 133.89 秒和 25.40 秒；第二题已生成并执行 SQL，但结果与 gold SQL 不一致。为避免长时间占用 API，任务已停止，尚未形成完整 v0/v1/v2 公开集准确率。

## 2026-08-26 v2 分项耗时评测

- 使用重启后的 `5670` 服务完成 BIRD Mini-Dev 全部 22 题，结果文件为 `docs/baseline/bird_v2_eval_timed.json`。
- SQL 转化率 `9/22 = 40.9%`，执行成功率 `9/22 = 40.9%`，结果正确率 `5/22 = 22.7%`，平均端到端耗时 `25.22 秒`。
- 已成功返回结构化结果的请求中，平均 schema 准备 `0.35 秒`、模型生成 `19.33 秒`、SQL 执行 `0.024 秒`；因此主要瓶颈是模型生成而非数据库执行。
- 部分题目返回 HTTP 400 或无法解析 SQL，需下一步区分模型输出格式、上下文长度和数据源注册问题，不能直接解读为 SQL 能力准确率。

说明：v2 本次运行的前 8 题曾受到重复数据源注册和旧摘要状态影响，出现 HTTP 400；v0 是更早的历史运行，三版并非完全同条件。因此前两项不能直接用于判断版本优劣。按“已生成 SQL 的题目”计算，v0/v1/v2 的结果正确率分别约为 36.4%（4/11）、30.0%（3/10）和 55.6%（5/9），v2 反而表现出更高的生成后准确性。

## 2026-08-26 v1 完整公开集评测

- v1 使用同一 BIRD Mini-Dev 22 题 manifest 完成评测，结果文件为 `docs/baseline/bird_v1_eval_timed.json`。
- SQL 转化率 `10/22 = 45.5%`，执行成功率 `10/22 = 45.5%`，结果正确率 `3/22 = 13.6%`，平均端到端耗时 `40.50 秒`。
- 本次 v1 评测使用独立 run-id、注册后 schema refresh 和本地 embedding 代理；没有出现数据库锁或 HTTP 400，失败项属于模型未生成可执行 SQL 或结果不正确。

## 2026-08-26 v2 schema 兜底后完整公开集评测

- v2 使用 schema 召回兜底和独立 run-id 完成 BIRD Mini-Dev 22 题，结果文件为 `docs/baseline/bird_v2_eval_schema_fallback.json`。
- SQL 转化率和执行成功率均为 `18/22 = 81.8%`，结果正确率 `5/22 = 22.7%`，平均端到端耗时 `44.74 秒`。
- 平均 schema 准备 `0.76 秒`、模型生成 `44.47 秒`、SQL 执行 `0.057 秒`；schema 兜底触发率为 `100%`。与旧 v2 的 40.9% SQL 转化率相比，覆盖率明显提升，但正确率暂未提升，下一步应优化字段语义和逻辑校验，并降低全表兜底造成的 prompt 延迟。

## 计划中需要明确的四个问题

### 1. 模型、数据库和部署方式

- 大语言模型：DeepSeek `deepseek-v4-flash`，通过 OpenAI 兼容接口接入。
- 当前数据库：SQLite；已使用 Walmart Sales 作为回归库，并准备了公开 BIRD Mini-Dev 的 11 个跨领域 SQLite 数据库。
- 部署方式：Windows 本地 `.venv`，DB-GPT WebServer 运行在 `127.0.0.1:5670`；v0/v1/v2 对比服务使用独立运行目录和端口，避免互相污染。

### 2. 成功率、响应时间和人工节省

目前能对外承诺的实测数据是 B01-B07：v0/v1 结果正确率 7/7，v2 首轮 6/7、重试后 7/7；平均响应时间约为 v0 14.10 秒、v1 17.80 秒、v2 首轮 19.05 秒。人工节省时间尚未做业务人员对照实验，计划用同一批任务记录“人工写 SQL 到得到结果”的时间，与系统端到端时间比较，再报告中位数和节省比例。

### 3. 功能边界

- 多轮问答：DB-GPT 原生支持；计划增加跨轮条件继承的回归集。
- 图表生成：原生支持按结果类型生成可视化；计划增加图表与 SQL 结果一致性检查。
- 权限控制：当前具备 API Key 和数据源连接配置级控制；尚未完成企业级用户/角色/行级权限，列入后续必做项。
- 多数据源：连接管理器支持多数据源，v2 已实现按数据源加载指标配置；计划继续验证 SQLite、MySQL、PostgreSQL 的兼容性。

### 4. 是否实际部署和使用

目前是本人 Windows 本地技术验证环境，已实际启动 WebServer 并完成模型和数据库调用，但没有业务部门生产部署或真实业务人员持续使用记录。因此计划中应写成“完成本地可运行原型和可复现实验”，不要写成“已上线/已被业务使用”。下一阶段若需要业务证明，应安排小范围试用并记录任务量、成功率、响应时间和用户反馈。

## 2026-08-26 下一阶段：枚举值与字段语义校准

针对 v2 中“SQL 可以执行但筛选语义仍可能错误”（例如 Y/N、F/T、0/1 编码含义混淆）的问题，已完成一轮通用改进：

- 在数据库问答提示中加入每张候选表的有界真实行样本，生成“表.字段：示例值”上下文；样本默认最多 8 张表、每表 5 行、每表 12 列、每字段 8 个值，优先状态/类型/标志位字段，避免无限扩大 prompt。
- 对 MySQL、MSSQL、SQLite/PostgreSQL/DuckDB 使用对应的标识符转义；采样只读，不修改任何数据库内容。
- SQL Guard 增加非阻断的枚举值校验：当等值或 `IN` 条件使用了样本中未出现的字符串值时记录告警，不把非穷尽样本误判为硬错误。
- `analysis_report`/评测 timings 增加 `value_hint_seconds`、`value_hint_table_count`、`value_hint_column_count` 和 `sql_value_warning_count`，可用于比较改动前后的语义风险与延迟。

该改动的目标是减少“可执行但业务含义错误”，不是声称仅靠样本就能证明结果正确。下一轮应使用同一 BIRD manifest 重跑 v2，并重点观察结果正确率、模型耗时和告警数量；若告警/延迟过高，再将样本范围收窄到问题相关字段。

## 2026-08-26 value hints 快速复核

重启 5670 服务后使用公开 BIRD California Schools 用例复核，结果文件为
`docs/baseline/bird_v2_value_hints_smoke2.json`：样本值采集成功（3 张表、35 个字段），
`value_hint_seconds=0.0393s`，SQL 转化和执行均成功，但结果正确率仍为 `0/1`。
模型依然将 `Virtual='Y'` 用作“exclusively virtual”，说明该改动已生效，但仅凭样本值无法推断业务编码语义；后续需要指标/字段语义知识库或歧义澄清机制，不能用硬编码替换值。

## 2026-08-26 通用字段语义层（v3 开发中）

- 在 `MetricRegistry` 中增加通用 `FieldDefinition`，支持表、字段、描述、同义词、用户概念到存储值的 `value_mapping`、来源和置信度。
- 语义文件放在 `configs/semantics/`，运行时按数据源加载；BIRD 等带运行后缀的数据源名按稳定前缀匹配，不把规则写进 SQL 代码。
- `configs/semantics/california_schools.json` 记录了 `schools.Virtual` 的公开数据源映射，仅作为验证配置；引擎本身不认识或特判 `Virtual`。
- 生成提示会同时注入指标和字段语义，并要求无明确映射时澄清；样本值仍只作为证据，不替代业务字典。

该版本尚未重新跑完整 22 题评测；需要重启服务后，使用同一 manifest 比较 v2 与 v3 的结果正确率、澄清率和模型耗时。

## 2026-08-26 v3 语义映射快速复核

重启服务后使用同一 California Schools 用例验证，结果文件为
`docs/baseline/bird_v3_semantic_smoke.json`。模型生成了
`schools."Virtual" = 'F'`，SQL 转化、执行和结果正确率均为 `1/1`；说明字段级语义映射已被在线服务加载并生效。
本次端到端耗时 `155.35s`，其中模型生成 `150.41s`，下一步仍需单独优化延迟，并使用完整 22 题评测确认收益不是单题现象。

## 2026-08-26 DeepSeek 非思考模式复核

此前通过 `proxy/openai` 转发时，`thinking_enabled=false` 不会被转换为 DeepSeek 的
`extra_body.thinking.type=disabled`，导致单题等待超过 300 秒。改为 DB-GPT 原生
`proxy/deepseek` 适配器并直接连接 DeepSeek API 后，快速用例结果文件为
`docs/baseline/bird_v3_direct_nonthinking_smoke.json`：SQL 转化、执行和结果正确率均为 `1/1`，端到端耗时降至 `8.59s`，模型生成耗时 `5.97s`。

完整 22 题结果与限制见 [v2_v3_comparison_20260826.md](v2_v3_comparison_20260826.md)。v3 非思考模式结果为：SQL 转化率 `19/22 = 86.4%`、执行成功率 `19/22 = 86.4%`、结果正确率 `7/22 = 31.8%`、平均耗时 `6.93s`。由于历史 v2 使用了不同模型代理配置，该结果属于工程对比而非严格单变量消融实验。
