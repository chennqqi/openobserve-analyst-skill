# openobserve-analyst-skill

English Version: [README_EN.md](https://github.com/chennqqi/openobserve-analyst-skill/blob/main/README_EN.md)

中文版: [README.md](https://github.com/chennqqi/openobserve-analyst-skill/blob/main/README.md)

An analysis-oriented Skill for **OpenObserve**, designed to interact with the OpenObserve observability platform through APIs and provide an Agent with the following capabilities:

- Log querying and error investigation
- Metrics querying and trend analysis
- Distributed trace lookup and slow request diagnosis
- Alert rule inspection
- Secondary analysis based on query results

This project is suitable as a capability extension for an Agent / Assistant so it can perform observability analysis tasks around OpenObserve.

## Project Positioning

This project is not a full web service. It is a Skill project that uses `SKILL.md` as the instruction entry point and Python scripts as the actual execution layer.

Specifically:

- `SKILL.md`: defines the purpose of the Skill, task decision flow, and recommended execution patterns
- `scripts/oo_client.py`: calls OpenObserve APIs
- `scripts/oo_analyze.py`: performs pattern extraction, TopK aggregation, and timeline analysis on log query results
- `references/api_reference.md`: provides a quick OpenObserve API reference

## Core Capabilities

### 1. Logs

Supports log-related analysis:

- List log streams
- View stream schema
- Fetch latest logs
- Search error / warning related logs
- Execute custom SQL queries
- Summarize log levels

### 2. Metrics

Supports PromQL queries through the OpenObserve Prometheus-compatible API:

- Instant query
- Range query
- Metric name lookup

### 3. Traces

Supports distributed tracing analysis:

- Get recent traces
- Query all spans for a specific trace
- Filter traces by service, duration, and error status

### 4. Alerts

Supports listing alert definitions in OpenObserve.

### 5. Query Result Analysis

Performs secondary analysis on log query results:

- Log pattern extraction
- Group-by field counting
- Timeline bucket analysis

## Project Structure

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
└─ scripts/
   ├─ oo_analyze.py
   └─ oo_client.py
```

## Requirements

### Python

The scripts run on Python 3 and currently use only the Python standard library, with no extra third-party dependencies.

Recommended version:

- Python 3.9+

### OpenObserve Credentials

Before running any script, configure the following environment variables:

| Variable | Description | Example |
|------|------|------|
| `OO_BASE_URL` | OpenObserve service URL | `http://localhost:5080` |
| `OO_ORG` | Organization name | `default` |
| `OO_USER` | Username | `root@example.com` |
| `OO_PASSWORD` | Password | `Complexpass#123` |

You can also put these variables in `scripts/.env` or a project-root `.env` (existing environment variables take precedence). Optional: `OO_TZ` (default UTC), `OO_TIMEOUT` (default 60 seconds).

PowerShell example:

```powershell
$env:OO_BASE_URL="http://localhost:5080"
$env:OO_ORG="default"
$env:OO_USER="your-email@example.com"
$env:OO_PASSWORD="your-password"
```

## Quick Start

### 1. List log streams

```powershell
python scripts/oo_client.py streams --type logs
```

### 2. View the schema of a stream

```powershell
python scripts/oo_client.py schema my_stream
```

### 3. View recent logs

```powershell
python scripts/oo_client.py tail my_stream -n 50 --since 30m
```

### 4. View error logs

```powershell
python scripts/oo_client.py errors my_stream --since 2h --size 100
```

### 5. Execute a custom SQL query for logs

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\" WHERE match_all('timeout')" --since 1h
```

On PowerShell, `--sql` with outer single quotes is more reliable:

```powershell
python scripts/oo_client.py search --sql 'SELECT * FROM "mystream" WHERE match_all(''timeout'')' --since 1h
```

### 6. Query metrics

```powershell
python scripts/oo_client.py metrics-query "avg(rate(process_cpu_seconds_total[5m]))"
```

### 7. View metric trends

```powershell
python scripts/oo_client.py metrics-range "container_memory_usage_bytes" --since 1h --step 60
```

### 8. Get recent traces

```powershell
python scripts/oo_client.py traces-latest --since 30m --size 20
```

### 9. Query slow traces

```powershell
python scripts/oo_client.py traces-search --service order-service --min-duration-ms 200 --since 2h
```

### 10. List alert rules

```powershell
python scripts/oo_client.py alerts-list
```

### 11. Fetch logs around a timestamp

```powershell
python scripts/oo_client.py around my_stream --at 2024-01-01T12:00:00Z --size 10
```

### 12. List distinct field values

```powershell
python scripts/oo_client.py values my_stream --fields level,service --since 1h
```

### 13. Time histogram

```powershell
python scripts/oo_client.py histogram my_stream --interval 5m --since 1h
```

## Secondary Log Analysis

`oo_analyze.py` reads JSON Lines produced by `oo_client.py search` from standard input and performs further analysis.

### Pattern extraction

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py patterns --top 20
```

### Field TopK statistics

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 1h --size 500 | python scripts/oo_analyze.py topk service -k 10
```

### Timeline analysis

```powershell
python scripts/oo_client.py search "SELECT * FROM \"mystream\"" --since 6h --size 1000 | python scripts/oo_analyze.py timeline --bucket-minutes 10
```

## Main Commands

### `scripts/oo_client.py`

The commands are grouped by capability:

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

Show help directly:

```powershell
python scripts/oo_client.py -h
```

### `scripts/oo_analyze.py`

Supported analysis commands:

- `patterns`
- `topk`
- `timeline`

Show help directly:

```powershell
python scripts/oo_analyze.py -h
```

## Typical Use Cases

### Scenario 1: Investigate error logs in the last hour

```powershell
python scripts/oo_client.py errors app_logs --since 1h --size 100
```

### Scenario 2: Check whether a specific error bursts over time

```powershell
python scripts/oo_client.py search "SELECT * FROM \"app_logs\" WHERE match_all('timeout')" --since 6h --size 1000 | python scripts/oo_analyze.py timeline --bucket-minutes 10
```

### Scenario 3: View current request rate per service

```powershell
python scripts/oo_client.py metrics-query "sum by (service) (rate(http_requests_total[1m]))"
```

### Scenario 4: Diagnose slow requests

```powershell
python scripts/oo_client.py traces-search --since 1h --min-duration-ms 500
```

### Scenario 5: Inspect logs around a given timestamp

```powershell
python scripts/oo_client.py around app_logs --at 2024-01-01T12:00:00Z --size 10
```

## Development Notes

### Skill Entry

If you use this project from the perspective of an Agent Skill, read the following first:

- `SKILL.md`

That file defines:

- applicable scenarios
- prerequisite environment variables
- the task decision tree for Logs / Metrics / Traces / Alerts
- recommended command templates
- report output conventions

### API Reference

If you want to extend the scripts or add new capabilities, continue with:

- `references/api_reference.md`

It includes:

- Search API
- Stream / Schema API
- Prometheus-compatible query APIs
- Trace query APIs
- Alerts APIs
- time parameter notes

## Notes

- All requests rely on OpenObserve HTTP Basic Auth.
- Log and trace queries should always limit the time range reasonably to avoid scanning too much data.
- `--since` supports formats such as `15m`, `1h`, and `2d`.
- Before piping log data into `oo_analyze.py`, it is recommended to narrow down the dataset with SQL first.
- For log queries, avoid setting `--size` too large. Use pagination for larger datasets.
- Stream names containing special characters should be wrapped in double quotes.
- On PowerShell, prefer `--sql 'SELECT * FROM "mystream" LIMIT 20'`.
- `search` defaults to jsonl so it can pipe into `oo_analyze.py`; use `--format compact` when an Agent is reading samples.
- `--until` accepts relative or absolute time; when omitted, the end time is now.

## Possible Future Extensions

- Add more analysis subcommands such as anomaly clustering, field distribution, and error code statistics
- Add richer output formats such as Markdown reports or structured JSON
- Add automated tests for the scripts
- Add sample data and demo screenshots

## License

This project uses the license declared in the repository `LICENSE` file.
