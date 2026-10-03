# DB-GPT V2 校验报告

生成时间：2026-08-21 19:51:58
模型：`deepseek-v4-flash`；数据源：`Walmart_Sales`；服务：`http://127.0.0.1:5670`

## 1. 校验范围

- 服务健康检查：通过，`/api/health` 返回 `status=ok`。
- 模型检查：通过，模型列表包含 `deepseek-v4-flash`。
- 端到端回归：B01-B07，与 V0/V1 使用同一问题集。
- 通用能力专项：数据源指标配置、SQL Guard、SQL 纠错和执行 Trace。

## 2. V0/V1/V2 端到端对比

| 版本 | SQL 转化率 | 执行成功率 | 结果正确率 | 平均耗时 | 中位耗时 |
|---|---:|---:|---:|---:|---:|
| V0 原版 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 14.10s | 13.90s |
| V1 指标/Guard 版 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 17.80s | 17.00s |
| V2 首轮实测 | 6/7 = 85.7% | 6/7 = 85.7% | 6/7 = 85.7% | 19.05s | 15.33s |
| V2 B02 重试后 | 7/7 = 100.0% | 7/7 = 100.0% | 7/7 = 100.0% | 19.80s | 15.33s |

V2 首轮 B02 没有返回可解析的 SQL/data；针对该题重试后成功生成 `SUM(Weekly_Sales)` 查询并返回正确结果。因此应同时关注首轮稳定性和重试恢复能力，不能只报告重试后的 100%。

## 3. V2 各题结果

| 编号 | 首轮 | 重试/最终 | 耗时（秒） | 结果 |
|---|---|---|---:|---|
| B01 | 通过 | 通过 | 8.35 | SELECT COUNT(*) AS row_count FROM walmart_sales; |
| B02 | 失败 | 通过（重试恢复） | 12.26 | SELECT SUM(Weekly_Sales) AS Total_Weekly_Sales FROM walmart_sales; |
| B03 | 通过 | 通过 | 15.33 | SELECT AVG(Weekly_Sales) AS average_weekly_sales FROM walmart_sales; |
| B04 | 通过 | 通过 | 38.69 | SELECT COUNT(DISTINCT Store) AS store_count FROM walmart_sales; |
| B05 | 通过 | 通过 | 18.14 | SELECT Store, SUM(Weekly_Sales) AS Total_Weekly_Sales FROM walmart_sales GROUP BY Store ORDER BY Total_Weekly_Sales DESC LIMIT 1; |
| B06 | 通过 | 通过 | 37.17 | SELECT CASE WHEN Holiday_Flag = 1 THEN 'Holiday' ELSE 'Non-holiday' END AS period_type, SUM(Weekly_Sales) AS total_weekly_sales FROM walmart_sales GROUP BY CASE WHEN Holiday_Flag = 1 THEN 'Holiday' ELSE 'Non-holiday' END ORDER BY period_type; |
| B07 | 通过 | 通过 | 8.68 | SELECT MIN(Date) AS min_date, MAX(Date) AS max_date FROM walmart_sales; |

## 4. 通用改进能力专项

| 能力 | V0 | V2 |
|---|---:|---:|
| 按数据源指标配置加载与匹配 | 0/4 | 4/4 |
| 危险 SQL 预执行拦截 | 0/3 | 3/3 |
| SQL 执行失败纠错 | 0/3 | 3/3 |
| SQL 执行 Trace | 0/1 | 1/1 |

## 5. 结论

1. V2 重启后已正确加载数据源配置框架，Walmart 配置和通用 orders/marketing_events 配置均可读取。
2. V2 通用专项能力全部通过，说明指标配置不再依赖单一 Walmart 代码路径。
3. V2 首轮端到端为 6/7，B02 经单题重试恢复；这次失败更像模型 SSE/结果解析瞬时波动，不是指标配置导致的 SQL 口径错误。
4. V2 平均耗时高于 V0/V1，下一步应增加请求级重试、SSE 空响应分类和耗时分解，避免把网络/模型波动混入 SQL 准确率。

## 6. 评测产物

- 首轮原始结果：`D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v2_endpoint_eval.json`
- B02 重试结果：`D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v2_B02_retry.json`
- 本报告：`D:\1ALL\DB-GPT\DB-GPT-main\docs\baseline\v2_validation_report.md`
