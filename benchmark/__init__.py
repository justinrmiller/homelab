"""Throughput and latency benchmarks for the stack's data services.

Each service has its own module, run against a hostname:

    uv run python -m benchmark.s3_bench --host nas.local

Deliberately no imports here. ``python -m benchmark.valkey_bench`` should not
have to load librdkafka's C extension to measure a key-value store.
"""
