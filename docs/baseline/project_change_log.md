# DB-GPT 改进过程日志

本文记录本项目改进过程中遇到的问题、定位结论、代码修改、验证方式和对评测的影响。所有公开集评测均使用 BIRD Mini-Dev SQLite manifest，不通过针对单题修改测试数据来制造结果。

## 记录规则

- 每次改动记录“问题 → 原因 → 修改 → 验证 → 限制”。
- 评测结果区分 SQL 转化率、执行成功率、结果正确率和分项耗时。
- 若两个版本同时改变了模型、代理或数据源注册方式，不将结果表述为严格单变量实验。

## 已完成记录

### 2026-08-21～2026-08-26：基线与评测框架

- 问题：原始测试主要是手工用例，无法稳定比较 v0/v1/v2。
- 修改：固定公开 BIRD Mini-Dev 22 题、11 个 SQLite 数据库，新增 `tools/dbgpt_bird_eval.py` 和 manifest。
- 修改：评测器记录 SQL 转化、执行、结果正确率以及 Schema、模型、首 token、SQL 执行耗时。
- 限制：早期 v0/v1/v2 运行包含不同服务注册和模型配置，不能直接视为严格 A/B 实验。

### 2026-08-21～2026-08-26：数据库注册、锁和 embedding 外部依赖

- 问题：重复注册 BIRD 数据源时出现 SQLite 锁、HTTP 400 或首题长时间等待；默认 embedding 还会访问外部服务。
- 原因：每次运行使用相同数据源名，schema 摘要异步生成，且 embedding 配置依赖外网。
- 修改：评测器增加 `--run-id`，注册名按运行隔离；新增本地 OpenAI 兼容 embedding 代理；注册后支持显式 schema refresh。
- 后续修正：逐库 refresh 在服务繁忙时仍可能长时间等待，评测器增加 `--skip-refresh`，依赖运行时直接 schema 回退。
- 影响：评测可重复执行，不影响用户现有 5670 服务和数据库文件。

### 2026-08-21～2026-08-26：SQL 安全与有限纠错

- 问题：模型可能输出写操作、多条语句、未知表或超大明细查询。
- 修改：`SqlGuard` 增加只读校验、单语句校验、schema 表引用校验、错误分类、有限 `LIMIT` 修复和 `SqlExecutionTrace`。
- 修改：增加数据源白名单和敏感列黑名单边界。
- 验证：危险 SQL、缺失 LIMIT、权限边界和分析报告相关单元测试通过。
- 限制：结构安全不等同于业务语义正确；“能执行”仍可能得到错误结果。

### 2026-08-26：Schema 召回兜底

- 问题：新注册数据库的向量摘要为空或不完整时，模型直接认为无法生成 SQL。
- 修改：小型数据库在摘要为空/不完整时回退到完整 `table_simple_info`，并记录 `schema_fallback_used` 与表数量。
- 结果：旧 v2 schema 兜底评测 SQL 转化率达到 `18/22 = 81.8%`，但结果正确率仍为 `5/22 = 22.7%`。
- 限制：全表上下文可能增加 Prompt 长度；后续需要语义选择和缓存优化。

### 2026-08-26：真实样本值提示

- 问题：模型面对 `Y/N`、`F/T`、`0/1` 等标志位时可能猜错含义。
- 修改：从候选表只读抽取有界样本值，注入 Prompt；增加 `value_hint_*` 指标和样本值告警。
- 兼容性问题：SQLite 的 schema 字符串带末尾分号，初版解析器没有识别，导致样本数为 0。
- 修复：解析器允许末尾分号，并增加 SQLite/ MySQL/ MSSQL/ PostgreSQL/DuckDB 标识符转义。
- 结果：样本采集成功，但 California Schools 用例仍生成 `Virtual='Y'`，说明样本只能证明值存在，不能证明业务含义。

### 2026-08-26：通用字段语义层（v3）

- 问题：`Virtual` 的正确编码不能从字母本身推断。
- 修改：在 `MetricRegistry` 中增加通用 `FieldDefinition`，支持字段描述、同义词、用户概念到存储值的 `value_mapping`、来源和置信度。
- 修改：新增 `configs/semantics/california_schools.json` 作为数据源配置；引擎不在代码中特判 `Virtual`。
- 修改：Prompt 同时注入指标语义和字段语义，未知或歧义时要求澄清。
- 验证：同一 BIRD 用例生成 `schools.Virtual = 'F'`，结果正确率 `1/1`。
- 限制：目前已实现“提示和配置”，真正的交互式澄清流程仍待完成。

### 2026-08-26：思考模式与模型代理问题

- 问题：通过 `proxy/openai` 转发时，配置中的 `thinking_enabled=false` 没有转换成 DeepSeek 所需的 `extra_body.thinking.type=disabled`。
- 结果：单题曾超过 300 秒超时；使用错误/未注册的 `deepseek-v4-pro` 时又出现快速但无 SQL 输出。
- 修改：改用 DB-GPT 原生 `proxy/deepseek` 适配器，直接连接 DeepSeek API，并设置 `deepseek-v4-flash` 非思考模式。
- 验证：同一题端到端耗时从约 `155s` 降至 `8.59s`，结果保持正确 `1/1`。
- 限制：模型供应商仍可能产生网络长尾，因此评测器还需要单题硬超时并继续下一题。

### 2026-08-26：v3 完整公开集评测

- 结果文件：`docs/baseline/bird_v3_direct_nonthinking_eval.json`
- SQL 转化率：`19/22 = 86.4%`
- 执行成功率：`19/22 = 86.4%`
- 结果正确率：`7/22 = 31.8%`
- 平均端到端耗时：`6.93s`
- 平均模型生成耗时：`7.07s`
- 平均 SQL 执行耗时：`0.051s`
- 限制：历史 v2 使用了不同模型代理配置，因此 v2/v3 当前属于工程对比，不是严格单变量消融实验。

