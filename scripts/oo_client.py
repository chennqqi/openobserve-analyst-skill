#!/usr/bin/env python3
"""
OpenObserve API Client — Logs / Metrics / Traces / Alerts
Usage: python oo_client.py <command> [options]

LOGS Commands:
  search      Search logs with SQL query
  streams     List available streams (logs/metrics/traces)
  schema      Get stream schema
  tail        Get latest N log entries
  errors      Find error/warning logs
  summary     Summarize log counts by level
  around      Fetch logs around a timestamp
  values      List distinct field values
  histogram   Time-bucketed log counts

METRICS Commands:
  metrics-query       Instant PromQL query
  metrics-range       PromQL range query (time series)
  metrics-list        List metric names

TRACES Commands:
  traces-latest       List recent traces
  traces-get          Get all spans for a specific trace_id
  traces-search       Search traces by service / duration / status

ALERTS Commands:
  alerts-list         List all alert definitions

Environment variables (required):
  OO_BASE_URL   e.g. http://localhost:5080
  OO_ORG        organization name (default: default)
  OO_USER       username
  OO_PASSWORD   password

Optional:
  OO_TZ         timezone for naive timestamps (default: UTC)
  OO_TIMEOUT    HTTP timeout in seconds (default: 60)
"""

import os
import sys
import json
import re
import base64
import argparse
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote


# ---------------------------------------------------------------------------
# .env auto-loader (env vars still take precedence)
# Reads scripts/.env, then skill-root .env.
# ---------------------------------------------------------------------------

def _load_dotenv():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = None
    for cand in (script_dir, os.path.dirname(script_dir)):
        path = os.path.join(cand, ".env")
        if os.path.isfile(path):
            env_path = path
            break
    if not env_path:
        return
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REL_TIME = re.compile(r"^(\d+)([mhd])$")
_COMPACT_FIELDS = ("_timestamp", "level", "status", "event", "service", "message", "log", "msg")
_ERROR_BODY_LIMIT = 500
_MSG_FALLBACK_LIMIT = 500
_CELL_LIMIT = 80


def get_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def now_us() -> int:
    return int(time.time() * 1_000_000)


def now_s() -> int:
    return int(time.time())


