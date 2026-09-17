#!/usr/bin/env python3
"""Benchmark Valkey: round-trip floor, SET, GET, and optional pipelining.

Run with: uv run python -m benchmark.valkey_bench --host <hostname>
"""

from __future__ import annotations

import argparse
import contextlib
import time
from typing import Any

from benchmark import cli
from benchmark.harness import PhaseOptions, make_payload, run_phase
from benchmark.report import ServiceReport
from benchmark.stats import PhaseResult
from benchmark.targets import resolve
from dashboard.clients import make_valkey_client

DEFAULT_OPS = 10_000
DEFAULT_PAYLOAD = 512

# UNLINK reclaims memory on a background thread; DEL blocks the server. Chunked
# so a large run does not build one enormous command.
_CLEANUP_CHUNK = 500


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pipeline",
        type=cli.positive_int,
        default=1,
        help="commands per round trip; >1 adds pipelined SET/GET phases",
    )


def _keys(run_id: str, count: int) -> list[str]:
    return [f"bench:{run_id}:key:{i:07d}" for i in range(count)]


def _cleanup(client: Any, keys: list[str]) -> int:
    removed = 0
    for start in range(0, len(keys), _CLEANUP_CHUNK):
        chunk = keys[start : start + _CLEANUP_CHUNK]
        try:
            removed += int(client.unlink(*chunk))
        except Exception:
            # Older servers, or a server built without UNLINK.
            with contextlib.suppress(Exception):
                removed += int(client.delete(*chunk))
    return removed


def run(args: argparse.Namespace, /) -> ServiceReport:
    targets = resolve(args)
    cfg = targets.valkey
    ops = args.ops or DEFAULT_OPS
    size = args.payload_size or DEFAULT_PAYLOAD
    warmup = cli.default_warmup(ops, args.warmup)
    run_id = cli.new_run_id()
    payload = make_payload(size)
    keys = _keys(run_id, ops)

    # One client for the whole run, shared by every thread. valkey-py is
    # thread-safe and checks a connection out of its own pool per command; a
    # client per thread would mean a pool per thread.
    client = make_valkey_client(cfg, timeout=args.timeout)
    try:
        client.ping()
    except Exception as exc:
        raise cli.PreflightError(f"cannot reach Valkey at {cfg.host}:{cfg.port} — {exc}") from exc

    def do_ping(_: int) -> int:
        client.ping()
        return 0

    def do_set(i: int) -> int:
        client.set(keys[i], payload)
        return size

    def do_get(i: int) -> int:
        value = client.get(keys[i])
        if value is None:
            # Not a fast success: a missing key means the wrong server, or
            # eviction mid-run. Counting it as a hit would report a fantastic
            # GET rate for a server that is storing nothing.
            raise KeyError(keys[i])
        return len(value)

    phases: list[PhaseResult] = []
    notes: list[str] = []
    common: PhaseOptions = {"concurrency": args.concurrency, "duration_cap": args.duration}
    try:
        phases.append(run_phase("ping", do_ping, total_ops=min(ops, 1000), warmup=warmup, **common))
        phases.append(run_phase("set", do_set, total_ops=ops, warmup=warmup, **common))
        phases.append(run_phase("get", do_get, total_ops=ops, warmup=warmup, **common))

        if args.pipeline > 1:
            phases.extend(_pipelined(args, client, keys, payload, size, common))
            notes.append(
                "pipelined phases use transaction=False; MULTI/EXEC would measure "
                "transaction overhead instead of pipelining"
            )
    finally:
        if args.keep:
            notes.append(f"--keep: left {len(keys)} keys under bench:{run_id}:")
        else:
            notes.append(f"cleaned up {_cleanup(client, keys)} keys")

    return ServiceReport(
        service="Valkey",
        target=f"{cfg.host}:{cfg.port}",
        run_id=run_id,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        params={
            "ops": ops,
            "concurrency": args.concurrency,
            "payload": f"{size}B",
            "warmup": warmup,
            "pipeline": args.pipeline,
        },
        phases=tuple(phases),
        notes=tuple(notes),
    )


def _pipelined(
    args: argparse.Namespace,
    client: Any,
    keys: list[str],
    payload: bytes,
    size: int,
    common: PhaseOptions,
) -> list[PhaseResult]:
    """SET and GET again, batched ``--pipeline`` commands per round trip.

    Operations are truncated to a whole number of batches so the throughput
    figure counts exactly the commands that were sent.
    """
    depth = args.pipeline
    batches = len(keys) // depth
    if batches == 0:
        return []

    def batch_set(b: int) -> int:
        lo = b * depth
        with client.pipeline(transaction=False) as pipe:
            for key in keys[lo : lo + depth]:
                pipe.set(key, payload)
            pipe.execute()
        return size * depth

    def batch_get(b: int) -> int:
        lo = b * depth
        with client.pipeline(transaction=False) as pipe:
            for key in keys[lo : lo + depth]:
                pipe.get(key)
            values = pipe.execute()
        if any(v is None for v in values):
            raise KeyError(f"missing keys in batch {b}")
        return sum(len(v) for v in values)

    warmup = max(1, cli.default_warmup(batches, args.warmup) // depth)
    batched: PhaseOptions = {"ops_per_call": depth, **common}
    return [
        run_phase("set-pipe", batch_set, total_ops=batches, warmup=warmup, **batched),
        run_phase("get-pipe", batch_get, total_ops=batches, warmup=warmup, **batched),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, parents=[cli.shared_parser()])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return cli.execute([("valkey", run)], args)


if __name__ == "__main__":
    raise SystemExit(main())
