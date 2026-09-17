"""Rendering for benchmark results: a table to read, JSON to diff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchmark.stats import PhaseResult

_COLUMNS = (
    ("phase", 10, "<"),
    ("ops", 9, ">"),
    ("errs", 6, ">"),
    ("elapsed", 9, ">"),
    ("ops/s", 11, ">"),
    ("MiB/s", 9, ">"),
    ("p50 ms", 10, ">"),
    ("p90 ms", 10, ">"),
    ("p99 ms", 10, ">"),
    ("max ms", 10, ">"),
)

# How many distinct failure messages to show per phase before summarising.
_ERRORS_SHOWN = 3


@dataclass(frozen=True)
class ServiceReport:
    service: str
    target: str
    run_id: str
    started_at: str
    params: dict[str, Any]
    phases: tuple[PhaseResult, ...]
    notes: tuple[str, ...] = ()


def _row(cells: list[str]) -> str:
    return "".join(
        f"{cell:{align}{width}}" for cell, (_, width, align) in zip(cells, _COLUMNS, strict=True)
    )


def _phase_cells(phase: PhaseResult) -> list[str]:
    latency = phase.latency_ms
    ops = f"{phase.ops:,}"
    if phase.truncated or phase.ops + phase.errors < phase.requested:
        ops = f"{ops}/{phase.requested:,}"
    cells = [
        phase.name,
        ops,
        str(phase.errors),
        f"{phase.elapsed:.2f}s",
        f"{phase.ops_per_sec:,.1f}",
        f"{phase.mib_per_sec:,.1f}" if phase.total_bytes else "-",
    ]
    for key in ("p50", "p90", "p99", "max"):
        cells.append(f"{latency[key]:.3f}" if latency else "-")
    return cells


def render_text(report: ServiceReport) -> str:
    """The default human-readable rendering of one service's run."""
    params = "  ".join(f"{k}={v}" for k, v in report.params.items())
    lines = [
        "",
        f"{report.service}  {report.target}  run {report.run_id}",
        f"  {params}",
        "",
        _row([name for name, _, _ in _COLUMNS]),
    ]
    for phase in report.phases:
        lines.append(_row(_phase_cells(phase)))
        if phase.truncated:
            lines.append(f"  {phase.name}: stopped early at the --duration cap")
        if phase.sample_label != "op":
            lines.append(f"  {phase.name}: latency is per {phase.sample_label}, throughput per op")
        for message, count in sorted(phase.error_counts.items(), key=lambda kv: -kv[1])[
            :_ERRORS_SHOWN
        ]:
            lines.append(f"  {phase.name}: {count} x {message}")
    lines.extend(f"  note: {note}" for note in report.notes)
    return "\n".join(lines)


def to_dict(report: ServiceReport) -> dict[str, Any]:
    """JSON-serialisable form, for comparing runs across hosts."""
    return {
        "service": report.service,
        "target": report.target,
        "run_id": report.run_id,
        "started_at": report.started_at,
        "params": report.params,
        "notes": list(report.notes),
        "phases": [
            {
                "name": phase.name,
                "ops": phase.ops,
                "requested": phase.requested,
                "errors": phase.errors,
                "error_counts": dict(phase.error_counts),
                "elapsed_s": phase.elapsed,
                "ops_per_sec": phase.ops_per_sec,
                "bytes": phase.total_bytes,
                "mib_per_sec": phase.mib_per_sec,
                "latency_ms": phase.latency_ms,
                "sample_label": phase.sample_label,
                "truncated": phase.truncated,
            }
            for phase in report.phases
        ],
    }