## 待记录的后续步骤

1. 固定非思考模型配置，仅切换语义注册表，完成严格 v2/v3 消融对比。
2. 增加评测器单题硬超时、模型输出长度限制、Prompt/schema 缓存，并记录 P50/P95。
3. 增加 SQL AST 校验和结果级异常检查。
4. 完成字段语义歧义的实际澄清交互。
5. 完善前端 SQL、语义依据、告警、分析报告和版本对比面板。

## 2026-08-26：评测器长尾保护（第 2 步开始）

- 问题：模型流式响应持续输出时，普通 HTTP 读取超时不会生效，单题可能阻塞整个 22 题评测。
- 修改：`tools/dbgpt_bird_eval.py` 增加 `--case-timeout`（默认 180 秒），按墙钟时间检查流式读取；超时记录 `model_timeout` 并继续下一题。
- 修改：评测 summary 增加 `model_timeout_rate`，便于区分模型长尾和 SQL/数据库错误。
- 验证：评测器编译检查通过，相关单元测试 5 个通过。

### 2026-08-26：续跑评测、结构校验与语义歧义决策（第 2～4 步继续）

- 问题：评测中断后只能从头开始，长尾耗时缺少 P50/P95；表存在性校验无法覆盖部分结构风险；字段语义虽能注入 Prompt，但没有可解释的“已解析/需澄清”状态。
- 修改：`tools/dbgpt_bird_eval.py` 增加 `--checkpoint`/`--resume`，每题落盘结果并支持跳过已完成题；summary 增加端到端和模型生成的 P50/P95。
- 修改：`SqlGuard` 增加结构树级检查（括号、`SELECT INTO`、执行/导出命令、空 CTE）和结果级数据质量告警（超出行数、NaN/Infinity）；危险结构直接拒绝，结果异常保留在 trace 中供前端和评测统计。
- 修改：`MetricRegistry.semantic_decision` 根据配置化字段、别名和 value mapping 返回 `resolved` 或 `clarification_required`；增加 `DBGPT_DISABLE_FIELD_SEMANTICS=true` 以支持同模型严格消融。
- 验证：新增 SQL 结构/结果告警和语义决策单元测试；待服务重启后用同一模型完成 v2（关闭语义）/v3（开启语义）/v4（开启校验）严格对比。
- 限制：当前环境未安装 `sqlglot`，结构检查使用已有 `sqlparse` 的 token tree 和方括号/关键字规则；不声称替代完整方言 AST。

### 2026-08-26：前端可解释性联调（第 5 步继续）

- 修改：执行 trace 通过 `analysis_report` 生成链路传递到前端；图表视图和数据库聊天视图增加 `Diagnostics` 标签，展示 Schema/值提示/模型/SQL 分项耗时。
- 修改：自动分析报告现在包含 SQL Guard 的尝试次数、纠错状态、执行 SQL、错误类型和结构/结果告警（如果有）。
- 限制：当前工作区未安装 `web/node_modules`，尚未运行 Next.js 类型检查和浏览器端联调；后端字段已保持向后兼容。

### 2026-08-26：字段歧义实际拦截（第 4 步完成组件闭环）

- 问题：仅在 Prompt 中提醒模型澄清，模型仍可能忽略提醒并直接生成 SQL。
- 修改：`ChatWithDbAutoExecute` 将 `MetricRegistry.semantic_decision` 写入执行 callable；`DbChatOutputParser` 在 `clarification_required` 时确定性阻止 SQL 执行，直接返回候选字段澄清消息。
- 验证：新增 `test_ambiguous_semantics_block_sql_execution_and_ask_user`，确认执行函数不会被调用且用户收到澄清提示。

### 2026-08-26：语义证据前端展示（第 5 步继续）

- 修改：后端 chart-view payload 增加 `semantic_decision`；前端增加 `Semantics` 标签，展示解析状态、候选字段、概念和存储值，形成可审计的语义依据。
- 验证：Python 解析器单元测试 4/4 通过，后端编译检查通过；前端构建仍待安装已有依赖后执行。

### 2026-08-26：严格版本对比工具（第 1 步继续）

- 修改：新增 `tools/compare_bird_versions.py`，读取 v2/v3/v4 完整评测 JSON，校验模型与 manifest 一致性，并输出指标、P50/P95 和超时率对比；条件不一致时明确标记为工程参考。
- 验证：脚本编译和 `--help` 检查通过；待新版服务启动后生成三份同条件结果文件。

### 2026-08-26：服务重载状态

- 问题：启动新版实例时发现 5670 已被 PID 25956 占用，重复启动返回 Windows `WinError 10048` 并自动退出。
- 处理：未强制终止未知进程，避免影响用户当前服务和数据；确认旧实例仍可访问根页面和数据库列表。
- 下一步：关闭旧实例后，用相同 `DBGPT_HOME` 启动一次，使本轮 SQL Guard、语义拦截和前端 payload 改动加载，再开始严格 v2/v3/v4 评测。

### 2026-08-27：旧实例验证

- 验证：对当前 5670 服务执行 BIRD California Schools 第 5 题，返回 SQL 使用 `Virtual = 'Y'`，结果正确率为 false；这证明当前端口服务尚未加载本轮配置化语义拦截（新版应解析为 `F` 或要求澄清）。
- 结论：不能将当前服务结果冒充 v3/v4；必须先关闭 PID 25956 对应旧实例并重新启动，再进行严格对比。

### 2026-08-27：稳定数据源名语义匹配修复

