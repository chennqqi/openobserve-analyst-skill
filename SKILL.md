---
name: openobserve-analyst
description: 通过 API 与 OpenObserve 可观测性平台交互，使 Agent 具备调用 OpenObserve 进行日志分析（Logs）、指标查询（Metrics）、分布式追踪分析（Traces）和告警查看（Alerts）的能力。当用户需要查询日志、分析错误、排查系统问题、查看指标趋势或与 OpenObserve 交互时使用。
---

# OpenObserve 全栈可观测性分析 Skill

本 Skill 覆盖 OpenObserve 三大核心支柱：**Logs（日志）**、**Metrics（指标）**、**Traces（追踪）**，以及 **Alerts（告警）**。

脚本目录：`scripts/`  
API 参考：`references/api_reference.md`

---

## 第一步：确认环境变量

**执行任何命令前，先确认用户已配置以下变量：**

| 变量 | 说明 | 示例 |
|------|------|------|
| `OO_BASE_URL` | 服务地址 | `http://localhost:5080` |
| `OO_ORG` | 组织名（默认 `default`） | `default` |
| `OO_USER` | 用户名 | `root@example.com` |
| `OO_PASSWORD` | 密码 | `Complexpass#123` |

脚本会自动加载 `scripts/.env` 或项目根目录 `.env`（已存在的环境变量优先）。

**未设置时提示用户执行（PowerShell）：**
```powershell
$env:OO_BASE_URL="http://localhost:5080"
$env:OO_ORG="default"
$env:OO_USER="your-email@example.com"
$env:OO_PASSWORD="your-password"
```

---

## 任务决策树

```
用户需求 → 判断数据类型：

  LOGS（日志）
  ├─ "查看/搜索日志"         → search / tail
  ├─ "有没有报错/异常"       → errors
  ├─ "日志量统计"            → summary
  ├─ "有什么常见问题/模式"   → search | oo_analyze.py patterns
  ├─ "日志趋势分布"          → search | oo_analyze.py timeline
  ├─ "有哪些数据流/字段"     → streams / schema
  ├─ "某时刻附近的日志"      → around
  ├─ "字段有哪些取值"        → values
  └─ "按时间分桶统计"        → histogram

  METRICS（指标）
  ├─ "当前 XX 指标是多少"    → metrics-query
  ├─ "XX 指标最近趋势"       → metrics-range
  └─ "有哪些指标"            → metrics-list

  TRACES（追踪）
  ├─ "最近有哪些请求/trace"  → traces-latest
  ├─ "某个 trace 的详情"     → traces-get <trace_id>
  ├─ "哪些请求耗时长/报错"   → traces-search --min-duration-ms / --errors-only
  └─ "某服务的 trace"        → traces-search --service <name>

  ALERTS（告警）
  └─ "看看有哪些告警规则"    → alerts-list
```

---

## LOGS — 日志分析

### 浏览数据流
```bash
# 列出所有日志流
python scripts/oo_client.py streams --type logs

# 查看字段结构
python scripts/oo_client.py schema <stream_name>
```

### 查看日志
```bash
# 最新 50 条
python scripts/oo_client.py tail <stream_name> -n 50 --since 30m

# 错误日志（最近 2 小时）
python scripts/oo_client.py errors <stream_name> --since 2h --size 100

# 错误 + 警告
python scripts/oo_client.py errors <stream_name> --level warn --since 1h

# 日志统计摘要
python scripts/oo_client.py summary <stream_name> --since 24h
```

### 自定义 SQL 查询
```bash
# 全文搜索
python scripts/oo_client.py search "SELECT * FROM \"mystream\" WHERE match_all('timeout')" --since 1h

# 关键词 + 字段过滤
python scripts/oo_client.py search "SELECT * FROM \"mystream\" WHERE match_all('OOM') AND namespace='prod'" --since 6h --size 100

# 按级别统计
python scripts/oo_client.py search "SELECT level, COUNT(*) AS cnt FROM \"mystream\" GROUP BY level ORDER BY cnt DESC" --since 24h

# PowerShell：用 --sql 和外层单引号，避免 \" 被吞掉
python scripts/oo_client.py search --sql 'SELECT * FROM "mystream" LIMIT 20' --since 1h
```

