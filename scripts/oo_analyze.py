#!/usr/bin/env python3
"""
OpenObserve Log Analysis Helper
Performs deeper analysis on query results: pattern extraction, anomaly hints, top-N grouping.

Usage: python oo_analyze.py <command> [options]

Commands:
  patterns    Extract recurring log patterns from raw lines
  topk        Group and rank by a field
  timeline    Show log volume per time bucket

Reads JSON lines from stdin (output of oo_client.py search).
"""

import sys
import json
import re
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone


def read_hits_stdin():
    """Read JSON lines from stdin, skip comment lines starting with #."""
    hits = []
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            hits.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return hits


def cmd_patterns(args):
    """Extract common patterns from log messages."""
    hits = read_hits_stdin()
    if not hits:
        print("No input.")
        return

    messages = []
    for hit in hits:
        msg = hit.get("log", hit.get("message", hit.get("msg", "")))
        messages.append(str(msg))

    # Normalize: replace numbers, UUIDs, IPs, hex with placeholders
    def normalize(msg):
        msg = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<UUID>', msg, flags=re.I)
        msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>', msg)
        msg = re.sub(r'\b0x[0-9a-f]+\b', '<HEX>', msg, flags=re.I)
        msg = re.sub(r'\b\d+\b', '<NUM>', msg)
        msg = re.sub(r'"[^"]{0,100}"', '"<STR>"', msg)
        return msg.strip()

    normalized = [normalize(m) for m in messages]
    counter = Counter(normalized)

    print(f"# Log Patterns  |  total={len(messages)}  unique_patterns={len(counter)}")
    print()
    print(f"{'COUNT':>8}  PATTERN")
    print("-" * 80)
    for pattern, cnt in counter.most_common(args.top):
        truncated = pattern[:120] + ("..." if len(pattern) > 120 else "")
        print(f"{cnt:>8}  {truncated}")


def cmd_topk(args):
    """Group and count by a specific field."""
    hits = read_hits_stdin()
    if not hits:
        print("No input.")
        return

    counter = Counter()
    for hit in hits:
        val = hit.get(args.field, "<missing>")
        counter[str(val)] += 1

    print(f"# Top-{args.k} by '{args.field}'  |  total={len(hits)}")
    print()
    print(f"{'COUNT':>8}  {'VALUE'}")
    print("-" * 60)
    for val, cnt in counter.most_common(args.k):
        print(f"{cnt:>8}  {val}")


def cmd_timeline(args):
    """Show log volume per time bucket."""
    hits = read_hits_stdin()
    if not hits:
        print("No input.")
        return

    bucket_us = args.bucket_minutes * 60 * 1_000_000
    buckets = defaultdict(int)

    for hit in hits:
        ts = hit.get("_timestamp", 0)
        if ts:
            bucket = (ts // bucket_us) * bucket_us
            buckets[bucket] += 1

    if not buckets:
        print("No timestamp data found.")
        return

    max_count = max(buckets.values())
    bar_width = 40

    print(f"# Timeline  |  bucket={args.bucket_minutes}min  total_buckets={len(buckets)}")
    print()
    for bucket_ts in sorted(buckets):
        dt = datetime.fromtimestamp(bucket_ts / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        cnt = buckets[bucket_ts]
        bar_len = int(cnt / max_count * bar_width) if max_count > 0 else 0
        bar = "█" * bar_len
        print(f"  {dt}  {bar:<{bar_width}}  {cnt}")


def main():
    parser = argparse.ArgumentParser(description="OpenObserve Log Analyzer (reads JSON from stdin)")
    subparsers = parser.add_subparsers(dest="command")

    p_pat = subparsers.add_parser("patterns", help="Extract log patterns")
    p_pat.add_argument("--top", type=int, default=20, help="Show top N patterns")

    p_topk = subparsers.add_parser("topk", help="Group by field and rank")
    p_topk.add_argument("field", help="Field name to group by")
    p_topk.add_argument("-k", type=int, default=10, help="Number of top values")

    p_tl = subparsers.add_parser("timeline", help="Log volume over time")
    p_tl.add_argument("--bucket-minutes", type=int, default=5, help="Time bucket in minutes")

    args = parser.parse_args()

    dispatch = {
        "patterns": cmd_patterns,
        "topk": cmd_topk,
        "timeline": cmd_timeline,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