- 问题：重启后对已有稳定数据源名 `BIRD_california_schools` 做冒烟时，语义上下文仍显示未匹配；带评测 run-id 的名称可以匹配，稳定名称不能匹配。
- 原因：语义解析只识别 `BIRD_<stem>_<run-id>` 前缀，没有覆盖无 run-id 的 `BIRD_<stem>`。
- 修改：`MetricRegistry.for_datasource` 增加稳定名称精确匹配，保持带 run-id 的评测注册兼容。
- 验证：代码级匹配冒烟通过；需再次重启服务后确认端到端 payload。

### 2026-08-27：本地代理循环依赖定位

- 问题：将 DB-GPT 5670 配置为 `proxy/deepseek` 且 `api_base=http://127.0.0.1:5699/v1` 后，模型请求在 20～120 秒内超时。
- 原因：`tools/local_openai_proxy.py` 的上游固定为 5670 `/api/v1/chat/completions`；5670 再指向 5699 会形成 5670 → 5699 → 5670 循环。
- 处理：停止错误配置的 5670 实例，未删除或移动任何数据；保留 5699 桥接脚本供“主服务直连模型”时使用。
- 正确配置：5670 必须直连用户已配置的 DeepSeek API（`proxy/deepseek`、`DEEPSEEK_API_BASE` 和真实 `DEEPSEEK_API_KEY`），不要将其 api_base 指向 5699。

### 2026-08-27：代理可用性复核

- 验证：5699 `/v1/models` 和 `/v1/embeddings` 可返回，但 `/v1/chat/completions` 在 15～40 秒内无响应；结合桥接脚本可确认这是上游 5670 不可用/循环时的预期表现，而不是 BIRD 或 SQL 代码错误。
- 处理：评测器将连接/读取长尾统一记录为 `model_timeout`，并保留 checkpoint；严格 v2/v3/v4 评测需在 5670 直连真实模型后执行。

### 2026-08-27：版本对比面板数据契约

- 修改：新增 `web/components/chat/chat-content/version-comparison.tsx`，支持展示 v2/v3/v4 的转换率、执行率、结果正确率、平均/P50/P95 延迟和超时率。
- 修改：后端读取可选环境变量 `DBGPT_VERSION_COMPARISON_FILE`，将对比 JSON 注入 chart-view payload；未配置时保持旧行为。
- 验证：后端编译和解析器 4/4 单元测试通过；前端依赖未安装，浏览器构建仍待执行。

### 2026-08-27：评测复用已注册数据源

- 问题：每次严格版本评测创建带 run-id 的数据库副本，会触发摘要/embedding 初始化，放大启动等待并产生无关长尾。
- 修改：`dbgpt_bird_eval.py` 增加 `--reuse-registered`，可复用已有 `BIRD_<db_id>` 注册，仅在数据源确实不存在时才注册新副本。
- 影响：不修改数据库文件；适合同一 manifest 的 v2/v3/v4 对比，降低 schema 初始化噪声。

### 2026-08-27：严格评测实验契约

- 问题：历史 v2/v3 结果只记录了模型名和 manifest 路径，无法证明 API 地址、provider、manifest 内容和超时设置一致；直接横向比较会夸大或误判改进效果。
- 修改：`dbgpt_bird_eval.py` 为 checkpoint 和最终 JSON 写入 `experiment_contract`（模型、manifest SHA-256、case timeout、provider、API base）；`compare_bird_versions.py` 改为要求三份结果契约完整且一致，缺失时明确标记为非严格 A/B。
- 验证：编译通过；历史结果因缺少契约被正确判定为“只能作为工程参考”，不会冒充严格对比。

### 2026-08-27：直连模型前置条件

- 问题：当前 5670 主服务已停止，5699 本地桥接只提供模型列表/embedding；其聊天上游固定指向 5670，不能作为 5670 的 api_base，否则形成循环依赖。
- 结论：严格 v2/v3/v4 评测前，必须在用户终端配置真实 `DEEPSEEK_API_KEY`，并让 5670 通过 `proxy/deepseek` 直连 DeepSeek API；不修改或移动现有项目数据。

### 2026-08-27：本轮离线验证

- 通过：分析报告/语义澄清单元测试 4/4；Python 编译检查通过；SQL Guard 冒烟确认能拦截括号不平衡和 `SELECT INTO`，并对超出行数的结果产生告警。
- 受限：当前虚拟环境未安装 `pytest`，前端 `web/node_modules` 不存在，因此 pytest 全量和 Next.js 构建留待依赖/模型服务恢复后执行。

### 2026-08-27：SQL 结构可解释性补强

- 修改：`SqlGuard` 在执行追踪中新增 AST-like 结构快照，记录语句类型、涉及表/CTE、JOIN/WHERE/GROUP/ORDER/LIMIT、子查询和 token 数；自动分析报告同步展示该结构。
- 目的：让 SQL 校验不只返回“通过/失败”，还可以在前端解释实际检查了什么；保留 sqlparse 的方言中立边界，不将 token tree 冒充完整方言 AST。
- 验证：CTE + JOIN + WHERE + ORDER BY + LIMIT 结构冒烟通过，快照正确记录表和结构标志。

### 2026-08-27：服务启动复核

- 验证：在当前 Codex PowerShell 执行 `tools/start_dbgpt_deepseek.ps1`，脚本按设计拒绝启动并提示缺少 `DEEPSEEK_API_KEY`；说明密钥只配置在用户另一个终端时不会自动继承到本进程。

### 2026-08-27：版本消融能力标记

- 问题：评测器原先的 `--variant` 只是标签，无法证明服务确实运行了对应 v2/v3/v4 能力。
- 修改：`SqlGuard` 增加 `DBGPT_SQL_GUARD_ENHANCED` 开关；服务 payload/评测结果记录 `runtime_features` 和配置不匹配率。目标定义为：v2 关闭语义与增强 Guard，v3 仅启用语义，v4 同时启用语义与增强 Guard；严格对比要求不匹配率为 0。
- 验证：代码编译与报告单测通过；当前 5670 是修改前启动的旧进程，冒烟返回 `runtime_features={}`、`configuration_mismatch=true`，必须重启后才能开始新版严格评测。

