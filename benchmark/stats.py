"""Latency and throughput arithmetic.

Pure: no clients, no I/O, no printing. Everything a run reports is computed
here, so the numbers can be tested without a stack running.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

MIB = 1024 * 1024

# Reported for every phase, alongside min/mean/max.
PERCENTILES = (50, 90, 99)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of ``values``, with ``q`` a percentage.

    Nearest-rank returns a latency that was actually observed rather than an
    interpolation between two samples, which is what you want for a tail
    figure: with nine samples the p99 is the slowest of the nine, not a number
    nothing ever took. ``statistics.quantiles`` interpolates and needs at least
    two points.
    """
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    rank = math.ceil(q / 100 * len(ordered)) - 1
    return ordered[min(max(rank, 0), len(ordered) - 1)]


@dataclass(frozen=True)
class PhaseResult:
    """One measured phase — a put pass, a GET pass, a produce pass.

    ``latencies`` holds one sample per *timed call*, which is not always one
    per logical operation: a pipelined Valkey batch is a single round trip
    carrying ``ops_per_call`` commands. Throughput counts the commands,
    latency describes the round trip, and ``sample_label`` says which.
    """

    name: str
    requested: int
    elapsed: float
    latencies: tuple[float, ...] = ()
    error_counts: Mapping[str, int] = field(default_factory=dict)
    total_bytes: int = 0
    truncated: bool = False
    ops_per_call: int = 1

    @property
    def ops(self) -> int:
        """Logical operations that succeeded."""
        return len(self.latencies) * self.ops_per_call

    @property
    def errors(self) -> int:
        return sum(self.error_counts.values())

    @property
    def sample_label(self) -> str:
        return "batch" if self.ops_per_call > 1 else "op"

    @property
    def ops_per_sec(self) -> float:
        return self.ops / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def mib_per_sec(self) -> float:
        return self.total_bytes / MIB / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def latency_ms(self) -> dict[str, float] | None:
        """Latency summary in milliseconds, or ``None`` if nothing succeeded."""
        if not self.latencies:
            return None
        samples = list(self.latencies)
        summary = {
            "min": min(samples) * 1000,
            "mean": sum(samples) / len(samples) * 1000,
            "max": max(samples) * 1000,
        }
        for q in PERCENTILES:
            summary[f"p{q}"] = percentile(samples, q) * 1000
        return summary