### 按时间点 / 字段取值 / 分桶
```bash
# 某条日志前后文
python scripts/oo_client.py around <stream_name> --at 2024-01-01T12:00:00Z --size 10

# 字段去重取值
python scripts/oo_client.py values <stream_name> --fields level,service --since 1h

# 按时间分桶计数
python scripts/oo_client.py histogram <stream_name> --interval 5m --since 1h
```

### 深度分析（管道）
```bash
# 提取日志模式（归一化去重）
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py patterns --top 20

# 按字段分组排名
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py topk service -k 10

# 时序分布（每 10 分钟）
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 6h --size 1000 | python scripts/oo_analyze.py timeline --bucket-minutes 10
```

---

## METRICS — 指标查询

OpenObserve 兼容 Prometheus API（PromQL）。

```bash
# 即时查询：当前 CPU 使用率
python scripts/oo_client.py metrics-query "avg(rate(process_cpu_seconds_total[5m]))"

# 范围查询：内存使用趋势（最近 1 小时，每 60s 一个点）
python scripts/oo_client.py metrics-range "container_memory_usage_bytes" --since 1h --step 60

# 列出所有指标名（模糊过滤）
python scripts/oo_client.py metrics-list --filter http
```

**PromQL 速查：**
```
# HTTP 请求速率
rate(http_requests_total[5m])

# P99 延迟
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# 服务 QPS
sum by (service) (rate(http_requests_total[1m]))

# 错误率
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
```

---

## TRACES — 分布式追踪

```bash
# 最近 20 个 trace（默认流 default）
python scripts/oo_client.py traces-latest --since 30m --size 20

# 指定服务的 trace
python scripts/oo_client.py traces-latest mystream --filter "service_name:api-gateway"

# 查看某个 trace 的所有 span
python scripts/oo_client.py traces-get abc123def456... --since 2h

# 搜索耗时 > 500ms 的请求
python scripts/oo_client.py traces-search --since 1h --min-duration-ms 500

# 只看报错 trace
python scripts/oo_client.py traces-search --since 1h --errors-only

# 指定服务的慢请求
python scripts/oo_client.py traces-search --service order-service --min-duration-ms 200 --since 2h
```

---

## ALERTS — 告警规则

```bash
# 列出所有告警定义
python scripts/oo_client.py alerts-list
```

---

## 分析报告输出规范

完成分析后，按以下结构汇报：

```
# [分析标题]（数据类型 | 时间范围 | Stream/服务）

## 概要
[数据量、时间范围、主要发现一句话总结]

## 关键发现
- 发现1（附数量/百分比）
- 发现2（附数量/百分比）

## 异常 / 错误摘要
[错误类型、频次、首末出现时间]

## 趋势
[量级变化、高峰时段、异常突增点]

## 建议
1. 具体可操作建议
2. 需要进一步排查的方向
```

---

## 注意事项

1. **时间范围必须指定**，避免全量扫描。`--since` 支持 `15m` / `1h` / `2d`。
2. **Stream 名含特殊字符时加双引号**，如 `"my-stream"`。
3. **Metrics 使用 Prometheus 兼容端点**：`/api/{org}/prometheus/api/v1/...`
4. **Traces 的 `traces-get` 使用 `size=-1`** 拉取全部 span。
5. **管道分析先过滤**：缩小数据集后再管道给 `oo_analyze.py`。
6. **`--size` 建议 ≤ 500**；更多数据用 `--offset` 分页。
7. **PowerShell 查询用 `--sql` + 外层单引号**，例如 `--sql 'SELECT * FROM "mystream" LIMIT 20'`，不要写 `\"`。
8. **Agent 阅读日志可用 `--format compact`**；管道给 `oo_analyze.py` 时保持默认 `jsonl`。
9. **`--until` 支持 `15m` / `1h` / `2d` 或绝对时间**；未指定时截止到当前。