def http_timeout() -> float:
    try:
        return float(os.environ.get("OO_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def configured_tz():
    name = os.environ.get("OO_TZ", "UTC")
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def parse_absolute_us(spec: str) -> int:
    """Parse an absolute timestamp into microseconds."""
    spec = spec.strip()
    if spec.isdigit():
        n = int(spec)
        if n >= 10**15:
            return n
        if n >= 10**12:
            return n * 1000
        return n * 1_000_000
    normalized = spec.replace("Z", "+00:00")
    dt = None
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(spec, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError(
            f"Invalid time spec '{spec}'. Use 15m/1h/2d or an absolute timestamp."
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=configured_tz())
    return int(dt.timestamp() * 1_000_000)


def parse_time_us(spec: str) -> int:
    """Relative (15m/1h/2d → now-offset) or absolute timestamp, in microseconds."""
    spec = spec.strip()
    match = _REL_TIME.match(spec)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        multipliers = {"m": 60, "h": 3600, "d": 86400}
        return now_us() - value * multipliers[unit] * 1_000_000
    return parse_absolute_us(spec)


def parse_time_offset_us(spec: str) -> int:
    """Return absolute start time in microseconds."""
    return parse_time_us(spec)


def parse_time_offset_s(spec: str) -> int:
    """Return absolute start time in seconds (for Prometheus-compat APIs)."""
    return parse_time_us(spec) // 1_000_000


def resolve_range_us(since: str, until: str = "") -> tuple:
    start_us = parse_time_us(since)
    end_us = parse_time_us(until) if until else now_us()
    if start_us >= end_us:
        print("[ERROR] --since must be earlier than --until / now.", file=sys.stderr)
        sys.exit(1)
    return start_us, end_us


def choose_sql(positional="", sql_flag="", sql_file_text=None, stdin_text=None) -> str:
    """Pick SQL from --sql-file, --sql, positional, or stdin. First non-empty wins."""
    if sql_file_text:
        return sql_file_text.strip()
    if sql_flag:
        return sql_flag.strip()
    if positional and positional != "-":
        return positional.strip()
    if positional == "-" or stdin_text:
        return (stdin_text or "").strip()
    return ""


def resolve_sql(args) -> str:
    file_text = None
    sql_file = getattr(args, "sql_file", "")
    if sql_file:
        try:
            with open(sql_file, "r", encoding="utf-8") as fh:
                file_text = fh.read()
        except OSError as exc:
            print(f"[ERROR] Cannot read --sql-file: {exc}", file=sys.stderr)
            sys.exit(1)
    stdin_text = None
    positional = getattr(args, "sql", "") or ""
    sql_flag = getattr(args, "sql_flag", "") or ""
    if not file_text and not sql_flag and (positional == "-" or (not positional and not sys.stdin.isatty())):
        stdin_text = sys.stdin.read()
    sql = choose_sql(positional, sql_flag, file_text, stdin_text)
    if not sql:
        print(
            "[ERROR] SQL is required. Use a positional statement, --sql, --sql-file, or stdin.",
            file=sys.stderr,
        )
        sys.exit(1)
    return sql


def truncate_error_body(body: str, limit: int = _ERROR_BODY_LIMIT) -> str:
    body = body.replace("\r", " ").replace("\n", " ")
    if len(body) > limit:
        return body[:limit] + "...(truncated)"
    return body


def histogram_interval_sql(spec: str) -> str:
    """Map 5m/1h/1d to OpenObserve histogram interval text."""
    spec = spec.strip()
    match = re.match(r"^(\d+)([smhd])$", spec)
    if not match:
        raise ValueError(f"Unknown histogram interval '{spec}'. Use e.g. 5m / 1h / 1d.")
    value, unit = match.group(1), match.group(2)
    names = {"s": "second", "m": "minute", "h": "hour", "d": "day"}
    return f"{int(value)} {names[unit]}"


def pick_log_message(hit: dict) -> str:
    for key in ("log", "message", "msg"):
        value = hit.get(key)
        if value:
            return str(value)
    dumped = json.dumps(hit, ensure_ascii=False)
    if len(dumped) > _MSG_FALLBACK_LIMIT:
        return dumped[:_MSG_FALLBACK_LIMIT] + "..."
    return dumped


def api_request(method: str, url: str, headers: dict, body: dict = None, fatal: bool = True):
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=http_timeout()) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        error_body = truncate_error_body(e.read().decode(errors="replace"))
        print(f"[ERROR] HTTP {e.code}: {error_body}", file=sys.stderr)
        if fatal:
            sys.exit(1)
        return {}
    except URLError as e:
        print(f"[ERROR] Connection failed: {e.reason}", file=sys.stderr)
        if fatal:
            sys.exit(1)
        return {}


def api_get(url: str, headers: dict, fatal: bool = True):
    return api_request("GET", url, headers, fatal=fatal)


def fmt_ts_us(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fmt_ts_s(ts_s: float) -> str:
    return datetime.fromtimestamp(float(ts_s), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _cell(hit: dict, key: str) -> str:
    if key == "_timestamp":
        ts = hit.get("_timestamp", 0)
        try:
            return fmt_ts_us(int(ts))
        except (TypeError, ValueError, OSError):
            return str(ts)
    value = hit.get(key, "")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > _CELL_LIMIT:
        return text[:_CELL_LIMIT] + "..."
    return text


def _csv_escape(text: str) -> str:
    if any(ch in text for ch in ',\"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def infer_compact_fields(hits: list) -> list:
    if not hits:
        return list(_COMPACT_FIELDS[:3])
    sample = hits[:10]
    fields = [name for name in _COMPACT_FIELDS if any(name in hit for hit in sample)]
    if not fields:
        fields = list(hits[0].keys())[:8]
    return fields


def format_hits(hits: list, fields: str = "", out_format: str = "jsonl"):
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    if out_format == "jsonl":
        for hit in hits:
            row = {k: hit.get(k, "") for k in field_list} if field_list else hit
            print(json.dumps(row, ensure_ascii=False))
        return
    if not hits:
        return
    if not field_list:
        field_list = infer_compact_fields(hits)
    if out_format == "csv":
        print(",".join(field_list))
        for hit in hits:
            print(",".join(_csv_escape(_cell(hit, k)) for k in field_list))
        return
    if out_format == "md":
        print("| " + " | ".join(field_list) + " |")
        print("| " + " | ".join("---" for _ in field_list) + " |")
        for hit in hits:
            print("| " + " | ".join(_cell(hit, k).replace("|", "\\|") for k in field_list) + " |")
        return
    widths = {}
    for key in field_list:
        widths[key] = max(len(key), min(_CELL_LIMIT, max(len(_cell(hit, key)) for hit in hits)))
    print("  ".join(key.ljust(widths[key]) for key in field_list))
    print("  ".join("-" * widths[key] for key in field_list))
    for hit in hits:
        print("  ".join(_cell(hit, key).ljust(widths[key]) for key in field_list))


def search_payload(sql: str, start_us: int, end_us: int, size: int, offset: int = 0, out_format: str = "jsonl") -> dict:
    payload = {
        "query": {
            "sql": sql,
            "start_time": start_us,
            "end_time": end_us,
            "from": offset,
            "size": size,
        },
        "timeout": int(http_timeout()),
    }
    if out_format == "csv":
        payload["agent_options"] = {"output_format": "csv"}
    elif out_format == "md":
        payload["agent_options"] = {"output_format": "md_table"}
    return payload


def print_search_result(result: dict, fields: str = "", out_format: str = "jsonl", title: str = "# Search Results"):
    hits = result.get("hits", [])
    total = result.get("total", len(hits) if isinstance(hits, list) else 0)
    took = result.get("took", 0)
    print(f"{title}  |  total={total}  took={took}ms  returned={len(hits) if isinstance(hits, list) else '?'}\n")
    if isinstance(hits, str):
        print(hits)
        return
    if not isinstance(hits, list):
        print(json.dumps(result, ensure_ascii=False))
        return
    format_hits(hits, fields, out_format)


def schema_field_names(base_url, org, headers, stream) -> set:
    encoded = quote(stream, safe="")
    result = api_get(f"{base_url}/api/{org}/{encoded}/schema", headers, fatal=False)
    return {field.get("name") for field in result.get("schema", []) if field.get("name")}


def stream_or_default(args) -> str:
    if not getattr(args, "stream", ""):
        print('[WARN] stream omitted; querying "default". Pass a stream name explicitly.', file=sys.stderr)
        return "default"
    return args.stream


# ---------------------------------------------------------------------------
# LOGS commands
# ---------------------------------------------------------------------------

def cmd_search(args, base_url, org, headers):
    sql = resolve_sql(args)
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    out_format = getattr(args, "out_format", "jsonl")
    payload = search_payload(sql, start_us, end_us, args.size, args.offset, out_format)
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    print_search_result(result, args.fields, out_format)


def cmd_streams(args, base_url, org, headers):
    stream_type = getattr(args, "type", "logs")
    url = f"{base_url}/api/{org}/streams?type={stream_type}&fetchSchema={'true' if args.schema else 'false'}"
    result = api_get(url, headers)
    streams = result.get("list", [])
    print(f"# Streams ({stream_type})  |  count={len(streams)}\n")
    for s in streams:
        stats = s.get("stats", {})
        doc_num = stats.get("doc_num", "?")
        size_mb = stats.get("storage_size", 0)
        print(f"  {s['name']:<30} docs={doc_num:<12} size={size_mb:.1f}MB")
        if args.schema and s.get("schema"):
            for field in s["schema"][:10]:
                print(f"      field: {field['name']} ({field['type']})")
            if len(s["schema"]) > 10:
                print(f"      ... and {len(s['schema']) - 10} more fields")


def cmd_schema(args, base_url, org, headers):
    result = api_get(f"{base_url}/api/{org}/{args.stream}/schema", headers)
    fields = result.get("schema", [])
    print(f"# Schema '{args.stream}'  |  fields={len(fields)}\n")
    for f in fields:
        print(f"  {f['name']:<50} {f['type']}")


def cmd_tail(args, base_url, org, headers):
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    payload = search_payload(
        f'SELECT * FROM "{args.stream}" ORDER BY _timestamp DESC',
        start_us, end_us, args.n, 0, "jsonl",
    )
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", 0)
    print(f"# Tail '{args.stream}'  |  total_in_range={total}  showing={len(hits)}\n")
    for hit in hits:
        ts = hit.get("_timestamp", 0)
        msg = pick_log_message(hit)
        print(f"[{fmt_ts_us(ts)}] {msg}")


def cmd_errors(args, base_url, org, headers):
    stream = stream_or_default(args)
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    names = schema_field_names(base_url, org, headers, stream)
    if "level" in names:
        levels = ["ERROR", "error", "FATAL", "fatal", "PANIC", "panic"]
        if args.level == "warn":
            levels.extend(["WARN", "warn", "WARNING", "warning"])
        level_filter = " OR ".join(f"level = '{lv}'" for lv in levels)
    else:
        level_filter = "match_all('error') OR match_all('ERROR') OR match_all('FATAL') OR match_all('fatal') OR match_all('panic')"
        if args.level == "warn":
            level_filter += " OR match_all('WARN') OR match_all('warn') OR match_all('warning')"
    sql = f'SELECT * FROM "{stream}" WHERE {level_filter} ORDER BY _timestamp DESC'
    payload = search_payload(sql, start_us, end_us, args.size, 0, "jsonl")
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", 0)
    print(f"# Error Logs '{stream}'  |  total={total}  showing={len(hits)}\n")
    for hit in hits:
        ts = hit.get("_timestamp", 0)
        msg = pick_log_message(hit)
        level = hit.get("level", hit.get("severity", ""))
        print(f"[{fmt_ts_us(ts)}] [{level}] {msg}")


def cmd_summary(args, base_url, org, headers):
    stream = stream_or_default(args)
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    names = schema_field_names(base_url, org, headers, stream)
    group_field = "level" if "level" in names else ("status" if "status" in names else "level")
    stream_clause = f'FROM "{stream}"'
    url = f"{base_url}/api/{org}/_search"

    r_level = api_request("POST", url, headers, search_payload(
        f"SELECT {group_field}, COUNT(*) AS cnt {stream_clause} GROUP BY {group_field} ORDER BY cnt DESC",
        start_us, end_us, 100, 0, "jsonl",
    ))
    r_total = api_request("POST", url, headers, search_payload(
        f"SELECT COUNT(*) AS total {stream_clause}",
        start_us, end_us, 1, 0, "jsonl",
    ))

    print(f"# Log Summary '{stream}' (past {args.since})\n")
    print("## By Level")
    for row in r_level.get("hits", []):
        print(f"  {str(row.get(group_field, 'unknown')):<15} {row.get('cnt', 0)}")
    hits_t = r_total.get("hits", [])
    total = hits_t[0].get("total", "?") if hits_t else "?"
    print(f"\n## Total entries: {total}")


def cmd_around(args, base_url, org, headers):
    key_us = parse_time_us(args.at)
    params = urlencode({"key": key_us, "size": args.size})
    encoded = quote(args.stream, safe="")
    url = f"{base_url}/api/{org}/{encoded}/_around?{params}"
    result = api_get(url, headers)
    out_format = getattr(args, "out_format", "jsonl")
    print_search_result(result, args.fields, out_format, title=f"# Around '{args.stream}'")


def cmd_values(args, base_url, org, headers):
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    params = {
        "fields": args.fields,
        "start_time": start_us,
        "end_time": end_us,
        "size": args.size,
    }
    if args.keyword:
        params["keyword"] = args.keyword
    encoded = quote(args.stream, safe="")
    url = f"{base_url}/api/{org}/{encoded}/_values?{urlencode(params)}"
    result = api_get(url, headers)
    hits = result.get("hits", [])
    print(f"# Values '{args.stream}'  |  fields={args.fields}  groups={len(hits)}\n")
    for group in hits:
        field = group.get("field", "?")
        values = group.get("values", [])
        print(f"  {field}")
        for item in values:
            key = item.get("zo_sql_key", item)
            num = item.get("zo_sql_num", "")
            extra = f"  {num}" if num != "" else ""
            print(f"    {key}{extra}")


def cmd_histogram(args, base_url, org, headers):
    start_us, end_us = resolve_range_us(args.since, getattr(args, "until", ""))
    try:
        interval = histogram_interval_sql(args.interval)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    sql = (
        f'SELECT histogram(_timestamp, \'{interval}\') AS ts, COUNT(*) AS cnt '
        f'FROM "{args.stream}" GROUP BY ts ORDER BY ts'
    )
    payload = search_payload(sql, start_us, end_us, args.size, 0, "jsonl")
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    print(f"# Histogram '{args.stream}'  |  interval={args.interval}  buckets={len(hits)}\n")
    for row in hits:
        ts = row.get("ts", row.get("histogram", ""))
        cnt = row.get("cnt", row.get("count", 0))
        print(f"  {ts}  {cnt}")


# ---------------------------------------------------------------------------
# METRICS commands
# ---------------------------------------------------------------------------

def cmd_metrics_query(args, base_url, org, headers):
    """Instant PromQL query."""
    params = urlencode({"query": args.query, "time": now_s()})
    url = f"{base_url}/api/{org}/prometheus/api/v1/query?{params}"
    result = api_get(url, headers)
    status = result.get("status", "unknown")
    data = result.get("data", {})
    result_type = data.get("resultType", "unknown")
    results = data.get("result", [])
    print(f"# Metrics Instant Query  |  status={status}  type={result_type}  series={len(results)}\n")
    for item in results:
        metric = item.get("metric", {})
        value = item.get("value", [None, None])
        ts_str = fmt_ts_s(value[0]) if value[0] else ""
        print(f"  {json.dumps(metric, ensure_ascii=False)}")
        print(f"    value={value[1]}  at={ts_str}\n")


def cmd_metrics_range(args, base_url, org, headers):
    """PromQL range query."""
    start_s = parse_time_offset_s(args.since)
    end_s = now_s()
    params = urlencode({
        "query": args.query,
        "start": start_s,
        "end": end_s,
        "step": args.step,
    })
    url = f"{base_url}/api/{org}/prometheus/api/v1/query_range?{params}"
    result = api_get(url, headers)
    status = result.get("status", "unknown")
    data = result.get("data", {})
    results = data.get("result", [])
    print(f"# Metrics Range Query  |  status={status}  series={len(results)}  step={args.step}\n")
    for item in results:
        metric = item.get("metric", {})
        values = item.get("values", [])
        print(f"  Series: {json.dumps(metric, ensure_ascii=False)}  datapoints={len(values)}")
        for ts, val in values[-5:]:  # show last 5 points
            print(f"    [{fmt_ts_s(ts)}] {val}")
        if len(values) > 5:
            print(f"    ... (showing last 5 of {len(values)} points; use --size to adjust)")
        print()


def cmd_metrics_list(args, base_url, org, headers):
    """List available metric names."""
    params = urlencode({"start": parse_time_offset_s(args.since), "end": now_s()})
    url = f"{base_url}/api/{org}/prometheus/api/v1/label/__name__/values?{params}"
    result = api_get(url, headers)
    names = result.get("data", [])
    print(f"# Metric Names  |  count={len(names)}\n")
    filter_str = args.filter.lower() if args.filter else ""
    for name in sorted(names):
        if not filter_str or filter_str in name.lower():
            print(f"  {name}")


# ---------------------------------------------------------------------------
# TRACES commands
# ---------------------------------------------------------------------------

def cmd_traces_latest(args, base_url, org, headers):
    """List recent traces from a stream."""
    start_us, end_us = resolve_range_us(args.since, "")
    params = urlencode({
        "start_time": start_us,
        "end_time": end_us,
        "from": 0,
        "size": args.size,
        "filter": args.filter or "",
    })
    stream = args.stream or "default"
    url = f"{base_url}/api/{org}/{stream}/traces/latest?{params}"
    result = api_get(url, headers)
    traces = result.get("hits", result.get("traces", []))
    total = result.get("total", len(traces))
    print(f"# Recent Traces '{stream}'  |  total={total}  showing={len(traces)}\n")
    for t in traces:
        trace_id = t.get("trace_id", "?")
        svc = t.get("service_name", t.get("service", "?"))
        duration_ms = t.get("duration", 0) / 1000  # ns to ms if needed
        start_ts = t.get("start_time", 0)
        status = t.get("status_code", t.get("status", ""))
        spans = t.get("spans", t.get("spans_count", "?"))
        ts_str = fmt_ts_us(start_ts) if start_ts else ""
        print(f"  [{ts_str}] trace={trace_id[:16]}...  svc={svc}  dur={duration_ms:.1f}ms  spans={spans}  status={status}")


def cmd_traces_get(args, base_url, org, headers):
    """Get all spans for a specific trace_id using Search API."""
    start_us, end_us = resolve_range_us(args.since, "")
    sql = f'SELECT * FROM "{args.stream or "default"}" WHERE trace_id = \'{args.trace_id}\' ORDER BY start_time'
    payload = search_payload(sql, start_us, end_us, -1, 0, "jsonl")
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    spans = result.get("hits", [])
    print(f"# Trace Detail  |  trace_id={args.trace_id}  spans={len(spans)}\n")
    for span in spans:
        span_id = span.get("span_id", "?")
        name = span.get("operation_name", span.get("name", "?"))
        svc = span.get("service_name", span.get("service", "?"))
        dur = span.get("duration", 0)
        status = span.get("status_code", "")
        parent = span.get("parent_span_id", "root")
        print(f"  span={span_id[:12]}  op={name}  svc={svc}  dur={dur}us  status={status}  parent={parent[:12] if parent else 'root'}")


def cmd_traces_search(args, base_url, org, headers):
    """Search traces by service, min duration, or error status."""
    start_us, end_us = resolve_range_us(args.since, "")
    stream = args.stream or "default"

    conditions = []
    if args.service:
        conditions.append(f"service_name = '{args.service}'")
    if args.min_duration_ms:
        conditions.append(f"duration >= {args.min_duration_ms * 1000}")
    if args.errors_only:
        conditions.append("status_code = 'STATUS_CODE_ERROR'")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f'SELECT * FROM "{stream}" {where} ORDER BY _timestamp DESC'

    payload = search_payload(sql, start_us, end_us, args.size, 0, "jsonl")
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", 0)
    print(f"# Trace Search '{stream}'  |  total={total}  showing={len(hits)}\n")
    for span in hits:
        ts = span.get("_timestamp", 0)
        trace_id = span.get("trace_id", "?")
        op = span.get("operation_name", span.get("name", "?"))
        svc = span.get("service_name", "?")
        dur = span.get("duration", 0)
        status = span.get("status_code", "")
        print(f"  [{fmt_ts_us(ts)}] trace={trace_id[:16]}  op={op}  svc={svc}  dur={dur}us  status={status}")


# ---------------------------------------------------------------------------
# ALERTS commands
# ---------------------------------------------------------------------------

def cmd_alerts_list(args, base_url, org, headers):
    """List alert definitions."""
    url = f"{base_url}/api/{org}/alerts"
    result = api_get(url, headers)
    alerts = result.get("list", result if isinstance(result, list) else [])
    print(f"# Alerts  |  count={len(alerts)}\n")
    for a in alerts:
        name = a.get("name", "?")
        stream = a.get("stream_name", "?")
        enabled = a.get("enabled", "?")
        condition = a.get("condition", {})
        freq = a.get("frequency", "?")
        print(f"  {name:<30} stream={stream}  enabled={enabled}  freq={freq}")
        if condition:
            print(f"    condition: {json.dumps(condition, ensure_ascii=False)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _load_dotenv()
    base_url = os.environ.get("OO_BASE_URL", "").rstrip("/")
    org = os.environ.get("OO_ORG", "default")
    user = os.environ.get("OO_USER", "")
    password = os.environ.get("OO_PASSWORD", "")

    if not base_url:
        print("[ERROR] OO_BASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    if not user or not password:
        print("[ERROR] OO_USER and OO_PASSWORD must be set.", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": get_auth_header(user, password),
        "Content-Type": "application/json",
    }

    parser = argparse.ArgumentParser(
        description="OpenObserve CLI  — Logs / Metrics / Traces / Alerts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # ── LOGS ──────────────────────────────────────────────────
    p = sub.add_parser("search", help="[LOGS] Run SQL query")
    p.add_argument("sql", nargs="?", default="", help="SQL statement, or '-' to read stdin")
    p.add_argument("--sql", dest="sql_flag", default="", help="SQL statement (PowerShell-friendly)")
    p.add_argument("--sql-file", dest="sql_file", default="", help="Read SQL from a file")
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="", help="End time: 15m/1h/2d or absolute timestamp")
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--fields", default="")
    p.add_argument("--format", dest="out_format", default="jsonl",
                   choices=["jsonl", "compact", "csv", "md"],
                   help="Output format (default jsonl; use jsonl for oo_analyze.py)")

    p = sub.add_parser("streams", help="[LOGS] List streams")
    p.add_argument("--type", default="logs", choices=["logs", "metrics", "traces"])
    p.add_argument("--schema", action="store_true")

    p = sub.add_parser("schema", help="[LOGS] Show stream schema")
    p.add_argument("stream")

    p = sub.add_parser("tail", help="[LOGS] Show latest entries")
    p.add_argument("stream")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="")

    p = sub.add_parser("errors", help="[LOGS] Find error logs")
    p.add_argument("stream", nargs="?", default="")
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="")
    p.add_argument("--size", type=int, default=50)
    p.add_argument("--level", default="error", choices=["error", "warn"])

    p = sub.add_parser("summary", help="[LOGS] Log count summary")
    p.add_argument("stream", nargs="?", default="")
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="")

    p = sub.add_parser("around", help="[LOGS] Logs around a timestamp")
    p.add_argument("stream")
    p.add_argument("--at", required=True, help="Center timestamp: 15m/1h/2d or absolute")
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--fields", default="")
    p.add_argument("--format", dest="out_format", default="jsonl",
                   choices=["jsonl", "compact", "csv", "md"])

    p = sub.add_parser("values", help="[LOGS] Distinct field values")
    p.add_argument("stream")
    p.add_argument("--fields", required=True, help="Comma-separated field names")
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="")
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--keyword", default="")

    p = sub.add_parser("histogram", help="[LOGS] Time histogram")
    p.add_argument("stream")
    p.add_argument("--interval", default="5m", help="Bucket size, e.g. 5m / 1h")
    p.add_argument("--since", default="1h")
    p.add_argument("--until", default="")
    p.add_argument("--size", type=int, default=1000)

    # ── METRICS ───────────────────────────────────────────────
    p = sub.add_parser("metrics-query", help="[METRICS] Instant PromQL query")
    p.add_argument("query", help="PromQL expression")

    p = sub.add_parser("metrics-range", help="[METRICS] PromQL range query")
    p.add_argument("query", help="PromQL expression")
    p.add_argument("--since", default="1h", help="Look-back window, e.g. 15m/1h/2d")
    p.add_argument("--step", default="60", help="Step in seconds (default 60)")

    p = sub.add_parser("metrics-list", help="[METRICS] List metric names")
    p.add_argument("--since", default="1h")
    p.add_argument("--filter", default="", help="Substring filter on metric name")

    # ── TRACES ────────────────────────────────────────────────
    p = sub.add_parser("traces-latest", help="[TRACES] List recent traces")
    p.add_argument("stream", nargs="?", default="default")
    p.add_argument("--since", default="1h")
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--filter", default="", help="Filter expression e.g. 'service_name:my-svc'")

    p = sub.add_parser("traces-get", help="[TRACES] Get spans for a trace_id")
    p.add_argument("trace_id", help="Full trace ID")
    p.add_argument("--stream", default="default")
    p.add_argument("--since", default="1d")

    p = sub.add_parser("traces-search", help="[TRACES] Search traces by criteria")
    p.add_argument("--stream", default="default")
    p.add_argument("--since", default="1h")
    p.add_argument("--service", default="", help="Filter by service name")
    p.add_argument("--min-duration-ms", type=int, default=0, dest="min_duration_ms",
                   help="Minimum trace duration (ms)")
    p.add_argument("--errors-only", action="store_true", dest="errors_only",
                   help="Only show error traces")
    p.add_argument("--size", type=int, default=20)

    # ── ALERTS ────────────────────────────────────────────────
    p = sub.add_parser("alerts-list", help="[ALERTS] List alert definitions")

    args = parser.parse_args()

    dispatch = {
        "search": cmd_search,
        "streams": cmd_streams,
        "schema": cmd_schema,
        "tail": cmd_tail,
        "errors": cmd_errors,
        "summary": cmd_summary,
        "around": cmd_around,
        "values": cmd_values,
        "histogram": cmd_histogram,
        "metrics-query": cmd_metrics_query,
        "metrics-range": cmd_metrics_range,
        "metrics-list": cmd_metrics_list,
        "traces-latest": cmd_traces_latest,
        "traces-get": cmd_traces_get,
        "traces-search": cmd_traces_search,
        "alerts-list": cmd_alerts_list,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args, base_url, org, headers)


if __name__ == "__main__":
    main()
