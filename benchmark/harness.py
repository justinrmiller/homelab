"""Thread-pool driver shared by every benchmark.

One thread per *worker*, not per operation. Submitting a task per operation
would cost tens of microseconds each, the same order as a local Valkey round
trip, so the executor would be a large part of what got measured. Each worker
takes a contiguous slice of the index space and loops over it in-thread.

The threads are explicit rather than a ``ThreadPoolExecutor``: a pool only
spawns a worker when no existing one is idle, so with fast operations a single
thread can drain every slice and ``--concurrency`` silently becomes 1.
"""

from __future__ import annotations

import contextlib
import math
import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from benchmark.stats import PhaseResult

# Takes the operation's index, returns the bytes it moved (0 when it moves no
# payload, such as a PING or a LIST).
Operation = Callable[[int], int]


class PhaseOptions(TypedDict, total=False):
    """The run_phase arguments a service module reuses across its phases.

    ``warmup`` is deliberately absent: it varies per phase and is always
    passed explicitly.
    """

    concurrency: int
    duration_cap: float | None
    setup: Callable[[], None] | None
    ops_per_call: int


# Error labels are keyed in a Counter rather than accumulated in a list: a
# 100k-op run against a dead service should not build 100k strings.
_LABEL_MAX = 120


def make_payload(size: int) -> bytes:
    """A random buffer, generated once and reused for every op in a phase.

    Random so it is incompressible and no backend can flatter itself on the
    wire. Generated once because the benchmark measures the service, not the
    system CSPRNG.
    """
    return os.urandom(size)


def error_label(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_LABEL_MAX]


def slice_bounds(total: int, workers: int, index: int) -> tuple[int, int]:
    """Half-open index range for worker ``index``, distributing the remainder."""
    base, extra = divmod(total, workers)
    start = index * base + min(index, extra)
    return start, start + base + (1 if index < extra else 0)


@dataclass
class _Outcome:
    latencies: list[float]
    errors: Counter[str]
    total_bytes: int
    start: float
    end: float
    truncated: bool


def run_phase(
    name: str,
    op: Operation,
    *,
    total_ops: int,
    concurrency: int = 1,
    warmup: int = 0,
    duration_cap: float | None = None,
    setup: Callable[[], None] | None = None,
    ops_per_call: int = 1,
) -> PhaseResult:
    """Run ``op`` over ``range(total_ops)`` and measure it.

    ``setup`` runs once per worker thread before any timing, for per-thread
    state such as a boto3 client. ``warmup`` operations run on those same
    threads, through the same code path, with their results discarded.
    """
    workers = max(1, min(concurrency, total_ops)) if total_ops else 1
    per_worker_warmup = math.ceil(warmup / workers) if warmup > 0 else 0

    def work(index: int) -> _Outcome:
        if setup is not None:
            setup()
        start_i, end_i = slice_bounds(total_ops, workers, index)
        indices = range(start_i, end_i)

        # Warmup on the worker's own thread pays for the TCP connect, for
        # botocore building its endpoint and serializer on first call, and for
        # the Valkey pool filling. Untimed, or the p99 is just "the first call".
        for i in list(indices)[:per_worker_warmup]:
            with contextlib.suppress(Exception):
                op(i)

        latencies: list[float] = []
        errors: Counter[str] = Counter()
        total_bytes = 0
        truncated = False
        start = time.perf_counter()
        for i in indices:
            if duration_cap is not None and time.perf_counter() - start > duration_cap:
                truncated = True
                break
            call_start = time.perf_counter()
            try:
                moved = op(i)
            except Exception as exc:
                # A failed op records no latency: the duration of a failure is
                # meaningless and would skew the percentiles.
                errors[error_label(exc)] += 1
                continue
            latencies.append(time.perf_counter() - call_start)
            total_bytes += moved
        return _Outcome(latencies, errors, total_bytes, start, time.perf_counter(), truncated)

    if total_ops <= 0:
        return PhaseResult(name=name, requested=0, elapsed=0.0, ops_per_call=ops_per_call)

    collected: dict[int, _Outcome] = {}
    lock = threading.Lock()

    def runner(index: int) -> None:
        try:
            outcome = work(index)
        except Exception as exc:
            # Only reachable if `setup` fails; per-op failures are handled
            # inside `work`. Record it rather than losing the thread silently.
            now = time.perf_counter()
            outcome = _Outcome([], Counter({error_label(exc): 1}), 0, now, now, False)
        with lock:
            collected[index] = outcome

    threads = [
        threading.Thread(target=runner, args=(i,), name=f"bench-{name}-{i}") for i in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    outcomes = [collected[i] for i in sorted(collected)]

    latencies: list[float] = []
    errors: Counter[str] = Counter()
    for outcome in outcomes:
        latencies.extend(outcome.latencies)
        errors.update(outcome.errors)

    # Wall clock across all workers, never the sum of the latencies: at
    # concurrency 8 the latency sum would report an eighth of the real rate.
    elapsed = max(o.end for o in outcomes) - min(o.start for o in outcomes)

    return PhaseResult(
        name=name,
        requested=total_ops * ops_per_call,
        elapsed=elapsed,
        latencies=tuple(latencies),
        error_counts=dict(errors),
        total_bytes=sum(o.total_bytes for o in outcomes),
        truncated=any(o.truncated for o in outcomes),
        ops_per_call=ops_per_call,
    )
