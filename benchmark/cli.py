"""Shared command-line surface for the benchmark modules.

Every service module builds its parser from :func:`shared_parser`, so the
flags that mean the same thing everywhere are declared exactly once and the
combined runner in ``benchmark.__main__`` can reuse them too.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from benchmark.report import ServiceReport, render_text, to_dict

EXIT_OK = 0
EXIT_ERRORS = 1
# 2 is argparse's own usage error.
EXIT_PREFLIGHT = 3

_SUFFIXES = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024 * 1024,
    "mb": 1024 * 1024,
    "mib": 1024 * 1024,
}


def parse_size(text: str) -> int:
    """Parse a byte size such as ``512``, ``4k`` or ``1MiB``."""
    raw = text.strip().lower()
    digits = raw.rstrip("abikm")
    suffix = raw[len(digits) :]
    if not digits or suffix not in _SUFFIXES:
        raise argparse.ArgumentTypeError(f"not a byte size: {text!r} (try 512, 4k, 1MiB)")
    try:
        value = int(digits)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a byte size: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("size must be positive")
    return value * _SUFFIXES[suffix]


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def shared_parser() -> argparse.ArgumentParser:
    """Flags common to every benchmark, for use as an argparse parent.

    ``--ops`` and ``--payload-size`` default to ``None`` so each service can
    apply its own sensible figure: 100 objects of 1 MiB is a reasonable S3 run
    and a hopeless Valkey one.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--host", help="hostname running the stack (default: from the environment, else localhost)"
    )
    parser.add_argument("--s3-port", type=positive_int, help="default 4566")
    parser.add_argument("--valkey-port", type=positive_int, help="default 6379")
    parser.add_argument("--kafka-port", type=positive_int, help="default 9092")
    parser.add_argument("--ops", type=positive_int, help="operations per phase")
    parser.add_argument("--concurrency", type=positive_int, default=4, help="worker threads")
    parser.add_argument("--payload-size", type=parse_size, help="bytes per value, e.g. 4k")
    parser.add_argument(
        "--warmup", type=non_negative_int, help="untimed ops first (default: a tenth of --ops)"
    )
    parser.add_argument("--duration", type=float, help="per-phase wall-clock cap in seconds")
    parser.add_argument("--timeout", type=float, default=5.0, help="connection timeout in seconds")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--out", type=Path, help="also write JSON here")
    parser.add_argument("--keep", action="store_true", help="leave benchmark data in place")
    return parser


def default_warmup(ops: int, requested: int | None) -> int:
    """Warmup count: what was asked for, else a tenth of the run, capped."""
    if requested is not None:
        return requested
    return min(100, max(1, ops // 10))


def new_run_id() -> str:
    """Timestamped, unique, and safe as both an S3 key part and a topic name."""
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def emit(reports: list[ServiceReport], args: argparse.Namespace) -> None:
    """Print the reports and honour ``--json`` / ``--out``."""
    payload = {"schema": 1, "runs": [to_dict(r) for r in reports]}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for report in reports:
            print(render_text(report))
    if args.out is not None:
        args.out.write_text(json.dumps(payload, indent=2) + "\n")
        if not args.json:
            print(f"Wrote {args.out}")


def exit_code(reports: list[ServiceReport]) -> int:
    failed = any(phase.errors for report in reports for phase in report.phases)
    return EXIT_ERRORS if failed else EXIT_OK


class PreflightError(RuntimeError):
    """The service could not be reached, or is misconfigured for this run.

    Raised before any measurement, so the caller can report the cause and exit
    ``EXIT_PREFLIGHT`` instead of producing a table of zeros.
    """


def execute(
    runners: Sequence[tuple[str, Callable[[argparse.Namespace], ServiceReport]]],
    args: argparse.Namespace,
) -> int:
    """Run each service in turn, report everything, return the exit code.

    A preflight failure in one service does not stop the others: when three
    services are being compared, two answers beat none.
    """
    reports: list[ServiceReport] = []
    failures = 0
    for name, runner in runners:
        try:
            reports.append(runner(args))
        except PreflightError as exc:
            print(f"error: {name}: {exc}")
            failures += 1
        except KeyboardInterrupt:
            # The runners clean up in a finally block, so this is safe to
            # report as a tidy stop rather than a crash.
            print(f"\n{name}: interrupted, benchmark data cleaned up")
            return 130
    if reports:
        emit(reports, args)
    return EXIT_PREFLIGHT if failures else exit_code(reports)
