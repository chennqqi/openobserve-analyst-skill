# OpenObserve API Quick Reference

## Authentication
All requests require HTTP Basic Auth:
```
Authorization: Basic base64("username:password")
```

## Base URL Pattern
```
{OO_BASE_URL}/api/{organization}/...
```
Default organization: `default`

---

## LOGS — Search API

**POST** `/api/{org}/_search`

```json
{
  "query": {
    "sql": "SELECT * FROM \"stream_name\" WHERE ...",
    "start_time": 1674789786006000,
    "end_time":   1674789886006000,
    "from": 0,
    "size": 100
  }
}
```

- `start_time` / `end_time`: **microseconds** since Unix epoch
- `size`: use `-1` to return all (Traces only; use with caution on logs)
- `from`: pagination offset
- `timeout`: query timeout in seconds (CLI sends the HTTP timeout value)
- `agent_options.output_format`: `json` (default) | `csv` | `md_table`

**Response:**
```json
{ "total": 1234, "took": 42, "hits": [...] }
```

### SQL Patterns

```sql
-- Full-text search
SELECT * FROM "mystream" WHERE match_all('timeout')

-- Field filter
SELECT * FROM "mystream" WHERE level = 'error'

-- Count by level
SELECT level, COUNT(*) AS cnt FROM "mystream" GROUP BY level ORDER BY cnt DESC

-- Time histogram (5-min buckets)
SELECT histogram(_timestamp, '5 minute') AS ts, COUNT(*) AS cnt FROM "mystream" GROUP BY ts ORDER BY ts

-- Substring on field
SELECT * FROM "mystream" WHERE str_match(message, 'connection refused')

-- Regex match
SELECT * FROM "mystream" WHERE re_match(message, 'timeout.*retry')
```

### Built-in SQL Functions

| Function | Description |
|----------|-------------|
| `match_all('keyword')` | Full-text search (all fields) |
| `str_match(field, 'sub')` | Substring match on one field |
| `re_match(field, 'regex')` | Regex match on one field |
| `histogram(_timestamp, 'N minute')` | Time-bucketed aggregation |

---

## LOGS — Stream Management

**List streams**
```
GET /api/{org}/streams?type=logs&fetchSchema=true
```
- `type`: `logs` | `metrics` | `traces`

**Get schema**
```
GET /api/{org}/{stream}/schema
```

---

## LOGS — Around API

**GET** `/api/{org}/{stream}/_around`

Query parameters:

- `key`: `_timestamp` of the record to search around (microseconds)
- `size`: number of records to return

CLI: `python scripts/oo_client.py around <stream> --at <ts> --size 10`

---

## LOGS — Values API

**GET** `/api/{org}/{stream}/_values`

Query parameters:

- `fields`: comma-separated field names (required)
- `start_time` / `end_time`: time range (microseconds)
- `size`: number of values to return
- `keyword`: optional filter

CLI: `python scripts/oo_client.py values <stream> --fields level,service --since 1h`

---

## METRICS — Prometheus-Compatible API

Base path: `/api/{org}/prometheus/api/v1/`

**Instant query**
```
GET /api/{org}/prometheus/api/v1/query?query=<promql>&time=<unix_s>
```

**Range query**
```
GET /api/{org}/prometheus/api/v1/query_range?query=<promql>&start=<unix_s>&end=<unix_s>&step=<seconds>
```

**List metric names**
```
GET /api/{org}/prometheus/api/v1/label/__name__/values?start=<unix_s>&end=<unix_s>
```

**Remote Write endpoint** (for Prometheus scrape targets):
```
POST /api/{org}/prometheus/api/v1/write
```

### Common PromQL Expressions

```promql
# HTTP request rate (5m window)
rate(http_requests_total[5m])

# P99 latency
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# Error rate
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))

# CPU usage per pod
sum by (pod) (rate(container_cpu_usage_seconds_total[2m]))

# Memory usage
container_memory_usage_bytes{container!=""}
```

---

## TRACES — API

**List latest traces**
```
GET /api/{org}/{stream}/traces/latest
  ?start_time=<us>&end_time=<us>&from=0&size=20&filter=<expr>
```

- `filter` example: `service_name:api-gateway`
- Response: `.hits[]` with `trace_id`, `service_name`, `duration`, `start_time`, `spans_count`

**Get spans for a trace_id** (use Search API)
```json
POST /api/{org}/_search
{
  "query": {
    "sql": "SELECT * FROM \"default\" WHERE trace_id = '<id>' ORDER BY start_time",
    "start_time": ...,
    "end_time": ...,
    "from": 0,
    "size": -1
  }
}
```

### Span Fields

| Field | Description |
|-------|-------------|
| `trace_id` | Unique trace identifier |
| `span_id` | Individual span ID |
| `parent_span_id` | Parent span (null = root) |
| `operation_name` | Operation/endpoint name |
| `service_name` | Service that emitted span |
| `duration` | Duration in microseconds |
| `start_time` | Span start (microseconds) |
| `status_code` | `STATUS_CODE_OK` / `STATUS_CODE_ERROR` |

---

## ALERTS

**List alerts**
```
GET /api/{org}/alerts
```

---

## Time Conversion

```python
import time
from datetime import datetime, timezone

# Microseconds now
now_us = int(time.time() * 1_000_000)

# 1 hour ago (microseconds)
start_us = now_us - 1 * 3600 * 1_000_000

# From datetime (microseconds)
dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
us = int(dt.timestamp() * 1_000_000)

# Seconds now (for Prometheus API)
now_s = int(time.time())
start_s = now_s - 3600  # 1 hour ago
```

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200  | Success |
| 400  | Bad request / invalid SQL / invalid PromQL |
| 401  | Unauthorized |
| 404  | Stream or resource not found |
| 500  | Server error |
