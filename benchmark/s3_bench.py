#!/usr/bin/env python3
"""Benchmark the Floci S3 endpoint: PUT, GET, LIST and DELETE.

Run with: uv run python -m benchmark.s3_bench --host <hostname>
"""

from __future__ import annotations

import argparse
import contextlib
import threading
import time
from typing import Any

from benchmark import cli
from benchmark.harness import PhaseOptions, make_payload, run_phase
from benchmark.report import ServiceReport
from benchmark.stats import PhaseResult
from benchmark.targets import resolve
from dashboard import s3
from dashboard.config import S3Config

DEFAULT_OPS = 100
DEFAULT_PAYLOAD = 1024 * 1024
DEFAULT_BUCKET = "benchmark"

# LIST is cheap and its cost barely varies, so a full --ops worth of calls
# would just pad the run.
MAX_LIST_OPS = 50

_local = threading.local()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help=f"default {DEFAULT_BUCKET}")


def make_client(cfg: S3Config, pool_size: int) -> Any:
    """A boto3 client configured for measurement.

    Mirrors :func:`dashboard.clients.make_s3_client` — same endpoint, same
    credentials, same mandatory path-style addressing, which Floci requires at
    the container endpoint — but pins two defaults that would otherwise distort
    the numbers:

    * botocore retries a failed S3 call up to five times, which turns an error
      into a single very slow success and quietly corrupts both the p99 and the
      error count;
    * the connection pool holds ten sockets, so anything above that concurrency
      serialises on pool checkout instead of on the service.
    """
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        region_name=cfg.region,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        config=BotoConfig(
            s3={"addressing_style": "path"},
            retries={"mode": "standard", "total_max_attempts": 1},
            max_pool_connections=pool_size,
        ),
    )


def _thread_client(cfg: S3Config, pool_size: int) -> Any:
    """One client per worker thread — boto3 clients are not thread-safe."""
    client = getattr(_local, "client", None)
    if client is None:
        client = make_client(cfg, pool_size)
        _local.client = client
    return client


def _sweep(client: Any, bucket: str, keys: list[str]) -> None:
    """Delete exactly the keys this run created.

    Deliberately not a prefix scan: working from the in-memory list makes it
    structurally impossible to remove anything the benchmark did not write.

    Returns nothing on purpose. S3 answers 204 whether or not the key was
    there, so a count of successful calls would say "removed 40 objects" for a
    prefix that was already empty.
    """
    for key in keys:
        with contextlib.suppress(Exception):
            s3.delete_object(client, bucket, key)


def _delete_phase_covered_everything(phases: list[PhaseResult], expected: int) -> bool:
    delete = next((p for p in phases if p.name == "delete"), None)
    return delete is not None and delete.ops == expected and not delete.errors


def run(args: argparse.Namespace, /) -> ServiceReport:
    targets = resolve(args)
    cfg = targets.s3
    ops = args.ops or DEFAULT_OPS
    size = args.payload_size or DEFAULT_PAYLOAD
    warmup = cli.default_warmup(ops, args.warmup)
    run_id = cli.new_run_id()
    prefix = f"bench/{run_id}/"
    keys = [f"{prefix}obj-{i:06d}" for i in range(ops)]
    payload = make_payload(size)

    # Each worker gets its own small pool rather than all of them sharing one.
    pool_size = max(2, min(args.concurrency, 8))
    control = make_client(cfg, pool_size)
    try:
        buckets = s3.list_buckets(control)
    except Exception as exc:
        raise cli.PreflightError(f"cannot reach S3 at {cfg.endpoint_url} — {exc}") from exc
    if args.bucket not in buckets:
        # create_bucket handles the us-east-1 LocationConstraint special case.
        s3.create_bucket(control, args.bucket, cfg.region)

    def setup() -> None:
        _thread_client(cfg, pool_size)

    def do_put(i: int) -> int:
        s3.put_object(_thread_client(cfg, pool_size), args.bucket, keys[i], payload)
        return size

    def do_get(i: int) -> int:
        # dashboard.s3.get_object reads the body, so the transfer is timed.
        return len(s3.get_object(_thread_client(cfg, pool_size), args.bucket, keys[i]))

    def do_list(_: int) -> int:
        client = _thread_client(cfg, pool_size)
        s3.list_objects(client, args.bucket, prefix=prefix, limit=1000)
        return 0

    def do_delete(i: int) -> int:
        s3.delete_object(_thread_client(cfg, pool_size), args.bucket, keys[i])
        return 0

    phases: list[PhaseResult] = []
    notes: list[str] = []
    common: PhaseOptions = {
        "concurrency": args.concurrency,
        "duration_cap": args.duration,
        "setup": setup,
    }
    try:
        phases.append(run_phase("put", do_put, total_ops=ops, warmup=warmup, **common))
        phases.append(run_phase("get", do_get, total_ops=ops, warmup=warmup, **common))
        list_ops = min(ops, MAX_LIST_OPS)
        phases.append(run_phase("list", do_list, total_ops=list_ops, warmup=1, **common))
        if not args.keep:
            # No warmup: a warmup pass would delete the objects the timed pass
            # is about to delete, and S3 answers 204 either way, so the phase
            # would look fast while doing nothing.
            phases.append(run_phase("delete", do_delete, total_ops=ops, warmup=0, **common))
    finally:
        if args.keep:
            notes.append(f"--keep: left {len(keys)} objects under s3://{args.bucket}/{prefix}")
        elif not _delete_phase_covered_everything(phases, len(keys)):
            # The delete phase is the cleanup; this only runs when it did not
            # finish, so the run never leaves objects behind.
            _sweep(control, args.bucket, keys)
            notes.append(f"the delete phase did not finish; swept s3://{args.bucket}/{prefix}")

    notes.append(f"bucket {args.bucket} is reused between runs and never deleted")
    return ServiceReport(
        service="S3 (Floci)",
        target=cfg.endpoint_url,
        run_id=run_id,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        params={
            "ops": ops,
            "concurrency": args.concurrency,
            "payload": f"{s3.human_size(size)}",
            "warmup": warmup,
            "bucket": args.bucket,
        },
        phases=tuple(phases),
        notes=tuple(notes),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, parents=[cli.shared_parser()])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return cli.execute([("s3", run)], args)


if __name__ == "__main__":
    raise SystemExit(main())