### 2026-08-27：严格 v2 评测

- 配置：同一 DeepSeek 模型、同一 BIRD Mini-Dev 22 题 manifest、同一已注册 SQLite 数据源、case timeout 120 秒；关闭字段语义和增强 SQL Guard。
- 结果：SQL 转化率 86.36%，执行成功率 86.36%，结果正确率 45.45%，平均延迟 6.74 秒，P50 5.43 秒，P95 13.66 秒，模型生成均值 6.31 秒，模型超时率 0%，运行时配置不匹配率 0%。
- 产物：`docs/baseline/bird_v2_strict_eval.json` 和 `bird_v2_strict_checkpoint.json`。

### 2026-08-27：严格 v3 评测

- 配置：同一模型、manifest、SQLite 数据源和 120 秒单题超时；启用字段语义，关闭增强 SQL Guard。
- 结果：SQL 转化率 90.91%，执行成功率 90.91%，结果正确率 45.45%，平均延迟 7.09 秒，P50 6.55 秒，P95 12.36 秒，模型生成均值 6.96 秒，模型超时率 0%，运行时配置不匹配率 0%。
- 产物：`docs/baseline/bird_v3_strict_eval.json` 和 `bird_v3_strict_checkpoint.json`。

### 2026-08-27：严格 v4 评测与三版本对比

- 配置：同一 DeepSeek `deepseek-v4-flash`、同一 22 题 BIRD Mini-Dev manifest（SHA-256 `5b786fa35e0ccd1d54046ba7ab0b9228e461fe689f7bf0e9e110f6c5ad4be99f`）、同一 SQLite 数据源、同一 `proxy/deepseek` API、120 秒单题超时。
- v4 结果：SQL 转化率 86.36%，执行成功率 86.36%，结果正确率 36.36%，平均延迟 6.35 秒，P50 6.37 秒，P95 9.79 秒，模型生成均值 6.44 秒，超时率 0%，配置不匹配率 0%。
- 对比结论：v3 相比 v2 转化率提升 4.55 个百分点但平均延迟增加 0.35 秒；v4 相比 v3 平均延迟降低 0.74 秒、P95 降低 2.57 秒，但本次随机模型输出的结果正确率下降 9.09 个百分点，不能宣称 v4 在准确率上改进。三版本实验契约完全一致，报告标记 `compatible=true`。
- 产物：`bird_v4_strict_eval.json`、`bird_v4_strict_checkpoint.json`、`bird_v2_v3_v4_strict_comparison.md/.json`。

### 2026-08-27：严格对比报告接入启动脚本

- 修改：`start_dbgpt_deepseek.ps1` 新增 `-VersionComparisonFile` 参数；未显式传参时自动加载已生成的 `bird_v2_v3_v4_strict_comparison.json`（文件存在时），让新版服务的前端 payload 自动包含版本对比数据。
- 验证：PowerShell 语法解析通过；服务重启后还需做一次网页/API payload 冒烟确认。

### 2026-08-27：前端校验告警面板

- 修改：chart-view payload 新增 `validation_warnings` 和 `sql_structure`；前端增加 Alerts 与 SQL Structure 标签页，分别展示结果级/结构级告警和可解释结构快照。
- 验证：后端解析器编译、分析报告单元测试通过；Next.js 构建仍待 `web/node_modules` 安装后执行。
- 补充：兼容 gpt-vis 的 `vis-chart` 路径也已透传这些字段，避免新面板只在一种渲染路径生效。
- 验证：构造同契约 v2/v3/v4 临时结果后，对比工具判定 compatible=true；历史无契约结果判定 compatible=false。

### 2026-08-27：前端依赖缓存检查

- 尝试：使用 D 盘 `requirement\npm-cache` 执行 `npm ci --offline --ignore-scripts`。
- 结果：缓存缺少 `html2canvas` 包，离线安装以 `ENOTCACHED` 退出；未创建 `web\node_modules`，未删除或移动任何其他内容。Next.js 构建继续等待网络可用或补齐缓存。

### 2026-08-27：前端依赖安装与构建验证

- 修改：在 D 盘 npm 缓存下执行 `npm install --no-package-lock --ignore-scripts`，成功安装 1621 个依赖到 `web\node_modules`，没有改写 `package-lock.json`。
- 验证：Next.js 生产构建实际运行；项目原始构建脚本因 Windows 不支持 `NODE_OPTIONS=...` 语法，改用 PowerShell 等效命令后进入 webpack，但因大型 MUI/AntV 依赖触发 `EMFILE: too many open files` 失败。增加 `experimental.cpus=1` 后仍复现，说明是项目依赖图的 Windows 文件句柄限制。
- 定向 TypeScript 检查未发现本轮三个新增/透传组件的错误；全项目仍有既有 locale、chart、utils 类型错误，已保留原状未扩大修改范围。
- 补充复测：设置 Next `NEXT_PRIVATE_BUILD_WORKER=1` 并将 `experimental.cpus` 限为 1 后，仍在 `next-trace-entrypoints-plugin` 打开 MUI 图标时触发 EMFILE；该限制与本轮组件代码无关。

### 2026-08-27：构建依赖图收敛尝试

- 修改：将现有 `@mui/icons-material` barrel import 改为四个图标的 direct import，减少 webpack 追踪文件数；不改变组件行为。
- 验证：再次以 `cpus=1`、`NEXT_PRIVATE_BUILD_WORKER=1` 构建，进程持续高内存运行超过 7 分钟且无阶段输出，最终人工中止；未生成可交付的生产构建，问题仍属于项目整体依赖规模/Windows 构建资源限制。

