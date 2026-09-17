"""Table and JSON rendering."""

from __future__ import annotations

import json

from benchmark.report import ServiceReport, render_text, to_dict
from benchmark.stats import MIB, PhaseResult


def build(*phases: PhaseResult, notes: tuple[str, ...] = ()) -> ServiceReport:
    return ServiceReport(
        service="S3 (Floci)",
        target="http://nas.local:4566",
        run_id="20260916T142233-a1b2c3d4",
        started_at="2026-09-16T14:22:33+0000",
        params={"ops": 4, "concurrency": 2},
        phases=phases,
        notes=notes,
    )


PUT = PhaseResult(
    name="put",
    requested=4,
    elapsed=2.0,
    latencies=(0.01, 0.02, 0.03, 0.04),
    total_bytes=4 * MIB,
)


def test_table_has_a_header_and_a_row_per_phase():
    lines = render_text(build(PUT)).splitlines()
    header = next(line for line in lines if line.startswith("phase"))
    assert "ops/s" in header and "p99 ms" in header
    row = next(line for line in lines if line.startswith("put"))
    assert "2.00s" in row
    assert "40.000" in row  # p99 of 0.04s, in milliseconds


def test_every_line_fits_a_hundred_column_terminal():
    assert all(len(line) <= 100 for line in render_text(build(PUT)).splitlines())


def test_a_phase_with_no_successes_renders_dashes():
    empty = PhaseResult(name="get", requested=4, elapsed=1.0, error_counts={"KeyError: k": 4})
    row = next(line for line in render_text(build(empty)).splitlines() if line.startswith("get"))
    assert "-" in row
    assert "4 x KeyError: k" in render_text(build(empty))


def test_truncated_phases_say_so():
    capped = PhaseResult(name="put", requested=100, elapsed=1.0, latencies=(0.1,), truncated=True)
    text = render_text(build(capped))
    assert "--duration cap" in text
    assert "1/100" in text


def test_pipelined_phases_label_the_latency_unit():
    piped = PhaseResult(
        name="set-pipe", requested=100, elapsed=1.0, latencies=(0.01,) * 10, ops_per_call=10
    )
    assert "latency is per batch" in render_text(build(piped))


def test_notes_are_printed():
    assert "note: cleaned up 4 keys" in render_text(build(PUT, notes=("cleaned up 4 keys",)))


def test_json_round_trips_and_reports_milliseconds():
    payload = json.loads(json.dumps(to_dict(build(PUT))))
    phase = payload["phases"][0]
    assert phase["name"] == "put"
    assert phase["ops"] == 4
    assert phase["ops_per_sec"] == 2.0
    assert phase["mib_per_sec"] == 2.0
    assert phase["latency_ms"]["p50"] == 20.0
    assert phase["sample_label"] == "op"
    assert payload["target"] == "http://nas.local:4566"


def test_json_keeps_null_latency_for_a_failed_phase():
    empty = PhaseResult(name="get", requested=4, elapsed=1.0, error_counts={"boom": 4})
    assert to_dict(build(empty))["phases"][0]["latency_ms"] is None
