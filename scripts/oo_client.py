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
"""

import os
import sys
import json
import base64
import argparse
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def get_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def now_us() -> int:
    return int(time.time() * 1_000_000)


def now_s() -> int:
    return int(time.time())


def parse_time_offset_us(spec: str) -> int:
    """Return absolute start time in microseconds."""
    unit = spec[-1]
    value = int(spec[:-1])
    multipliers = {'m': 60, 'h': 3600, 'd': 86400}
    if unit not in multipliers:
        raise ValueError(f"Unknown time unit '{unit}'. Use m/h/d.")
    return now_us() - value * multipliers[unit] * 1_000_000


def parse_time_offset_s(spec: str) -> int:
    """Return absolute start time in seconds (for Prometheus-compat APIs)."""
    unit = spec[-1]
    value = int(spec[:-1])
    multipliers = {'m': 60, 'h': 3600, 'd': 86400}
    if unit not in multipliers:
        raise ValueError(f"Unknown time unit '{unit}'. Use m/h/d.")
    return now_s() - value * multipliers[unit]


def api_request(method: str, url: str, headers: dict, body: dict = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        error_body = e.read().decode()
        print(f"[ERROR] HTTP {e.code}: {error_body}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"[ERROR] Connection failed: {e.reason}", file=sys.stderr)
        sys.exit(1)


def api_get(url: str, headers: dict) -> dict:
    return api_request("GET", url, headers)


def fmt_ts_us(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fmt_ts_s(ts_s: float) -> str:
    return datetime.fromtimestamp(float(ts_s), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# LOGS commands
# ---------------------------------------------------------------------------

def cmd_search(args, base_url, org, headers):
    start_us = parse_time_offset_us(args.since)
    end_us = now_us()
    payload = {
        "query": {
            "sql": args.sql,
            "start_time": start_us,
            "end_time": end_us,
            "from": args.offset,
            "size": args.size,
        }
    }
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", len(hits))
    took = result.get("took", 0)
    print(f"# Search Results  |  total={total}  took={took}ms  returned={len(hits)}\n")
    field_list = [f.strip() for f in args.fields.split(",")] if args.fields else None
    for hit in hits:
        row = {k: hit.get(k, "") for k in field_list} if field_list else hit
        print(json.dumps(row, ensure_ascii=False))


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
    start_us = parse_time_offset_us(args.since)
    payload = {
        "query": {
            "sql": f'SELECT * FROM "{args.stream}" ORDER BY _timestamp DESC',
            "start_time": start_us,
            "end_time": now_us(),
            "from": 0,
            "size": args.n,
        }
    }
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", 0)
    print(f"# Tail '{args.stream}'  |  total_in_range={total}  showing={len(hits)}\n")
    for hit in hits:
        ts = hit.get("_timestamp", 0)
        msg = hit.get("log", hit.get("message", hit.get("msg", json.dumps(hit, ensure_ascii=False))))
        print(f"[{fmt_ts_us(ts)}] {msg}")


def cmd_errors(args, base_url, org, headers):
    start_us = parse_time_offset_us(args.since)
    level_filter = "match_all('error') OR match_all('ERROR') OR match_all('FATAL') OR match_all('fatal') OR match_all('panic')"
    if args.level == "warn":
        level_filter += " OR match_all('WARN') OR match_all('warn') OR match_all('warning')"
    stream_clause = f'FROM "{args.stream}"' if args.stream else 'FROM "default"'
    sql = f"SELECT * {stream_clause} WHERE {level_filter} ORDER BY _timestamp DESC"
    payload = {
        "query": {
            "sql": sql,
            "start_time": start_us,
            "end_time": now_us(),
            "from": 0,
            "size": args.size,
        }
    }
    result = api_request("POST", f"{base_url}/api/{org}/_search", headers, payload)
    hits = result.get("hits", [])
    total = result.get("total", 0)
    print(f"# Error Logs '{args.stream or 'default'}'  |  total={total}  showing={len(hits)}\n")
    for hit in hits:
        ts = hit.get("_timestamp", 0)
        msg = hit.get("log", hit.get("message", hit.get("msg", "")))
        level = hit.get("level", hit.get("severity", ""))
        print(f"[{fmt_ts_us(ts)}] [{level}] {msg}")


def cmd_summary(args, base_url, org, headers):
    start_us = parse_time_offset_us(args.since)
    end_us = now_us()
    stream_clause = f'FROM "{args.stream}"' if args.stream else 'FROM "default"'
    url = f"{base_url}/api/{org}/_search"

    r_level = api_request("POST", url, headers, {
        "query": {
            "sql": f"SELECT level, COUNT(*) AS cnt {stream_clause} GROUP BY level ORDER BY cnt DESC",
            "start_time": start_us, "end_time": end_us, "from": 0, "size": 100
        }
    })
    r_total = api_request("POST", url, headers, {
        "query": {
            "sql": f"SELECT COUNT(*) AS total {stream_clause}",
            "start_time": start_us, "end_time": end_us, "from": 0, "size": 1
        }
    })

    print(f"# Log Summary '{args.stream or 'default'}' (past {args.since})\n")
    print("## By Level")
    for row in r_level.get("hits", []):
        print(f"  {row.get('level','unknown'):<15} {row.get('cnt', 0)}")
    hits_t = r_total.get("hits", [])
    total = hits_t[0].get("total", "?") if hits_t else "?"
    print(f"\n## Total entries: {total}")


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
    start_us = parse_time_offset_us(args.since)
    end_us = now_us()
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
    start_us = parse_time_offset_us(args.since)
    sql = f'SELECT * FROM "{args.stream or "default"}" WHERE trace_id = \'{args.trace_id}\' ORDER BY start_time'
    payload = {
        "query": {
            "sql": sql,
            "start_time": start_us,
            "end_time": now_us(),
            "from": 0,
            "size": -1,
        }
    }
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
    start_us = parse_time_offset_us(args.since)
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

    payload = {
        "query": {
            "sql": sql,
            "start_time": start_us,
            "end_time": now_us(),
            "from": 0,
            "size": args.size,
        }
    }
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
    p.add_argument("sql", help="SQL statement")
    p.add_argument("--since", default="1h")
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--fields", default="")

    p = sub.add_parser("streams", help="[LOGS] List streams")
    p.add_argument("--type", default="logs", choices=["logs", "metrics", "traces"])
    p.add_argument("--schema", action="store_true")

    p = sub.add_parser("schema", help="[LOGS] Show stream schema")
    p.add_argument("stream")

    p = sub.add_parser("tail", help="[LOGS] Show latest entries")
    p.add_argument("stream")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--since", default="1h")

    p = sub.add_parser("errors", help="[LOGS] Find error logs")
    p.add_argument("stream", nargs="?", default="")
    p.add_argument("--since", default="1h")
    p.add_argument("--size", type=int, default=50)
    p.add_argument("--level", default="error", choices=["error", "warn"])

    p = sub.add_parser("summary", help="[LOGS] Log count summary")
    p.add_argument("stream", nargs="?", default="")
    p.add_argument("--since", default="1h")

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