### 2026-08-27：Windows 前端构建资源开关

- 修改：`next.config.js` 增加 `NEXT_OUTPUT_FILE_TRACING=false` 可选开关，默认仍开启 NFT；保留 `experimental.cpus=1`。同时将 MUI 图标改为 direct import，减少不必要的依赖扫描。
- 验证：关闭 NFT 后构建仍在大型 webpack 编译阶段超过 8 分钟且内存持续增长，主动中止；未出现新的代码错误，但当前机器无法完成生产构建验证。

### 2026-08-27：最终可比评测前的解析器与确定性修复

- 修复：流式响应中 `<chart-view>` 后存在文本尾部时，评测器不再只读取最后一个内容块，而是从后向前寻找最后一个有效 payload，避免把合法 SQL 误判为未生成。
- 调整：v2/v3/v4 评测统一显式发送 `temperature=0`，并将模型、API、数据清单、超时和温度写入实验契约，确保三版本可严格比较。
- 验证：当前 v2 服务运行时特征为 `semantic_enabled=false`、`enhanced_sql_guard=false`，与 v2 配置一致；运行时配置不匹配率为 0%。
- 结果：v2 最终确定性评测 22 题，SQL 转化率 81.82%，执行成功率 81.82%，结果正确率 45.45%，平均延迟 6.38s，P50 7.03s，P95 8.66s，模型生成平均 6.25s，超时率 0%。输出 `bird_v2_final_eval.json`。
- 结果：v3 最终确定性评测 22 题，运行时特征为 `semantic_enabled=true`、`enhanced_sql_guard=false`，配置不匹配率 0%；SQL 转化/执行成功率 86.36%，结果正确率 36.36%，平均延迟 6.66s，P50 6.64s，P95 13.84s，模型生成平均 6.83s，超时率 0%。输出 `bird_v3_final_eval.json`。
- 结果：v4 最终确定性评测 22 题，运行时特征为 `semantic_enabled=true`、`enhanced_sql_guard=true`，配置不匹配率 0%；SQL 转化/执行成功率 90.91%，结果正确率 36.36%，平均延迟 7.72s，P50 6.96s，P95 11.85s，模型生成平均 8.10s，超时率 0%。输出 `bird_v4_final_eval.json`。
- 对比：v2/v3/v4 使用同一模型、manifest、API、temperature=0 和 120s 超时，严格兼容性判定为 `compatible=true`。v4 的 SQL 转化率最高（较 v2 +9.09 个百分点），但平均模型生成耗时较 v2 增加 1.85s，结果正确率未提升；后续优化重点应放在结果级校验、语义消歧和低延迟模型/提示词，而不是继续叠加 Guard 规则。
- 过程问题：v4 首次整批评测中途服务进程重启，后续请求出现连接失败并造成运行时不匹配；未采纳该批次结果。服务恢复后重新从头运行，最终批次 22/22 均配置匹配，作为正式 v4 数据。
- 展示接入：启动脚本默认读取 `bird_v2_v3_v4_final_comparison.json`，后续重启服务后，网页端可通过 `version_comparison` 字段加载本次严格对比结果。

### 2026-08-27：扩大 BIRD 评测集并建立 55 题基线

- 数据：从公开 `mini_dev_sqlite.json` 按数据库和难度确定性抽取 11 个数据库、每库 5 题，共 55 题；未修改题目、证据、gold SQL 或数据库内容。
- 结果：v4 运行时配置匹配率 100%，SQL 转化/执行成功率 87.27%，结果正确率 34.55%，平均延迟 7.29s，P50 6.34s，P95 11.15s，模型生成平均 7.42s，超时率 0%。
- 产物：`bird_mini_dev_eval_manifest_5perdb.json`、`bird_v4_55_eval.json` 及可断点续跑的 `bird_v4_55_checkpoint.json`。
- 结论：扩大样本后，v4 的生成成功率仍明显高于 22 题基线，但结果正确率仍是主要瓶颈，下一步进入结果级校验与自动纠错优化。

### 2026-08-27：结果级校验线上验收

- 验证：重启 v4 后真实调用 `/api/v1/chat/completions`，响应包含 `result_row_count=1`、`sql_structure`、`analysis_report`、3 行 `version_comparison` 和 v4 运行时特征。
- 结论：新增结果行数和校验字段已进入线上 payload，前端 Diagnostics/Alerts/SQL Structure/Version Comparison 面板具备真实数据来源。

### 2026-08-27：低延迟模型可用性审计

- 方法：选取 3 道跨数据库公开题目，统一 v4 运行时、temperature=0 和 60s 超时，对当前已注册模型及候选模型做冒烟横评。
- `deepseek-v4-flash`：3/3 生成 SQL，结果正确率 66.67%，平均总耗时 5.80s，平均模型生成耗时 5.24s，0 超时。
- `deepseek-chat`、`deepseek-reasoner`：当前服务未注册对应模型，3 题均无 SQL，平均响应约 0.4s；该结果标记为“不可用/未注册”，不作为准确率结论。
- 结论：当前可验证的低延迟默认模型仍是 `deepseek-v4-flash`；要完成真实多模型成本横评，需要分别以候选模型启动服务并确认 API 账户已开通对应模型。当前请求未产生模型费用估算数据，不能虚构账单成本。
- 复测：启动并注册 `deepseek-chat` 后，用同一 3 题样本完成横评：SQL 生成率 100%，结果正确率 66.67%，平均总耗时 4.59s，平均模型生成耗时 4.17s，0 超时；相同样本的 `deepseek-v4-flash` 为 5.80s/5.24s，正确率同为 66.67%。
- 结论：在当前样本上 `deepseek-chat` 比 v4-flash 平均总延迟降低约 20.9%，准确率相同，具备低延迟候选资格；实际费用仍需读取 API usage 或账单，当前服务响应未返回 token 用量，因此不虚构成本数字。

