#!/usr/bin/env python3
"""Benchmark Kafka: produce throughput, consume throughput, round-trip latency.

Run with: uv run python -m benchmark.kafka_bench --host <hostname>
"""

from __future__ import annotations

import argparse
import textwrap
import time
from collections import Counter
from typing import Any

from benchmark import cli
from benchmark.harness import error_label, make_payload
from benchmark.report import ServiceReport
from benchmark.stats import PhaseResult
from benchmark.targets import resolve
from dashboard.clients import make_kafka_admin
from dashboard.config import KafkaConfig

DEFAULT_OPS = 20_000
DEFAULT_PAYLOAD = 1024
DEFAULT_E2E_OPS = 100

# Addresses that only ever mean "this machine". A broker advertising one of
# these is unusable from anywhere else.
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

_FLUSH_TIMEOUT = 30.0
_POLL_TIMEOUT = 1.0
# Consecutive empty polls before a drain gives up, so a consumer never spins
# forever against a topic that will not deliver the rest.
_MAX_EMPTY_POLLS = 10

_ADVERTISED_HELP = textwrap.dedent(
    """\
    The broker accepted the connection and then told the client to reconnect
    to {advertised!r}, which on this machine means this machine. Kafka hands
    out the address in KAFKA_ADVERTISED_LISTENERS, and it has to resolve for
    the client, not for the broker.

    Fix it one of these ways:
      1. Set KAFKA_ADVERTISED_HOST={requested} in .env and `make restart`.
      2. Run the benchmark on the host itself with --host localhost.
      3. Tunnel: ssh -L 9092:localhost:9092 {requested}, then --host localhost.

    Re-run with --force to benchmark anyway (it will almost certainly time out).
    """
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--partitions", type=cli.positive_int, default=1)
    parser.add_argument(
        "--acks",
        choices=("0", "1", "all"),
        default="1",
        help="durability the producer waits for (default 1)",
    )
    parser.add_argument("--linger-ms", type=cli.non_negative_int, default=0)
    parser.add_argument("--batch-size", type=cli.positive_int, default=16384)
    parser.add_argument(
        "--compression",
        choices=("none", "gzip", "snappy", "lz4", "zstd"),
        default="none",
    )
    parser.add_argument(
        "--key-mode",
        choices=("none", "seq"),
        default="seq",
        help="seq spreads messages across partitions; none lets librdkafka clump them",
    )
    parser.add_argument(
        "--address-family",
        choices=("any", "v4", "v6"),
        default="any",
        help="v4 avoids the IPv6 retry noise when the stack binds 127.0.0.1",
    )
    parser.add_argument("--e2e", action="store_true", help="add a produce-to-consume latency phase")
    parser.add_argument("--e2e-ops", type=cli.positive_int, default=DEFAULT_E2E_OPS)
    parser.add_argument("--force", action="store_true", help="run even if preflight objects")


def advertised_mismatch(broker_hosts: list[str], requested_host: str) -> str | None:
    """Explain why brokers advertising ``broker_hosts`` are unreachable, or None.

    Pure by design — it compares against a literal set instead of resolving
    DNS — so the check that saves everyone twenty minutes is unit-testable.
    """
    if requested_host.lower() in LOOPBACK:
        return None
    loopback = [h for h in broker_hosts if h.lower() in LOOPBACK]
    if not loopback:
        return None
    return _ADVERTISED_HELP.format(advertised=loopback[0], requested=requested_host)


def wait_for_leaders(admin: Any, topic: str, partitions: int, timeout: float = 30.0) -> None:
    """Block until every partition has an elected leader.

    ``create_topics`` resolving only means the controller accepted the topic.
    Producing before the leaders are in place returns UNKNOWN_TOPIC_OR_PART,
    and librdkafka's retry lands on its metadata refresh interval — seconds of
    it, straight into the p99.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        meta = admin.list_topics(topic=topic, timeout=5).topics.get(topic)
        if (
            meta is not None
            and meta.error is None
            and len(meta.partitions) == partitions
            and all(p.error is None and p.leader >= 0 for p in meta.partitions.values())
        ):
            return
        time.sleep(0.2)
    raise cli.PreflightError(f"topic {topic} had no partition leaders after {timeout:g}s")


def _preflight(admin: Any, cfg: KafkaConfig, host: str, force: bool) -> list[str]:
    try:
        metadata = admin.list_topics(timeout=10)
    except Exception as exc:
        raise cli.PreflightError(f"cannot reach Kafka at {cfg.bootstrap_servers} — {exc}") from exc

    brokers = [f"{b.id} -> {b.host}:{b.port}" for b in metadata.brokers.values()]
    # Always printed: seeing the advertised address turns this whole class of
    # problem from a mystery into something obvious.
    print(f"brokers advertised by {cfg.bootstrap_servers}: {', '.join(brokers) or 'none'}")

    problem = advertised_mismatch([b.host for b in metadata.brokers.values()], host)
    if problem and not force:
        raise cli.PreflightError(problem)
    return [problem.splitlines()[0]] if problem else []


def _producer(cfg: KafkaConfig, args: argparse.Namespace) -> Any:
    """Producer with the knobs this benchmark varies.

    Built here rather than via :func:`dashboard.clients.make_kafka_producer`
    because acks, linger and batch size are the point. Idempotence is left off
    on purpose: enabling it silently forces acks=all and would override --acks.
    """
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": cfg.bootstrap_servers,
            "acks": args.acks,
            "linger.ms": args.linger_ms,
            "batch.size": args.batch_size,
            "compression.type": args.compression,
            "broker.address.family": args.address_family,
        }
    )


def _consumer(cfg: KafkaConfig, group_id: str, address_family: str) -> Any:
    """Consumer matching :func:`dashboard.clients.make_kafka_consumer`.

    Same three settings it applies — earliest offsets and partition EOF events,
    which a drain loop needs — plus the address family, which the factory has
    no way to pass through.
    """
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": cfg.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.partition.eof": True,
            "broker.address.family": address_family,
        }
    )


def _produce_phase(
    producer: Any,
    topic: str,
    count: int,
    payload: bytes,
    key_mode: str,
    duration_cap: float | None,
) -> PhaseResult:
    latencies: list[float] = []
    errors: Counter[str] = Counter()

    def on_delivery(err: Any, msg: Any) -> None:
        if err is not None:
            errors[str(err)[:120]] += 1
            return
        # librdkafka records produce() -> ack itself, batching wait included.
        # Timing the produce() call would measure the enqueue and nothing else.
        latency = msg.latency()
        if latency is not None:
            latencies.append(latency)

    truncated = False
    start = time.perf_counter()
    for i in range(count):
        if duration_cap is not None and time.perf_counter() - start > duration_cap:
            truncated = True
            break
        key = str(i).encode() if key_mode == "seq" else None
        while True:
            try:
                producer.produce(topic, value=payload, key=key, on_delivery=on_delivery)
                break
            except BufferError:
                # queue.buffering.max.messages is full; drain and try again.
                producer.poll(0.5)
            except Exception as exc:
                errors[error_label(exc)] += 1
                break
        # Delivery callbacks only fire from inside poll() or flush(); without
        # this they would all queue up until the flush below.
        producer.poll(0)

    remaining = producer.flush(timeout=_FLUSH_TIMEOUT)
    # The throughput denominator has to include the flush, or with --linger-ms
    # set this would report the enqueue rate.
    elapsed = time.perf_counter() - start
    if remaining:
        errors[f"{remaining} messages still undelivered at flush"] += remaining

    return PhaseResult(
        name="produce",
        requested=count,
        elapsed=elapsed,
        latencies=tuple(latencies),
        error_counts=dict(errors),
        total_bytes=len(latencies) * len(payload),
        truncated=truncated,
    )


def _consume_phase(
    consumer: Any, topic: str, expected: int, duration_cap: float | None
) -> PhaseResult:
    from confluent_kafka import KafkaError

    consumer.subscribe([topic])
    latencies: list[float] = []
    errors: Counter[str] = Counter()
    eof: set[int] = set()
    total_bytes = 0
    empty_polls = 0
    truncated = False
    start = time.perf_counter()

    while len(latencies) < expected:
        if duration_cap is not None and time.perf_counter() - start > duration_cap:
            truncated = True
            break
        poll_start = time.perf_counter()
        msg = consumer.poll(_POLL_TIMEOUT)
        waited = time.perf_counter() - poll_start
        if msg is None:
            empty_polls += 1
            if empty_polls >= _MAX_EMPTY_POLLS:
                break
            continue
        empty_polls = 0
        if msg.error() is not None:
            if msg.error().code() == KafkaError._PARTITION_EOF:
                # Every assigned partition must report EOF, not just the first:
                # stopping on one would truncate any multi-partition run.
                eof.add(msg.partition())
                if eof >= {p.partition for p in consumer.assignment()}:
                    break
                continue
            errors[str(msg.error())[:120]] += 1
            continue
        latencies.append(waited)
        total_bytes += len(msg.value() or b"")

    elapsed = time.perf_counter() - start
    return PhaseResult(
        name="consume",
        requested=expected,
        elapsed=elapsed,
        latencies=tuple(latencies),
        error_counts=dict(errors),
        total_bytes=total_bytes,
        truncated=truncated,
    )


def _e2e_phase(
    producer: Any, consumer: Any, topic: str, count: int, payload: bytes, warmup: int = 3
) -> PhaseResult:
    """Produce one message, wait for it to come back, repeat.

    A strict ping-pong rather than a timestamp embedded in the bulk run: with
    everything produced first, message zero's "end-to-end latency" would
    include the entire produce phase. One clock, one process, so
    ``perf_counter`` is valid on both sides.
    """
    from confluent_kafka import KafkaError

    consumer.subscribe([topic])
    deadline = time.perf_counter() + 30
    while not consumer.assignment() and time.perf_counter() < deadline:
        consumer.poll(0.5)
    if not consumer.assignment():
        raise cli.PreflightError(f"consumer was never assigned a partition of {topic}")

    latencies: list[float] = []
    errors: Counter[str] = Counter()

    # Untimed round trips first: the first one pays for group coordination and
    # the first fetch, which would otherwise be the whole tail of this phase.
    for i in range(warmup):
        producer.produce(topic, value=payload, key=f"warmup-{i}".encode())
        producer.flush(timeout=_FLUSH_TIMEOUT)
        consumer.poll(5.0)

    start = time.perf_counter()
    for i in range(count):
        sent = time.perf_counter()
        producer.produce(topic, value=payload, key=str(i).encode())
        producer.flush(timeout=_FLUSH_TIMEOUT)
        while True:
            msg = consumer.poll(5.0)
            if msg is None:
                errors["timed out waiting for the message to come back"] += 1
                break
            if msg.error() is not None:
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                errors[str(msg.error())[:120]] += 1
                break
            latencies.append(time.perf_counter() - sent)
            break

    return PhaseResult(
        name="e2e",
        requested=count,
        elapsed=time.perf_counter() - start,
        latencies=tuple(latencies),
        error_counts=dict(errors),
        total_bytes=len(latencies) * len(payload),
    )


def _create_topic(admin: Any, name: str, partitions: int) -> None:
    from confluent_kafka.admin import NewTopic

    spec = NewTopic(name, num_partitions=partitions, replication_factor=1)
    for topic, future in admin.create_topics([spec]).items():
        try:
            # create_topics returns futures; without resolving them, errors —
            # including TOPIC_ALREADY_EXISTS — are silently swallowed.
            future.result()
        except Exception as exc:
            raise cli.PreflightError(f"could not create topic {topic}: {exc}") from exc
    wait_for_leaders(admin, name, partitions)


def _delete_topics(admin: Any, names: list[str]) -> str:
    failures = []
    for topic, future in admin.delete_topics(names, operation_timeout=30).items():
        try:
            future.result()
        except Exception as exc:
            failures.append(f"{topic} ({exc})")
    if failures:
        return f"could not delete {', '.join(failures)} — remove them by hand"
    return f"deleted topic{'s' if len(names) > 1 else ''} {', '.join(names)}"


def run(args: argparse.Namespace, /) -> ServiceReport:
    targets = resolve(args)
    cfg = targets.kafka
    ops = args.ops or DEFAULT_OPS
    size = args.payload_size or DEFAULT_PAYLOAD
    run_id = cli.new_run_id()
    topic = f"bench-{run_id}"
    payload = make_payload(size)

    admin = make_kafka_admin(cfg)
    notes = _preflight(admin, cfg, targets.host, args.force)
    notes.append("produce and consume are single-threaded; librdkafka batches internally")
    if args.acks == "all":
        notes.append("acks=all matches acks=1 on this stack: one broker, replication factor 1")

    topics = [topic]
    _create_topic(admin, topic, args.partitions)
    producer = _producer(cfg, args)
    phases: list[PhaseResult] = []
    try:
        if args.e2e:
            # Its own topic, so the ping-pong is not walking through the bulk
            # run's backlog.
            e2e_topic = f"bench-e2e-{run_id}"
            _create_topic(admin, e2e_topic, 1)
            topics.append(e2e_topic)
            consumer = _consumer(cfg, f"bench-e2e-{run_id}", args.address_family)
            try:
                phases.append(_e2e_phase(producer, consumer, e2e_topic, args.e2e_ops, payload))
            finally:
                consumer.close()

        produced = _produce_phase(producer, topic, ops, payload, args.key_mode, args.duration)
        phases.append(produced)

        consumer = _consumer(cfg, f"bench-{run_id}", args.address_family)
        try:
            phases.append(_consume_phase(consumer, topic, produced.ops, args.duration))
        finally:
            consumer.close()
        notes.append(
            "consume latency is the wait for each message at the client, not broker "
            "latency; use --e2e for produce-to-consume"
        )
        notes.append(
            "produce latency includes time queued in the producer, so at saturation it "
            "reflects the backlog rather than broker service time"
        )
    finally:
        if args.keep:
            notes.append(f"--keep: left topic{'s' if len(topics) > 1 else ''} {', '.join(topics)}")
        else:
            notes.append(_delete_topics(admin, topics))

    return ServiceReport(
        service="Kafka",
        target=cfg.bootstrap_servers,
        run_id=run_id,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        params={
            "ops": ops,
            "payload": f"{size}B",
            "partitions": args.partitions,
            "acks": args.acks,
            "linger_ms": args.linger_ms,
            "compression": args.compression,
        },
        phases=tuple(phases),
        notes=tuple(notes),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, parents=[cli.shared_parser()])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return cli.execute([("kafka", run)], args)


if __name__ == "__main__":
    raise SystemExit(main())
