#!/usr/bin/env python3
"""Unit tests for oo_client helpers. No live OpenObserve required."""

import io
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import oo_client  # noqa: E402


class ChooseSqlTests(unittest.TestCase):
    def test_sql_file_wins(self):
        self.assertEqual(
            oo_client.choose_sql("SELECT 1", "SELECT 2", "SELECT 3", "SELECT 4"),
            "SELECT 3",
        )

    def test_sql_flag_over_positional(self):
        self.assertEqual(
            oo_client.choose_sql('SELECT * FROM "a"', "SELECT 2", None, None),
            "SELECT 2",
        )

    def test_positional(self):
        self.assertEqual(oo_client.choose_sql("SELECT 1", "", None, None), "SELECT 1")

    def test_dash_reads_stdin(self):
        self.assertEqual(
            oo_client.choose_sql("-", "", None, 'SELECT * FROM "app"'),
            'SELECT * FROM "app"',
        )

    def test_empty(self):
        self.assertEqual(oo_client.choose_sql("", "", None, None), "")


class TimeParseTests(unittest.TestCase):
    def test_relative_hour(self):
        with mock.patch.object(oo_client, "now_us", return_value=3_600_000_000):
            self.assertEqual(oo_client.parse_time_offset_us("1h"), 0)

    def test_unix_seconds(self):
        self.assertEqual(oo_client.parse_absolute_us("1700000000"), 1700000000 * 1_000_000)

    def test_iso_z(self):
        got = oo_client.parse_absolute_us("2024-01-01T00:00:00Z")
        expected = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
        self.assertEqual(got, expected)

    def test_naive_uses_oo_tz_utc(self):
        os.environ.pop("OO_TZ", None)
        got = oo_client.parse_absolute_us("2024-01-01 00:00:00")
        expected = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
        self.assertEqual(got, expected)

    def test_until_relative_before_since_fails(self):
        with mock.patch.object(oo_client, "now_us", return_value=10_000_000):
            with self.assertRaises(SystemExit):
                oo_client.resolve_range_us("1h", "2h")


class FormatHitsTests(unittest.TestCase):
    def test_jsonl_default_full_hit(self):
        hits = [{"_timestamp": 1, "log": "hello", "extra": "keep"}]
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            oo_client.format_hits(hits, "", "jsonl")
        line = buf.getvalue().strip()
        self.assertEqual(json.loads(line), hits[0])

    def test_jsonl_fields_projects(self):
        hits = [{"_timestamp": 1, "log": "hello", "extra": "drop"}]
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            oo_client.format_hits(hits, "log", "jsonl")
        self.assertEqual(json.loads(buf.getvalue().strip()), {"log": "hello"})

    def test_compact_infers_fields(self):
        hits = [{"_timestamp": 1700000000000000, "level": "error", "log": "boom", "noise": "x"}]
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            oo_client.format_hits(hits, "", "compact")
        text = buf.getvalue()
        self.assertIn("level", text)
        self.assertIn("error", text)
        self.assertNotIn("noise", text.split("\n")[0])


class HelperTests(unittest.TestCase):
    def test_histogram_interval(self):
        self.assertEqual(oo_client.histogram_interval_sql("5m"), "5 minute")
        self.assertEqual(oo_client.histogram_interval_sql("1h"), "1 hour")

    def test_truncate_error_body(self):
        body = "x" * 800
        out = oo_client.truncate_error_body(body, 500)
        self.assertTrue(out.endswith("...(truncated)"))
        self.assertEqual(len(out), 500 + len("...(truncated)"))

    def test_pick_log_message_prefers_log(self):
        self.assertEqual(oo_client.pick_log_message({"log": "a", "message": "b"}), "a")

    def test_pick_log_message_truncates_fallback(self):
        hit = {"k": "v" * 600}
        msg = oo_client.pick_log_message(hit)
        self.assertTrue(msg.endswith("..."))
        self.assertLessEqual(len(msg), oo_client._MSG_FALLBACK_LIMIT + 3)

    def test_search_payload_jsonl_has_timeout_no_agent_options(self):
        payload = oo_client.search_payload("SELECT 1", 1, 2, 10)
        self.assertIn("timeout", payload)
        self.assertNotIn("agent_options", payload)

    def test_search_payload_csv_sets_agent_options(self):
        payload = oo_client.search_payload("SELECT 1", 1, 2, 10, out_format="csv")
        self.assertEqual(payload["agent_options"]["output_format"], "csv")

    def test_search_payload_md_sets_md_table(self):
        payload = oo_client.search_payload("SELECT 1", 1, 2, 10, out_format="md")
        self.assertEqual(payload["agent_options"]["output_format"], "md_table")


if __name__ == "__main__":
    unittest.main()