### 2026-08-27：v4 失败分类与 Schema 关键字修复

- 基线分析：55 题中 48 题生成并执行 SQL，19 题结果正确；7 题无 SQL，其中 financial 数据库 5 题均在 schema 读取阶段失败。
- 根因：SQLite `table_simple_info()` 使用未加引号的 `PRAGMA table_info(order)`，`order` 是 SQL 关键字，导致 `sqlite3.OperationalError`，不是模型本身无法理解问题。
- 修改：对 PRAGMA 的表名进行单引号转义，支持所有合法 SQLite 表名；新增关键字表名单元测试。
- 离线验证：直接读取公开 financial 数据库成功发现 8 张表，并正确返回 `order(order_id,account_id,bank_to,account_to,amount,k_symbol)`。

### 2026-08-27：问题意图与 SQL 结构一致性诊断

- 修改：`SqlGuard.execute` 接收自然语言问题，对“多少/数量/平均/比例/列出”等常见意图与 SQL 聚合、GROUP BY 结构做非阻断一致性检查。
- 行为：只输出可解释的 `validation_warnings`，不自动重写复杂 SQL；避免启发式规则破坏合法方言查询。
- 验证：数量问题缺少 `COUNT` 时能产生告警；平均问题包含 `AVG` 时无误报；分析报告单元测试 4/4 通过。
- 防幻觉补强：数据类问题现在要求模型必须填充 `sql`；解析器会拒绝“直接给出数字但没有 SQL”的回答，防止把未执行的估算值当成数据库结果。

### 2026-08-27：模型 usage 与成本观测补强

- 修改：评测器解析 SSE 最终累计内容，记录 `provider_usage`（供应商返回时）、`estimated_output_tokens`（未返回 usage 时按字符估算）和响应字符数，汇总 `provider_usage_available_rate`。
- 口径：估算 token 仅用于模型间相对比较，不替代供应商账单；当前 DeepSeek 服务返回的 usage 为空，因此报告必须标注“估算/不可计费”。
- 验证：评测器编译通过，并能从实际 SSE 响应提取最终输出长度和估算 token 数。
- 新增：可选 `DBGPT_MODEL_ROUTING=true` 路由器；短且无 JOIN/分组/比较关键词的问题走 `DBGPT_FAST_MODEL`，复杂问题走 `DBGPT_ACCURATE_MODEL`，并把路由原因写入 `runtime_features`。默认关闭，避免未注册模型导致请求失败。
- 验证：路由单元测试 3/3 通过，默认关闭时保持用户指定模型。

### 2026-08-27：Schema 来源与 fallback 口径优化

- 修改：完整本地 Schema 成功加载时，不再把它记为失败 fallback；新增 `schema_retrieval_empty` 和 `schema_source_local_complete` 分项，区分向量检索为空与最终 Schema 不可用。
- 目的：避免把“检索索引暂不可用但本地完整 Schema 可用”误报成系统失败，同时保留对索引健康度的观测。
- 验证：后端编译和 MetricRegistry/分析报告测试通过；需服务重启后用 financial 和 55 题回归确认线上指标变化。
- 新增：向量检索为空时按问题词与表名/列名进行确定性本地 top-k 召回；没有任何匹配才使用完整 Schema，减少大库 Prompt 噪声。
- 验证：`_select_local_schema` 能从 schools/satscores/teachers/frpm 中召回前两张相关表，完全无匹配时保留全表。

### 2026-08-27：图表类型提示补全

- 发现：后端 `_generate_numbered_list()` 未把前端已支持的 `response_bar_chart` 提供给模型，用户要求分类对比图时模型只能退回表格或其他图表类型。
- 修改：增加条形图选项及适用场景说明“按类别比较数值”，保持前端 AutoChart 已有的类型契约不变。
- 验证：`base_chat.py` 编译通过；需重启后用分类聚合问题验证模型是否稳定返回 `response_bar_chart`。
- 配置补强：启动脚本现在显式设置绝对路径 `DBGPT_SEMANTICS_DIR`，避免从不同工作目录启动时找不到 datasource 语义 JSON。
- 解析补强：后端将 `Bar`/`Bar chart`、`Line`/`Line chart` 等常见模型标签规范化为 `response_*_chart`，降低模型输出格式差异造成的前端降级。
- 验证：图表标签归一化测试通过，相关场景测试共 9/9 通过。

### 2026-08-27：Schema/语义修复线上回归

- 线上验证：重启 v4 后，financial q92 返回 SQL、`semantic_decision.status=resolved`（`district.A11`）、结果行数和完整 SQL 结构；Schema fallback=0，检索为空=1，本地完整 Schema=1。
- 回归：financial 5 题 SQL 转化率 100%、执行成功率 100%、结果正确率 40%；修复前 5 题全部无 SQL（0% 转化/执行）。
- 结论：关键字表名和 financial 语义配置已解决“Schema 阶段直接失败”问题；剩余 3/5 错误属于模型业务逻辑/查询口径问题，进入更通用的语义覆盖与结果纠错阶段。

### 2026-08-27：产品化能力冒烟验收

- 多轮对话：复用同一 `conv_uid` 连续提问两轮，第二轮成功生成基于上下文的 `LIMIT 5` 查询并返回数据。
- 多数据源：55 题、11 个数据库的 SQLite 连接冒烟测试通过（`multisource_smoke=ok`）。
- 权限控制：SQL access policy 单元测试与分析报告测试共 6/6 通过。
- 前端：SQL、语义、告警、分析报告、Diagnostics、SQL Structure、Version Comparison 组件定向 ESLint 通过；生产构建仍受 Windows EMFILE/大型依赖图限制。
- 图表：前端自动图表渲染路径已接入统一 payload；本轮自然语言图表请求未稳定生成 chart 类型，标记为后续提示词/模型适配项，不虚构已完成的图表效果。

