# openobserve-analyst-skill
 
 中文版: [README.md](https://github.com/chennqqi/openobserve-analyst-skill/blob/main/README.md)

 English Version: [README_EN.md](https://github.com/chennqqi/openobserve-analyst-skill/blob/main/README_EN.md)

一个面向 **OpenObserve** 的分析型 Skill，用于通过 API 与 OpenObserve 可观测性平台交互，让 Agent 具备以下能力：

- 日志查询与错误排查
- 指标查询与趋势分析
- 分布式追踪检索与定位慢请求
- 告警规则查看
- 基于查询结果的二次分析

本项目适合作为 Agent / Assistant 的能力扩展，使其能够围绕 OpenObserve 执行可观测性分析任务。

## 项目定位

本项目不是一个完整的 Web 服务，而是一个以 `SKILL.md` 为入口说明、以 Python 脚本为实际执行载体的 Skill 项目。

其中：

- `SKILL.md`：定义 Skill 的用途、任务决策方式和推荐执行流程
- `scripts/oo_client.py`：负责调用 OpenObserve API
- `scripts/oo_analyze.py`：负责对日志查询结果做模式提取、TopK 统计、时间线分析
- `references/api_reference.md`：提供 OpenObserve API 快速参考

## 核心能力

### 1. Logs

支持日志相关分析：

- 列出日志流
- 查看 Stream Schema
- 拉取最新日志
- 检索错误 / 告警相关日志
- 执行自定义 SQL 查询
- 汇总日志级别统计

### 2. Metrics

支持通过 OpenObserve 的 Prometheus 兼容接口执行 PromQL 查询：

- 即时查询
- 范围查询
- 指标名检索

### 3. Traces

支持分布式追踪分析：

- 获取最近 Trace
- 查询指定 Trace 的全部 Span
- 按服务、耗时、错误状态筛选 Trace

### 4. Alerts

支持查看 OpenObserve 中的告警规则定义。

### 5. Query Result Analysis

对日志查询结果进行二次分析：

- 日志模式归纳
- 按字段分组计数
- 时间线分桶统计

## 项目结构

```text
.
├─ SKILL.md
├─ README.md
├─ README_EN.md
├─ LICENSE
├─ assets/
├─ doc/
│  ├─ requirements.md
│  └─ requirements-analysis.md
├─ references/
│  └─ api_reference.md
├─ tests/
│  └─ test_cli_unit.py
└─ scripts/
   ├─ oo_analyze.py
   └─ oo_client.py
```

## 运行要求

### Python

项目脚本基于 Python 3 运行，当前代码仅使用 Python 标准库，不依赖额外第三方包。

建议版本：

- Python 3.9+

### OpenObserve 访问凭据

在执行任何脚本前，请先配置以下环境变量：

| 变量名 | 说明 | 示例 |
|------|------|------|
| `OO_BASE_URL` | OpenObserve 服务地址 | `http://localhost:5080` |
| `OO_ORG` | 组织名 | `default` |
| `OO_USER` | 用户名 | `root@example.com` |
| `OO_PASSWORD` | 密码 | `Complexpass#123` |

也可将以上变量写入 `scripts/.env` 或项目根目录 `.env`（已存在的环境变量优先）。可选：`OO_TZ`（默认 UTC）、`OO_TIMEOUT`（默认 60 秒）。

PowerShell 示例：

```powershell
$env:OO_BASE_URL="http://localhost:5080"
$env:OO_ORG="default"
$env:OO_USER="your-email@example.com"
$env:OO_PASSWORD="your-password"
```

## 快速开始

### 1. 查看日志流

```powershell
python scripts/oo_client.py streams --type logs
```

### 2. 查看某个日志流的字段结构

```powershell
python scripts/oo_client.py schema my_stream
```

### 3. 查看最近日志

```powershell
python scripts/oo_client.py tail my_stream -n 50 --since 30m
```

### 4. 查看错误日志

```powershell
python scripts/oo_client.py errors my_stream --since 2h --size 100
```

### 5. 执行自定义日志 SQL

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\" WHERE match_all('timeout')" --since 1h
```

PowerShell 下更稳妥的写法是 `--sql` 加外层单引号：

```powershell
python scripts/oo_client.py search --sql 'SELECT * FROM "mystream" WHERE match_all(''timeout'')' --since 1h
```

### 6. 查询指标

```powershell
python scripts/oo_client.py metrics-query "avg(rate(process_cpu_seconds_total[5m]))"
```

### 7. 查看指标趋势

```powershell
python scripts/oo_client.py metrics-range "container_memory_usage_bytes" --since 1h --step 60
```

### 8. 获取最近 Trace

```powershell
python scripts/oo_client.py traces-latest --since 30m --size 20
```

### 9. 查询慢请求 Trace

```powershell
python scripts/oo_client.py traces-search --service order-service --min-duration-ms 200 --since 2h
```

### 10. 查看告警规则

```powershell
python scripts/oo_client.py alerts-list
```

### 11. 查看某时刻附近的日志

```powershell
python scripts/oo_client.py around my_stream --at 2024-01-01T12:00:00Z --size 10
```

### 12. 查看字段取值

```powershell
python scripts/oo_client.py values my_stream --fields level,service --since 1h
```

### 13. 按时间分桶统计

```powershell
python scripts/oo_client.py histogram my_stream --interval 5m --since 1h
```

## 日志二次分析

`oo_analyze.py` 从标准输入读取 `oo_client.py search` 输出的 JSON Lines 结果，并进行进一步分析。

### 模式提取

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py patterns --top 20
```

### 字段 TopK 统计

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py topk service -k 10
```

### 时间线分析

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 6h --size 1000 | python scripts/oo_analyze.py timeline --bucket-minutes 10
```

## 主要命令说明

### `scripts/oo_client.py`

按能力分为以下命令组：

- Logs
  - `search`
  - `streams`
  - `schema`
  - `tail`
  - `errors`
  - `summary`
  - `around`
  - `values`
  - `histogram`
- Metrics
  - `metrics-query`
  - `metrics-range`
  - `metrics-list`
- Traces
  - `traces-latest`
  - `traces-get`
  - `traces-search`
- Alerts
  - `alerts-list`

可直接查看帮助：

```powershell
python scripts/oo_client.py -h
```

### `scripts/oo_analyze.py`

支持以下分析命令：

- `patterns`
- `topk`
- `timeline`

可直接查看帮助：

```powershell
python scripts/oo_analyze.py -h
```

## 典型使用场景

### 场景 1：排查最近 1 小时错误日志

```powershell
python scripts/oo_client.py errors app_logs --since 1h --size 100
```

### 场景 2：分析某类错误是否集中爆发

```powershell
python scripts/oo_client.py search "SELECT * FROM \"app_logs\" WHERE match_all('timeout')" --since 6h --size 1000 | python scripts/oo_analyze.py timeline --bucket-minutes 10
```

### 场景 3：查看服务当前请求速率

```powershell
python scripts/oo_client.py metrics-query "sum by (service) (rate(http_requests_total[1m]))"
```

### 场景 4：定位慢请求

```powershell
python scripts/oo_client.py traces-search --since 1h --min-duration-ms 500
```

### 场景 5：查看某条日志前后文

```powershell
python scripts/oo_client.py around app_logs --at 2024-01-01T12:00:00Z --size 10
```

## 开发说明

### Skill 入口

如果你是从 Agent Skill 的角度使用本项目，建议优先阅读：

- `SKILL.md`

该文件定义了：

- 适用场景
- 环境变量前置要求
- 面向 Logs / Metrics / Traces / Alerts 的任务决策树
- 推荐命令模板
- 输出报告规范

### API 参考

如果你需要补充或扩展脚本能力，建议继续阅读：

- `references/api_reference.md`

其中包含：

- Search API
- Stream / Schema API
- Prometheus 兼容查询接口
- Trace 查询接口
- Alerts 接口
- 时间参数说明

## 注意事项

- 所有请求均依赖 OpenObserve HTTP Basic Auth。
- 日志与 Trace 查询必须合理限定时间范围，避免全量扫描。
- `--since` 支持 `15m`、`1h`、`2d` 这类格式。
- 对日志进行管道分析前，建议先通过 SQL 缩小数据范围。
- 对于日志查询，`--size` 不宜设置过大；更大数据量建议分页获取。
- 含特殊字符的 Stream 名建议使用双引号。
- PowerShell 执行 SQL 时建议使用 `--sql 'SELECT * FROM "mystream" LIMIT 20'`。
- `search` 默认输出 jsonl，可与 `oo_analyze.py` 管道衔接；阅读样本时可加 `--format compact`。
- `--until` 支持相对时间或绝对时间，未指定时截止到当前。

## 后续可扩展方向

- 增加更多分析子命令，例如异常聚类、字段分布、错误码统计
- 增加更丰富的输出格式，例如 Markdown 报告或结构化 JSON
- 为脚本补充自动化测试
- 增加示例数据与演示截图

## License

本项目使用仓库内 `LICENSE` 文件所声明的许可证。
