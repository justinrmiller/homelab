"""Turn a hostname into connection settings for each service.

Precedence is CLI flag > environment > built-in default. The environment part
comes from :func:`dashboard.config.load_config`, and the results are the same
frozen dataclasses the dashboard uses, so every factory in
``dashboard.clients`` works against them unchanged.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

from dashboard.config import KafkaConfig, S3Config, ValkeyConfig, load_config

DEFAULT_S3_PORT = 4566
DEFAULT_VALKEY_PORT = 6379

# The PLAINTEXT_HOST listener, and the only one published to the host. The
# broker's other listener is kafka:29092, which resolves only inside the
# compose network.
DEFAULT_KAFKA_PORT = 9092


@dataclass(frozen=True)
class Targets:
    host: str
    s3: S3Config
    valkey: ValkeyConfig
    kafka: KafkaConfig


def _endpoint(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _split_host_port(url: str, fallback_port: int) -> tuple[str, int]:
    parts = urlsplit(url)
    return parts.hostname or "localhost", parts.port or fallback_port


def _rewrite_port(url: str, port: int) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    return urlunsplit((parts.scheme, f"{host}:{port}", parts.path, parts.query, parts.fragment))


def _bootstrap_host(bootstrap_servers: str) -> str:
    """Hostname of the first broker in a ``host:port,host:port`` string."""
    first = bootstrap_servers.split(",")[0].strip()
    return first.rsplit(":", 1)[0] if ":" in first else first


def resolve(args: argparse.Namespace) -> Targets:
    """Build per-service settings from the parsed shared arguments."""
    env = load_config()
    host: str | None = getattr(args, "host", None)
    s3_port: int | None = getattr(args, "s3_port", None)
    valkey_port: int | None = getattr(args, "valkey_port", None)
    kafka_port: int | None = getattr(args, "kafka_port", None)

    if host:
        s3 = replace(env.s3, endpoint_url=_endpoint(host, s3_port or DEFAULT_S3_PORT))
        valkey = replace(env.valkey, host=host, port=valkey_port or DEFAULT_VALKEY_PORT)
        kafka = KafkaConfig(bootstrap_servers=f"{host}:{kafka_port or DEFAULT_KAFKA_PORT}")
        return Targets(host=host, s3=s3, valkey=valkey, kafka=kafka)

    # No --host: keep whatever the environment says, but still honour an
    # explicit port flag.
    s3 = env.s3
    if s3_port is not None:
        s3 = replace(s3, endpoint_url=_rewrite_port(s3.endpoint_url, s3_port))
    valkey = env.valkey if valkey_port is None else replace(env.valkey, port=valkey_port)
    kafka = env.kafka
    if kafka_port is not None:
        broker = _bootstrap_host(env.kafka.bootstrap_servers)
        kafka = KafkaConfig(bootstrap_servers=f"{broker}:{kafka_port}")
    return Targets(host=env.valkey.host, s3=s3, valkey=valkey, kafka=kafka)


def s3_host_port(cfg: S3Config) -> tuple[str, int]:
    return _split_host_port(cfg.endpoint_url, DEFAULT_S3_PORT)