### 2026-08-27：结果形状诊断与成本观测契约

- 发现：financial q159 的过滤条件和执行均成功，但模型把用户只要求的 `trans_id` 扩展成 8 列；原有“结果正确率”无法区分值正确、列形状不符和真正的过滤错误。
- 修改：`SqlExecutionTrace` 和 chart-view payload 增加 `result_column_count`；评测器增加 `expected_column_count`、`result_shape_match` 和 `result_shape_match_rate`，前端 Diagnostics 展示行数与列数。
- 修改：评测器读取供应商 usage 中的 input/output token；未提供 usage 时继续记录估算输出 token。只有显式设置 `DBGPT_INPUT_PRICE_PER_MILLION` / `DBGPT_OUTPUT_PRICE_PER_MILLION` 才计算美元成本，未配置或输入 token 缺失时保持 `null`，不虚构账单。
- 验证：SQL Guard 离线执行返回 `result_row_count=1`、`result_column_count=2`；后端、评测器编译通过。线上重启后需复测 q159，确认 payload 和新汇总字段可见。
- 补充：对“列出/哪些”问题的宽投影增加非阻断告警，不擅自删列；产品可据此让用户确认详情级别，评测则用 `result_shape_match` 单独量化列形状偏差。
- 图表稳定性：当模型漏填或填成默认 Table，而用户明确提出比较、趋势、占比且结果至少两行时，解析器按通用意图自动选择条形图、折线图或饼图；显式模型图表类型不覆盖。新增 3 个意图回退单元测试。
- 评测可重复性：评测器新增可重复的 `--db-id` 过滤参数，支持先对单库做快速回归，再运行完整公开 manifest；不改变题目、SQL 或准确率口径。

### 2026-08-27：新增字段线上验收与 financial 回归

- 服务重启后真实 payload 已包含 `result_column_count`、投影宽度告警和 `analysis_report`。
- 使用同一公开 BIRD Mini-Dev manifest 的 financial 5 题回归，模型仍为 `deepseek-v4-flash`、temperature=0、单题 90 秒：SQL 转换/执行率 60%，严格结果正确率 40%，结果形状匹配率 40%，超时率 20%，平均延迟 28.764s（含超时），Schema fallback 0%，Schema 向量检索为空率 100%，本批 provider usage/成本可用率 0%。产物：`financial_v4_latest_eval.json`。
- 逐题：q92 正确、q93 通过语义值规范化后正确；q159 执行成功但投影 8 列导致形状不匹配；q112 无 SQL；q89 超时无 SQL。结论：Schema/语义修复有效，当前主要瓶颈转为模型生成稳定性和查询投影意图，不能把 5 题结果外推为完整 BIRD 准确率。
- 图表线上验收：对 financial 发起“按 gender 比较客户数量并显示条形图”的通用问题，真实响应包含 SQL 且返回 `response_bar_chart`，未出现错误标记；图表回退链路可用，但仍需在完整公开集上统计图表类型覆盖率。

### 2026-08-27：v4 全部 55 题可重复回归

- 运行：同一公开 manifest、`deepseek-v4-flash`、temperature=0、复用数据库注册、跳过 refresh、单题 60 秒并启用 checkpoint。
- 结果：SQL 转换/执行率 76.36%，严格结果正确率 36.36%，结果形状匹配率 61.82%，超时率 1.82%，平均延迟 9.90s，P50 6.68s，P95 26.58s，平均模型生成 6.46s，平均 SQL 执行 0.147s。
- Schema：最终 fallback 0%，向量检索为空率 100%，本地完整 Schema 使用率 14.29%；两项分别表示最终可用性和索引健康度，不能合并解读。
- 成本：provider usage 和可计费成本可用率均为 0%；仅记录估算输出 token 平均 4,754，不作为账单。
- 旧 v4 55 题基线为转换 87.27%、正确 34.55%、平均 7.29s；新结果见 `bird_v4_55_latest_comparison.md`。由于超时预算不同（60s vs 180s）且模型服务存在波动，只有正确率的 +1.82 个百分点可作方向性参考，转换率和延迟不能作为严格 A/B 结论。

### 2026-08-27：v5 混合 Schema 召回与语义中间表示

- 修改：向量 Schema 候选不足时，保留向量排序并用表名/列名关键词补齐 top-k，避免空索引直接扩大为无关全表上下文；新增 `schema_hybrid_used`、`schema_local_selection_used`、`schema_hybrid_added_count` 指标。
- 修改：语义层增加 datasource-neutral 的 `semantic_intent` 中间表示，统一记录问题、指标、字段、已解析过滤和歧义；通过 payload 传递给报告和前端，不改变旧 `semantic_decision` 契约。
- 限制：当前数据库的向量检索为空率仍需通过索引 refresh/embedding 配置解决；混合召回是稳定兜底，不等于向量索引已经健康。

### 2026-08-27：v6 SQL 两阶段校验与低风险空结果重试

- 修改：`SqlGuard.review()` 固化“结构/Schema 校验 → 样本值与自然语言意图校验”的两阶段顺序，保留原有 `validate*` 兼容接口。
- 修改：当非聚合查询返回空结果，且值目录能够给出明确的大小写规范化时，执行最多一次低风险重试；聚合查询不会因 0 结果被盲目改写。
- 修改：结果追踪中保留重试告警、最终 SQL、行数和列数，便于区分模型错误与数据确实为空。
- 验证：离线模拟 `status='PAID'` 对应数据库值 `paid`，首次空结果后自动规范化重试成功；后端编译与既有 10 项应用测试通过。
- 限制：没有业务字典或样本值证据时不自动修改 SQL；复杂 JOIN、聚合口径仍需要模型重写或人工澄清。

