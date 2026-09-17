"""Percentile maths and the derived figures on a phase result."""

from __future__ import annotations

import pytest

from benchmark.stats import MIB, PhaseResult, percentile


def test_percentiles_of_one_to_one_hundred():
    values = [float(n) for n in range(1, 101)]
    assert percentile(values, 50) == 50
    assert percentile(values, 90) == 90
    assert percentile(values, 99) == 99
    assert percentile(values, 100) == 100


def test_percentile_sorts_its_input():
    assert percentile([9.0, 1.0, 5.0], 50) == 5.0


def test_percentile_of_a_single_sample_is_that_sample():
    assert percentile([0.25], 99) == 0.25


def test_percentile_of_an_empty_sample_raises():
    with pytest.raises(ValueError, match="empty sample"):
        percentile([], 50)


def test_rates_use_wall_clock_elapsed():
    phase = PhaseResult(
        name="put",
        requested=4,
        elapsed=2.0,
        latencies=(0.1, 0.2, 0.3, 0.4),
        total_bytes=4 * MIB,
    )
    assert phase.ops == 4
    assert phase.ops_per_sec == 2.0
    assert phase.mib_per_sec == 2.0
    assert phase.errors == 0


def test_zero_elapsed_does_not_divide_by_zero():
    phase = PhaseResult(name="ping", requested=1, elapsed=0.0, latencies=(0.001,))
    assert phase.ops_per_sec == 0.0
    assert phase.mib_per_sec == 0.0


def test_latency_summary_is_in_milliseconds():
    phase = PhaseResult(name="get", requested=2, elapsed=1.0, latencies=(0.001, 0.002))
    summary = phase.latency_ms
    assert summary is not None
    assert summary["min"] == pytest.approx(1.0)
    assert summary["max"] == pytest.approx(2.0)
    assert summary["mean"] == pytest.approx(1.5)
    assert summary["p50"] == pytest.approx(1.0)
    assert summary["p99"] == pytest.approx(2.0)


def test_no_successful_ops_means_no_latency_summary():
    phase = PhaseResult(name="get", requested=5, elapsed=1.0, error_counts={"KeyError: x": 5})
    assert phase.latency_ms is None
    assert phase.ops == 0
    assert phase.errors == 5


def test_pipelined_phase_counts_commands_but_times_batches():
    phase = PhaseResult(
        name="set-pipe",
        requested=100,
        elapsed=1.0,
        latencies=(0.01,) * 10,
        ops_per_call=10,
    )
    assert phase.ops == 100
    assert phase.ops_per_sec == 100.0
    assert phase.sample_label == "batch"
