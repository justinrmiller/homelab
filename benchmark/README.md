# Benchmarks

Throughput and latency for the stack's three data services, against any host
running it.

```sh
make bench HOST=nas.local                 # all three
make bench-valkey HOST=nas.local          # one service
uv run python -m benchmark.s3_bench --host nas.local --ops 200 --payload-size 4m
uv run python -m benchmark --host nas.local --json --out today.json
```

Run them as modules (`python -m benchmark.s3_bench`), not as file paths. Both
work, but `-m` is what the docs and the Makefile use.

## What gets measured

| Service | Phases |
|---|---|
| S3 (Floci) | `put`, `get`, `list`, `delete` |
| Valkey | `ping`, `set`, `get`, plus `set-pipe` / `get-pipe` with `--pipeline N` |
| Kafka | `produce`, `consume`, plus `e2e` with `--e2e` |

`ping` is the pure network round-trip floor. When a remote host looks slow,
compare it against `set` before blaming the service.

## Common flags

| Flag | Default | Notes |
|---|---|---|
| `--host` | environment, else `localhost` | Sets the hostname for every service at once |
| `--s3-port` / `--valkey-port` / `--kafka-port` | 4566 / 6379 / 9092 | |
| `--ops` | per service | S3 100, Valkey 10,000, Kafka 20,000 |
| `--payload-size` | per service | S3 1 MiB, Valkey 512 B, Kafka 1 KiB. Accepts `512`, `4k`, `1MiB` |
| `--concurrency` | 4 | Worker threads. Ignored by Kafka (see below) |
| `--warmup` | a tenth of `--ops`, capped at 100 | Untimed, on the same threads |
| `--duration` | none | Per-phase wall-clock cap, for slow remote hosts |
| `--json` / `--out FILE` | off | Machine-readable output for comparing runs |
| `--keep` | off | Leave the data in place instead of cleaning up |

Service-specific: `--bucket`, `--pipeline`, and for Kafka `--partitions`,
`--acks`, `--linger-ms`, `--batch-size`, `--compression`, `--key-mode`,
`--e2e`, `--e2e-ops`, `--address-family`, `--force`.

If the stack listens on IPv4 only — `BIND_ADDR=127.0.0.1`, say — but
`localhost` resolves to `::1` first, librdkafka logs a connection failure for
every socket before falling back. `--address-family v4` skips that.

## What it touches, and what it cleans up

Every run gets a unique id and namespaces its data under it:

- S3 — keys under `bench/<run-id>/` in the `benchmark` bucket. The bucket is
  created if missing and **never deleted**, so it is reused between runs.
- Valkey — keys under `bench:<run-id>:`, removed with `UNLINK` on the exact
  key list. Never `KEYS`, never `FLUSHALL`.
- Kafka — a `bench-<run-id>` topic, deleted afterwards.

Cleanup works from the list of names the process built in memory, not from a
prefix scan, so it cannot remove anything the benchmark did not create. It runs
in a `finally` block, so Ctrl-C still cleans up. `--keep` skips it.

## How the numbers are produced

- **Throughput is ops ÷ wall-clock elapsed**, measured across all workers.
  Never ops ÷ summed latency, which at concurrency 8 would report an eighth of
  the real rate.
- **Percentiles are nearest-rank**, so every figure is a latency that actually
  occurred rather than an interpolation between two samples.
- **Warmup runs on the worker threads themselves**, through the same code path,
  with results discarded. It pays for the TCP connect, for botocore building
  its endpoint and serializer on first call, and for the Valkey pool filling.
  Without it, the p99 is largely "the first request".
- **A failed operation records no latency** and is counted separately. The
  report prints the most common failure messages under the phase.
- Exit codes: `0` all good, `1` some operations failed, `3` preflight failed
  (unreachable, or misconfigured), `130` interrupted.

## Reading the results

- **Floci is effectively single-threaded.** S3 throughput flattens somewhere
  around `--concurrency 8`. That is a property of the emulator, not a bug in
  the benchmark.
- **`acks=all` matches `acks=1` here.** One broker at replication factor 1 has
  nothing to replicate to. Identical numbers are expected.
- **Pipelined Valkey latency is per batch, not per command.** `--pipeline 10`
  with `--ops 1000` is 100 round trips carrying 1000 commands; throughput
  counts the commands, the percentiles describe the round trip. The report
  labels it. Pipelines use `transaction=False` — valkey-py wraps a pipeline in
  `MULTI`/`EXEC` by default, which would measure transaction overhead instead.
- **Kafka produce and consume are single-threaded on purpose.** librdkafka
  already batches and overlaps internally; wrapping it in a Python thread pool
  adds GIL contention and measures nothing new. `--concurrency` is ignored.
- **Consume latency is the wait for each message at the client**, not broker
  latency. For produce-to-consume, use `--e2e`, which runs a strict ping-pong
  on its own topic. A timestamp embedded in the bulk run would be misleading:
  everything is produced first, so message zero's "latency" would include the
  whole produce phase.
- **Produce latency includes time spent queued in the producer.** A benchmark
  enqueues everything at once, so at saturation the figure reflects the
  backlog draining, not the broker's service time — expect tens of
  milliseconds alongside a high ops/s. `--e2e` measures latency unloaded.
- **Produce latency comes from `Message.latency()`**, which librdkafka records
  from `produce()` to the broker's acknowledgement. Timing the `produce()` call
  would measure the enqueue and nothing else.

## Benchmarking from another machine

Ports bind to `0.0.0.0`, so the only thing standing between you and a remote
run is Kafka not knowing its own name. In `.env` on the host running the stack:

```sh
KAFKA_ADVERTISED_HOST=nas.local   # this host's name, as the client resolves it
```

then `make restart`.

(`BIND_ADDR=127.0.0.1` reverses this and keeps everything on the one machine,
which is worth doing on a network you do not trust — the stack ships with
development credentials.)

Kafka needs that second variable because after bootstrap it hands the client an
address to reconnect to, and that address has to resolve *for the client*. Left
at the default, a remote client is told `localhost` and dials its own loopback.
The Kafka benchmark detects this before doing any work and prints the fix; it
also always prints the brokers' advertised addresses, which is usually enough
to see what is wrong. `--force` overrides the check.