### 2026-08-27：v7 结果缓存与路由安全边界

- 修改：新增 TTL/LRU、按用户 scope 隔离的 SQL 结果缓存，默认关闭；启用后仍先执行 SQL access policy，再读取/写入缓存。
- 修改：chat payload 的 timings 增加 `sql_cache_enabled` 和 `sql_cache_hit`，便于比较缓存命中对响应时间的影响。
- 验证：缓存 TTL/LRU、用户隔离和默认关闭行为的 2 项单元测试通过；不改变默认运行结果。
- 限制：缓存只适合明确允许缓存的读查询；对强实时或复杂行级权限数据源应保持关闭。

### 2026-08-27：v8 分组维度语义修正

- 发现：图表问题“按 gender 比较客户数量”被字段语义层误判为缺少 female/male 过滤值，直接进入澄清分支，导致合法 GROUP BY 查询不执行。
- 修改：语义决策区分“值过滤”和“分组维度”；出现 `by/group/per/按/分组` 等维度意图且没有具体映射值时返回 contextual，不阻断 SQL。
- 验证：新增维度语义单元测试；重启后的图表线上验收需确认返回 SQL、`response_bar_chart` 和 analysis report。
- 计划文档：新增 `docs/baseline/v5_v8_quality_plan.md`，固定阶段目标、指标门槛和不针对单题硬编码的执行规则。
- 补充验证：新增分组语义到条形图 payload 的解析器测试，确认 contextual 语义不会阻断合法 GROUP BY 查询，并同时生成 analysis report。

### 2026-08-27：v5–v8 最终线上验收

- 重启后确认真实 payload 已加载 `schema_hybrid_used`、`schema_local_selection_used`、`schema_hybrid_added_count`、`semantic_intent`、`result_column_count` 和缓存观测字段。
- 图表：通用问题“按 gender 比较客户数量并显示条形图”返回 chart-view、SQL、`response_bar_chart` 和 `analysis_report`，未触发错误澄清。
- 多轮：复用同一 `conv_uid` 连续提出“列出 North Bohemia 客户”与“其中有多少男性”，两轮均返回 SQL，第二轮返回 chart-view 且无错误。
- 缓存：默认关闭的线上 timing 字段已出现；启用缓存需显式设置 `DBGPT_SQL_RESULT_CACHE=true`，离线 TTL/LRU 和用户 scope 隔离测试通过，未在默认服务中改变数据新鲜度策略。
- 限制：当前 DeepSeek 网关仍返回空 usage；token 仅估算，成本保持 null。完整 55 题三次基线已完成，后续若修改模型或超时口径必须重新重复评测。

### 2026-08-27：v9 本地混合 Schema/语义检索

- 诊断：Chroma collection 和 embedding 数据存在，但线上 `schema_retrieval_empty=1`；原请求主要依赖全表/关键词兜底，缺少稳定的召回分数和索引版本。
- 修改：新增 `SchemaHybridRetriever`，用词法重合 + 256 维确定性 hashing-vector cosine 建立 D 盘版本化索引；保留 Chroma 候选并补齐本地候选，异常时继续旧 fallback。
- 修改：新增 `build_schema_semantic_documents.py`，只读生成 table/column/relationship/sample-value 及已配置 metric/semantic-field 文档；BIRD Mini-Dev 11 库、75 表、984 文档已生成。
- 验证：v9 统一公开 22 题评测 SQL 转化/执行率 95.45%，严格结果正确率 40.91%，形状匹配率 68.18%，平均 Schema 0.200s，本地检索 0.0126s，索引缓存命中率 47.62%。
- 对照：相同 manifest 的历史 v4 严格结果为转化 86.36%、正确 36.36%；完整对比见 `bird_v9_55_comparison.md`。v8 关闭混合召回的同预算控制组仍需补跑，不能将历史 v4 数值直接称为 v8。

### 2026-08-27：v8 / v9 严格 A/B 完成

- v8 控制组：关闭 `DBGPT_SCHEMA_HYBRID`，22 题 SQL 转化/执行率 86.36%、严格正确率 36.36%、形状匹配率 59.09%、平均延迟 6.16s。
- v9 实验组：开启本地混合召回，转化/执行率 95.45%、严格正确率 40.91%、形状匹配率 68.18%、平均延迟 6.97s。
- 变化：转化/执行 +9.09pp，严格正确 +4.55pp，形状匹配 +9.09pp；召回使用率从 0% 提升至 100%，缓存命中率 47.62%。
- 回归样本：`european_football_2#1035` 生成 `LIMIT 50` 导致完整列表被截断，记录为结果完整性/安全行数策略问题；不是 Schema 召回错误。
- 报告：`bird_v8_v9_final_comparison.md`；v9 结束后需恢复 `-SchemaHybrid true` 才能继续使用最新版服务。

### 2026-08-27：v9 最终线上验收

- 恢复 v9 后，Financial 分组问题连续两轮均返回正确 GROUP BY SQL；`schema_index_version=v9`、`schema_local_hybrid_used=1`、缓存命中 `1`，第二轮本地检索耗时 0.003s。
- v8 控制组已验证原有 fallback 可用；线上 payload 的 timings、semantic_intent、结果行列数和 analysis_report 字段均满足前端 Diagnostics/报告组件契约。
- v9 目标完成；后续质量工作聚焦“无显式条数要求时的 LIMIT 截断”与模型 SQL 业务口径，不再继续堆叠 Schema 召回规则。
