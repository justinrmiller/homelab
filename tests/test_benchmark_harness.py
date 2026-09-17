"""The thread-pool driver: slicing, warmup, error capture, duration cap."""

from __future__ import annotations

import threading
import time

from benchmark.harness import error_label, make_payload, run_phase, slice_bounds


def test_slice_bounds_covers_every_index_exactly_once():
    covered = []
    for worker in range(4):
        start, end = slice_bounds(10, 4, worker)
        covered.extend(range(start, end))
    assert sorted(covered) == list(range(10))


def test_payload_is_the_requested_size_and_random():
    assert len(make_payload(64)) == 64
    assert make_payload(64) != make_payload(64)


def test_error_label_includes_the_exception_type():
    assert error_label(KeyError("missing")).startswith("KeyError:")


def test_happy_path_records_one_latency_per_op():
    result = run_phase("x", lambda _: 8, total_ops=10, concurrency=2)
    assert result.ops == 10
    assert result.errors == 0
    assert len(result.latencies) == 10
    assert result.total_bytes == 80
    assert not result.truncated


def test_every_index_is_visited_once_across_workers():
    seen: list[int] = []
    lock = threading.Lock()

    def op(i: int) -> int:
        with lock:
            seen.append(i)
        return 0

    run_phase("x", op, total_ops=25, concurrency=4)
    assert sorted(seen) == list(range(25))


def test_failures_are_counted_and_contribute_no_latency():
    def op(i: int) -> int:
        if i % 3 == 0:
            raise RuntimeError("boom")
        return 1

    result = run_phase("x", op, total_ops=9, concurrency=1)
    assert result.errors == 3
    assert result.ops == 6
    assert len(result.latencies) == 6
    assert result.error_counts == {"RuntimeError: boom": 3}


def test_warmup_runs_extra_ops_but_records_none_of_them():
    calls: list[int] = []
    lock = threading.Lock()

    def op(i: int) -> int:
        with lock:
            calls.append(i)
        return 0

    result = run_phase("x", op, total_ops=10, concurrency=1, warmup=4)
    assert len(calls) == 14
    assert len(result.latencies) == 10


def test_warmup_failures_do_not_count_as_errors():
    state = {"first": True}

    def op(_: int) -> int:
        if state["first"]:
            state["first"] = False
            raise ConnectionError("cold start")
        return 0

    result = run_phase("x", op, total_ops=3, concurrency=1, warmup=1)
    assert result.errors == 0


def test_duration_cap_stops_early_and_says_so():
    def op(_: int) -> int:
        time.sleep(0.01)
        return 0

    result = run_phase("x", op, total_ops=1000, concurrency=1, duration_cap=0.05)
    assert result.truncated
    assert result.ops < 1000
    assert result.requested == 1000


def test_setup_runs_once_per_worker_thread():
    # Thread idents get recycled as soon as a thread finishes, so a fast phase
    # can report fewer distinct idents than it had workers. The harness names
    # its workers, which is stable.
    names: set[str] = set()
    lock = threading.Lock()

    def setup() -> None:
        with lock:
            names.add(threading.current_thread().name)

    run_phase("x", lambda _: 0, total_ops=20, concurrency=4, setup=setup)
    assert len(names) == 4
    assert all(n.startswith("bench-x-") for n in names)


def test_concurrency_is_real_and_not_a_lazily_grown_pool():
    """Four workers must genuinely overlap, even when each op is instant.

    A ThreadPoolExecutor only spawns a thread when none is idle, so with fast
    ops one thread can drain every slice and --concurrency quietly means 1.
    """
    started = threading.Barrier(4, timeout=5)

    def op(i: int) -> int:
        if i % 5 == 0:
            started.wait()
        return 0

    result = run_phase("x", op, total_ops=20, concurrency=4)
    assert result.errors == 0


def test_zero_ops_returns_an_empty_result():
    result = run_phase("x", lambda _: 0, total_ops=0)
    assert result.ops == 0
    assert result.elapsed == 0.0
    assert result.latency_ms is None
